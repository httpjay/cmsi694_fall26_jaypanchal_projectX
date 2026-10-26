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
DB_URL = "postgresql+psycopg2://jaypanchal@localhost:5432/projectx"

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
model_a = xgb.XGBRegressor(
    n_estimators=400,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    enable_categorical=True,
    tree_method="hist",
    random_state=RANDOM_SEED,
)
model_a.fit(X_train, train["target_dollars"])
pred_a = model_a.predict(X_test)
results.append(score_ranking(pred_a, "Model A: predicted dollars"))

# ---------------------------------------------------------------
# 7. MODEL B - predict chance of growth, then weight by award size
# ---------------------------------------------------------------

print("Training model B (predicting chance of growth)...")
model_b = xgb.XGBClassifier(
    n_estimators=400,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    enable_categorical=True,
    tree_method="hist",
    eval_metric="logloss",
    random_state=RANDOM_SEED,
)
model_b.fit(X_train, train["target_grew"])
prob_b = model_b.predict_proba(X_test)[:, 1]

results.append(score_ranking(prob_b, "Model B: chance of growth alone"))
results.append(
    score_ranking(prob_b * test["original_award"].values,
                  "Model B: chance x award size")
)

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

print("\nFeature importance (model A, by gain):")
imp = pd.Series(model_a.get_booster().get_score(importance_type="gain"))
for name, val in imp.sort_values(ascending=False).items():
    print(f"  {name:<28} {val:,.0f}")

res.to_csv("scrum20_results.csv", index=False)
print("\nSaved results table to scrum20_results.csv")

# ---------------------------------------------------------------
# 11. SAVE THE WATCHLIST
# ---------------------------------------------------------------

watchlist = test.copy()
watchlist["predicted_dollars"] = pred_a
watchlist["predicted_chance"] = prob_b
watchlist = watchlist.sort_values("predicted_dollars", ascending=False).head(1000)
watchlist["rank"] = range(1, len(watchlist) + 1)

names = pd.read_sql(
    "SELECT contract_award_unique_key, recipient_name FROM contract_summary",
    create_engine(DB_URL))
watchlist = watchlist.merge(names, on="contract_award_unique_key", how="left")

cols = ["recipient_name", "rank", "contract_award_unique_key", "award_date", "original_award",
        "predicted_dollars", "predicted_chance", "naics_code",
        "product_service_code", "extent_competed", "contract_pricing_type",
        "planned_duration_days", "under_umbrella",
        "target_dollars", "target_grew"]

from sqlalchemy import create_engine
engine = create_engine(DB_URL)
watchlist[cols].to_sql("watchlist", engine, if_exists="replace", index=False)
print(f"\nSaved top {len(watchlist)} contracts to the watchlist table")