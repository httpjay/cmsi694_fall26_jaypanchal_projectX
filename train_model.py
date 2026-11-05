"""
Project X - SCRUM-20
First trained model, scored against the baseline on the time-based holdout.

What this does:
  1. Loads model_final from Postgres (or a CSV export of it)
  2. Trains two models on the training half only
  3. Ranks the test half three ways and measures dollars of growth captured
  4. Prints a comparison table and a verdict

Run:  python3 train_model.py
"""

import sys
import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy import create_engine

# ---------------------------------------------------------------
# 1. SETTINGS - edit these
# ---------------------------------------------------------------

# Option A: read straight from Postgres. Fill in your details.
# Setting the PROJECTX_DB environment variable overrides this, which is how
# the serving layer is configured too.
import os
DB_URL = os.environ.get(
    "PROJECTX_DB", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx")

# Option B: if the database connection is a nuisance, export model_final
# to CSV from pgAdmin and put the path here instead. Leave as None to use the DB.
CSV_PATH = None

TOP_K = 200        # watchlist size
RANDOM_SEED = 42

# ---------------------------------------------------------------
# 2. LOAD
# ---------------------------------------------------------------

def load_data():
    if CSV_PATH:
        print(f"Reading {CSV_PATH}")
        return pd.read_csv(CSV_PATH)
    print("Reading model_final from Postgres")
    try:
        from sqlalchemy import create_engine
        engine = create_engine(DB_URL)
        return pd.read_sql("SELECT * FROM model_final", engine)
    except ImportError:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        df = pd.read_sql("SELECT * FROM model_final", conn)
        conn.close()
        return df


df = load_data()
print(f"Loaded {len(df):,} rows")

# ---------------------------------------------------------------
# 3. PREPARE FEATURES
# ---------------------------------------------------------------

# Everything here is known on the day of award. See the feature
# labelling document on SCRUM-17 for why each is included.
NUMERIC_FEATURES = [
    "original_award",
    "log_award",
    "award_month",
    "under_umbrella",
    "planned_duration_days",
]

CATEGORICAL_FEATURES = [
    "naics_code",
    "product_service_code",
    "contract_pricing_type",
    "extent_competed",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

for col in NUMERIC_FEATURES:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# XGBoost handles categories natively, but the categories must be
# defined across the whole dataset so train and test agree on the codes.
for col in CATEGORICAL_FEATURES:
    df[col] = df[col].astype("category")

df["target_dollars"] = pd.to_numeric(df["target_dollars"], errors="coerce").fillna(0)
df["target_grew"] = pd.to_numeric(df["target_grew"], errors="coerce").fillna(0).astype(int)

train = df[df["split"] == "train"].copy()
test = df[df["split"] == "test"].copy()

print(f"Train: {len(train):,} contracts   Test: {len(test):,} contracts")
print(f"Train growth total: ${train['target_dollars'].sum()/1e6:,.1f}M")
print(f"Test  growth total: ${test['target_dollars'].sum()/1e6:,.1f}M")

X_train, X_test = train[FEATURES], test[FEATURES]

# ---------------------------------------------------------------
# 3b. MODEL SETTINGS IN ONE PLACE
# ---------------------------------------------------------------
# Both the main run and the seed-stability check below build the same three
# models. Defining them once means the two can never drift apart.

def make_regressor(seed, max_depth=6):
    return xgb.XGBRegressor(
        n_estimators=400,
        max_depth=max_depth,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        enable_categorical=True,
        tree_method="hist",
        random_state=seed,
    )


def make_classifier(seed):
    return xgb.XGBClassifier(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        enable_categorical=True,
        tree_method="hist",
        eval_metric="logloss",
        random_state=seed,
    )


# ---------------------------------------------------------------
# 4. SCORING FUNCTION
# ---------------------------------------------------------------

def score_ranking(scores, name):
    """Take the top K contracts by `scores` and report what they caught."""
    order = np.argsort(-np.asarray(scores))
    picked = test.iloc[order[:TOP_K]]
    return {
        "method": name,
        "grew": int(picked["target_grew"].sum()),
        "dollars_m": picked["target_dollars"].sum() / 1e6,
    }


results = []

# ---------------------------------------------------------------
# 5. BASELINES
# ---------------------------------------------------------------

rng = np.random.default_rng(RANDOM_SEED)
results.append(score_ranking(rng.random(len(test)), "Random"))
results.append(score_ranking(test["original_award"].values, "Baseline: biggest award first"))

# ---------------------------------------------------------------
# 6. MODEL A - predict growth dollars directly
# ---------------------------------------------------------------

print("\nTraining model A (predicting growth dollars)...")
model_a = make_regressor(RANDOM_SEED)
model_a.fit(X_train, train["target_dollars"])
pred_a = model_a.predict(X_test)
results.append(score_ranking(pred_a, "Model A: predicted dollars"))

# ---------------------------------------------------------------
# 7. MODEL B - predict chance of growth, then weight by award size
# ---------------------------------------------------------------

print("Training model B (predicting chance of growth)...")
model_b = make_classifier(RANDOM_SEED)
model_b.fit(X_train, train["target_grew"])
prob_b = model_b.predict_proba(X_test)[:, 1]

results.append(score_ranking(prob_b, "Model B: chance of growth alone"))
results.append(
    score_ranking(prob_b * test["original_award"].values,
                  "Model B: chance x award size")
)

# ---------------------------------------------------------------
# 7b. MODEL C - two-part model, so the predicted amount means something
# ---------------------------------------------------------------
#
# Why this exists.
#
# Model A predicts dollars directly using squared-error loss. Almost every
# contract grows by zero and a handful grow by tens of millions. Fitting the
# AVERAGE of a target shaped like that drags every prediction upward: model A
# will happily predict $111M of growth on a contract that was signed for $1M.
# That ordering is still useful, but the number itself is not a believable
# estimate of anything, and showing it to a reviewer overclaims.
#
# A two-part (hurdle) model separates the two questions that are actually
# being asked:
#
#     will it grow at all?      -> the classifier, model B
#     if it grows, how much?    -> a regressor trained ONLY on contracts
#                                  that grew, on the log of the amount
#
#     expected growth = chance of growing  x  typical size if it grows
#
# The log is needed because growth amounts span six orders of magnitude.
# But exp() of an average log is NOT the average - it systematically
# underestimates. Duan's smearing estimate corrects that, using the spread
# of the training residuals, and is the standard fix for this bias.

print("Training model C (two-part: chance of growing x size if it grows)...")

growers = train[train["target_grew"] == 1]
print(f"  {len(growers):,} of {len(train):,} training contracts grew "
      f"({len(growers)/len(train)*100:.1f}%)")

model_c = make_regressor(RANDOM_SEED, max_depth=5)
log_size = np.log(growers["target_dollars"].values)
model_c.fit(growers[FEATURES], log_size)

# Duan's smearing estimate: the average of exp(residual) on the training
# growers. Multiplying by this turns exp(predicted log) back into a proper
# expected amount instead of something closer to a median.
residuals = log_size - model_c.predict(growers[FEATURES])
smearing = float(np.mean(np.exp(residuals)))
print(f"  smearing correction factor: {smearing:.3f}")

size_if_grows = np.exp(model_c.predict(X_test)) * smearing
pred_c = prob_b * size_if_grows

results.append(score_ranking(pred_c, "Model C: two-part expected dollars"))

# ---------------------------------------------------------------
# 8. CEILING
# ---------------------------------------------------------------

results.append(score_ranking(test["target_dollars"].values, "Perfect knowledge"))

# ---------------------------------------------------------------
# 9. RESULTS
# ---------------------------------------------------------------

res = pd.DataFrame(results)
ceiling = res.loc[res["method"] == "Perfect knowledge", "dollars_m"].iloc[0]
baseline = res.loc[res["method"].str.startswith("Baseline"), "dollars_m"].iloc[0]
res["pct_of_ceiling"] = (res["dollars_m"] / ceiling * 100).round(1)

print(f"\n{'='*70}")
print(f"TOP {TOP_K} CONTRACTS FROM THE HELD-OUT TEST YEAR ({len(test):,} contracts)")
print("="*70)
for r in res.itertuples():
    print(f"{r.method:<36} {r.grew:>4} grew   ${r.dollars_m:>7.1f}M   {r.pct_of_ceiling:>5.1f}% of ceiling")
print("="*70)

models_only = res[res["method"].str.startswith("Model")]
best = models_only.sort_values("dollars_m").iloc[-1]
lift = best["dollars_m"] - baseline

print(f"\nBaseline captured  ${baseline:.1f}M")
print(f"Best model captured ${best['dollars_m']:.1f}M  ({best['method']})")
print(f"Difference          ${lift:+.1f}M")

if lift > baseline * 0.10:
    verdict = "IMPROVEMENT - the model beats the baseline by a clear margin."
elif lift > 0:
    verdict = "MARGINAL - the model beats the baseline, but not by much."
else:
    verdict = "NO IMPROVEMENT - award-time information does not beat ranking by size."
print(f"\nVerdict: {verdict}")

# ---------------------------------------------------------------
# 10. WHICH FEATURES MATTERED
# ---------------------------------------------------------------

# ---------------------------------------------------------------
# 9b. CALIBRATION - is the predicted AMOUNT believable, not just the order?
# ---------------------------------------------------------------
#
# Ranking well and predicting well are different jobs. A model can sort
# contracts perfectly while every dollar figure it prints is nonsense.
# The watchlist shows those figures to a human, so they have to be checked.

actual_total = test["target_dollars"].sum()
actual_max = test["target_dollars"].max()

print(f"\n{'='*70}")
print("CALIBRATION - do the predicted amounts mean anything?")
print("="*70)
print(f"{'':<34}{'total predicted':>17}{'vs actual':>10}{'largest':>12}")
print(f"{'Actual growth in the test year':<34}"
      f"{'$' + format(actual_total/1e6, ',.1f') + 'M':>17}{'1.0x':>10}"
      f"{'$' + format(actual_max/1e6, ',.1f') + 'M':>12}")

for name, pred in [("Model A: dollars direct", pred_a),
                   ("Model C: two-part", pred_c)]:
    tot = float(np.sum(pred))
    print(f"{name:<34}{'$' + format(tot/1e6, ',.1f') + 'M':>17}"
          f"{format(tot/actual_total, ',.1f') + 'x':>10}"
          f"{'$' + format(float(np.max(pred))/1e6, ',.1f') + 'M':>12}")

# The clearest symptom of the problem: predicting more growth than the
# contract is worth in the first place.
for name, pred in [("Model A", pred_a), ("Model C", pred_c)]:
    over = int(np.sum(np.asarray(pred) > test["original_award"].values))
    print(f"{name} predicts more growth than the whole contract value "
          f"on {over:,} of {len(test):,} contracts ({over/len(test)*100:.1f}%)")

# Calibrating the amount may cost something in ranking. Say so plainly
# rather than leaving it buried in the table above.
a_m = next(r["dollars_m"] for r in results if r["method"].startswith("Model A"))
c_m = next(r["dollars_m"] for r in results if r["method"].startswith("Model C"))
gap = c_m - a_m
print()
if abs(gap) < 0.05 * max(a_m, 1):
    print(f"Ranking cost of calibrating: none worth mentioning "
          f"(${a_m:.1f}M vs ${c_m:.1f}M in the top {TOP_K}).")
elif gap < 0:
    print(f"Ranking cost of calibrating: ${abs(gap):.1f}M. Model A catches "
          f"${a_m:.1f}M in the top {TOP_K}, model C catches ${c_m:.1f}M.")
    print("  The watchlist uses model C anyway, because model A's dollar")
    print("  figures cannot be shown to a reviewer honestly. If that gap is")
    print("  too large to accept, the fix is a better size model, not a")
    print("  return to uncalibrated predictions.")
else:
    print(f"Calibrating also improved the ranking by ${gap:.1f}M "
          f"in the top {TOP_K}.")
print("="*70)

# ---------------------------------------------------------------
# 9c. IS THE IMPROVEMENT REAL, OR ONE LUCKY RUN?
# ---------------------------------------------------------------
#
# Every number above comes from a single test year. The headline claim -
# "the model beats the baseline" - could be an accident of which contracts
# happened to land in that year. Growth is rare and enormously skewed: a
# handful of contracts hold most of the money, so swapping two of them in or
# out could move the total by millions.
#
# The bootstrap asks the question directly. Draw a new test set the same size
# as the real one, sampling contracts WITH replacement, and score both
# rankings on it. Repeat many times. The spread of the answers tells you how
# much the result depends on luck.
#
# What matters is not whether each total is stable - they will not be - but
# whether the DIFFERENCE between model and baseline stays positive.

N_BOOTSTRAP = 400

print(f"\n{'='*70}")
print(f"IS THE IMPROVEMENT REAL? {N_BOOTSTRAP} resampled test years")
print("="*70)

def top_k_dollars(scores, dollars, k):
    """Dollars captured by the best k contracts under this ranking."""
    k = min(k, len(scores))
    top = np.argpartition(-scores, k - 1)[:k]
    return float(dollars[top].sum())

boot_rng = np.random.default_rng(RANDOM_SEED)
y_test = test["target_dollars"].values
score_model = np.asarray(pred_c, dtype=float)
score_base = test["original_award"].values.astype(float)
n_test = len(y_test)

boot_model, boot_base = [], []
for _ in range(N_BOOTSTRAP):
    idx = boot_rng.integers(0, n_test, n_test)
    boot_model.append(top_k_dollars(score_model[idx], y_test[idx], TOP_K))
    boot_base.append(top_k_dollars(score_base[idx], y_test[idx], TOP_K))

boot_model = np.array(boot_model)
boot_base = np.array(boot_base)
boot_diff = boot_model - boot_base

def band(a):
    lo, mid, hi = np.percentile(a, [2.5, 50, 97.5])
    typical = f"${mid/1e6:,.1f}M"
    return f"{typical:>10}   95% of the time between ${lo/1e6:,.1f}M and ${hi/1e6:,.1f}M"

print(f"{'':<26}{'typical':>10}")
print(f"{'Model C, top ' + str(TOP_K):<26}{band(boot_model)}")
print(f"{'Baseline, top ' + str(TOP_K):<26}{band(boot_base)}")
print(f"{'Difference':<26}{band(boot_diff)}")

wins = int((boot_diff > 0).sum())
print(f"\nThe model beat the baseline in {wins} of {N_BOOTSTRAP} resampled "
      f"years ({wins/N_BOOTSTRAP*100:.1f}%).")

lo_diff = float(np.percentile(boot_diff, 2.5))
if lo_diff > 0:
    print("The 95% range for the difference stays above zero, so the")
    print("improvement is not explained by which contracts landed in the")
    print("test year.")
else:
    print("The 95% range for the difference crosses zero. The improvement")
    print("is NOT established - on some plausible test years the baseline")
    print("does as well or better. This has to be reported as it is.")
print("="*70)

pd.DataFrame({"model": boot_model, "baseline": boot_base,
              "difference": boot_diff}).to_csv("scrum27_bootstrap.csv", index=False)
print("Saved every resampled result to scrum27_bootstrap.csv")

# ---------------------------------------------------------------
# 9d. HOW MUCH DOES THE ANSWER DEPEND ON THE RANDOM SEED?
# ---------------------------------------------------------------
#
# The bootstrap above asks what happens if the TEST YEAR had been different.
# This asks something separate: what happens if the TRAINING had gone
# slightly differently.
#
# XGBoost is not fully deterministic here. subsample and colsample_bytree
# draw at random, and tree_method="hist" splits work across threads, so the
# order they finish in is not fixed. Two runs of identical code on identical
# data give slightly different trees.
#
# That would not matter for a stable measure. It matters a great deal here,
# because the top 200 is decided by a handful of enormous contracts: a small
# change in the model reshuffles which of them make the cut, and the total
# moves by millions. Running several seeds turns that hidden wobble into a
# measured range that can be reported.

SEEDS = [42, 7, 123, 2024, 99]

print(f"\n{'='*70}")
print(f"DOES THE ANSWER DEPEND ON THE RANDOM SEED? {len(SEEDS)} training runs")
print("="*70)


def capture_for_seed(seed):
    """Train all three models with this seed, return top-K dollars captured."""
    ma = make_regressor(seed)
    ma.fit(X_train, train["target_dollars"])
    pa = ma.predict(X_test)

    mb = make_classifier(seed)
    mb.fit(X_train, train["target_grew"])
    pb = mb.predict_proba(X_test)[:, 1]

    g = train[train["target_grew"] == 1]
    mc = make_regressor(seed, max_depth=5)
    ls = np.log(g["target_dollars"].values)
    mc.fit(g[FEATURES], ls)
    sm = float(np.mean(np.exp(ls - mc.predict(g[FEATURES]))))
    pc = pb * np.exp(mc.predict(X_test)) * sm

    return {
        "seed": seed,
        "Model A: dollars direct": top_k_dollars(pa, y_test, TOP_K),
        "Model C: two-part": top_k_dollars(pc, y_test, TOP_K),
        "smearing": sm,
    }


seed_runs = []
for s in SEEDS:
    print(f"  training with seed {s}...")
    seed_runs.append(capture_for_seed(s))

seed_df = pd.DataFrame(seed_runs)
base_capture = top_k_dollars(score_base, y_test, TOP_K)

print(f"\n{'':<26}{'typical':>10}{'lowest':>11}{'highest':>11}{'spread':>11}")
for col in ["Model A: dollars direct", "Model C: two-part"]:
    v = seed_df[col].values
    print(f"{col:<26}{'$' + format(np.median(v)/1e6, ',.1f') + 'M':>10}"
          f"{'$' + format(v.min()/1e6, ',.1f') + 'M':>11}"
          f"{'$' + format(v.max()/1e6, ',.1f') + 'M':>11}"
          f"{'$' + format((v.max()-v.min())/1e6, ',.1f') + 'M':>11}")
print(f"{'Baseline: biggest first':<26}{'$' + format(base_capture/1e6, ',.1f') + 'M':>10}"
      f"      no randomness, so always the same")

a_v = seed_df["Model A: dollars direct"].values
c_v = seed_df["Model C: two-part"].values

print(f"\nSmearing factor ranged from {seed_df['smearing'].min():.3f} "
      f"to {seed_df['smearing'].max():.3f}.")

worst_model = min(a_v.min(), c_v.min())
if worst_model > base_capture:
    print(f"Every run of both models beat the baseline's "
          f"${base_capture/1e6:,.1f}M, so the advantage does not depend on "
          f"the seed.")
else:
    print(f"At least one run fell to ${worst_model/1e6:,.1f}M, below the "
          f"baseline's ${base_capture/1e6:,.1f}M. The advantage is not")
    print("robust to the training seed and must be reported that way.")

# Model A and Model C get compared a lot above. Say plainly whether a single
# run can actually tell them apart.
if min(a_v.max(), c_v.max()) > max(a_v.min(), c_v.min()):
    print("\nThe ranges for Model A and Model C overlap, so a single run")
    print("cannot say which ranks better. Any claim that one beats the other")
    print("needs the average across seeds, not one number.")
else:
    better = "A" if np.median(a_v) > np.median(c_v) else "C"
    print(f"\nThe ranges do not overlap: Model {better} ranks better across "
          f"every seed tried.")

print("="*70)
seed_df.to_csv("scrum27_seeds.csv", index=False)
print("Saved the per-seed results to scrum27_seeds.csv")

print("\nFeature importance (model A, by gain):")
imp = pd.Series(model_a.get_booster().get_score(importance_type="gain"))
for name, val in imp.sort_values(ascending=False).items():
    print(f"  {name:<28} {val:,.0f}")

res.to_csv("scrum20_results.csv", index=False)
print("\nSaved results table to scrum20_results.csv")

# ---------------------------------------------------------------
# 11. SAVE THE WATCHLIST
# ---------------------------------------------------------------

# The watchlist is ranked and labelled with model C, not model A. Model A's
# ordering is comparable, but its dollar figures are not defensible to show
# to a person - see the calibration table above.

from sqlalchemy import create_engine
engine = create_engine(DB_URL)

watchlist = test.copy()
watchlist["predicted_dollars"] = pred_c
watchlist["predicted_chance"] = prob_b
watchlist["predicted_size_if_grows"] = size_if_grows
watchlist = watchlist.sort_values("predicted_dollars", ascending=False).head(1000)
watchlist["rank"] = range(1, len(watchlist) + 1)

names = pd.read_sql(
    "SELECT contract_award_unique_key, recipient_name FROM contract_summary",
    engine)
watchlist = watchlist.merge(names, on="contract_award_unique_key", how="left")

cols = ["rank", "contract_award_unique_key", "recipient_name",
        "award_date", "original_award",
        "predicted_dollars", "predicted_chance", "predicted_size_if_grows",
        "naics_code", "product_service_code", "extent_competed",
        "contract_pricing_type", "planned_duration_days", "under_umbrella",
        "target_dollars", "target_grew"]

watchlist[cols].to_sql("watchlist", engine, if_exists="replace", index=False)
print(f"\nSaved top {len(watchlist)} contracts to the watchlist table")
print(f"Top 200 of the saved watchlist caught "
      f"${watchlist.head(200)['target_dollars'].sum()/1e6:,.1f}M "
      f"({int(watchlist.head(200)['target_grew'].sum())} of 200 grew)")