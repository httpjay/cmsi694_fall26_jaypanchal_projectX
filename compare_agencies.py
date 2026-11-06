"""
SCRUM-28 - does this work outside Veterans Affairs?

Everything up to now has been one agency. That is the project's biggest
weakness: a model that only works on hospital contracts is not a finding
about federal contracting, it is a finding about hospitals.

This script asks three questions of a second agency's test year:

  1. BASELINE      - how much does "check the biggest contracts" find?
  2. TRANSFERRED   - how much does the model TRAINED ON VETERANS AFFAIRS
                     find, applied to an agency it has never seen?
  3. LOCAL         - how much does the same method, retrained on the second
                     agency's own earlier year, find?

The three answers separate two different claims, and they can come apart:

  * If TRANSFERRED beats BASELINE, the trained model itself travels.
  * If TRANSFERRED fails but LOCAL beats BASELINE, the model does not
    travel but the METHOD does - which is still a real result, and the
    honest one to report if that is what happens.
  * If LOCAL also fails, the approach is specific to Veterans Affairs and
    the project should say so plainly.

    python3 compare_agencies.py usda_model_final "Agriculture"
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from models import (CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES,
                    make_classifier, make_regressor)

DB_URL = os.environ.get(
    "PROJECTX_DB", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx")

TOP_K = 200
RANDOM_SEED = 42
HOME_TABLE = "model_final"
HOME_NAME = "Veterans Affairs"


# ---------------------------------------------------------------
# Loading
# ---------------------------------------------------------------

def load(table):
    df = pd.read_sql(
        f"SELECT * FROM {table} ORDER BY contract_award_unique_key",
        create_engine(DB_URL))
    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["target_dollars"] = pd.to_numeric(
        df["target_dollars"], errors="coerce").fillna(0)
    df["target_grew"] = pd.to_numeric(
        df["target_grew"], errors="coerce").fillna(0).astype(int)
    return df


def align_categories(home, away):
    """Give both agencies the same category codes for every categorical.

    XGBoost's categorical support maps each category to an integer. Those
    integers are fixed when the model is trained, so if the two frames are
    categorised separately, code 7 might mean one industry at training time
    and a different one at scoring time - and the model would quietly score
    nonsense. Taking the union of both frames first keeps the codes aligned.
    """
    for col in CATEGORICAL_FEATURES:
        everything = pd.concat([home[col], away[col]]).astype("object")
        cats = pd.Categorical(everything).categories
        home[col] = pd.Categorical(home[col].astype("object"), categories=cats)
        away[col] = pd.Categorical(away[col].astype("object"), categories=cats)
    return home, away


# ---------------------------------------------------------------
# The model, exactly as the watchlist builds it
# ---------------------------------------------------------------

def fit_two_part(train, seed=RANDOM_SEED):
    """Model C: chance of growing x size if it grows, smearing-corrected."""
    clf = make_classifier(seed)
    clf.fit(train[FEATURES], train["target_grew"])

    growers = train[train["target_grew"] == 1]
    if len(growers) < 50:
        raise SystemExit(
            f"Only {len(growers)} contracts grew in the training half. "
            "Too few to fit the size model - this agency's data is too small "
            "or too clean for the comparison to mean anything.")

    reg = make_regressor(seed, max_depth=5)
    log_size = np.log(growers["target_dollars"].values)
    reg.fit(growers[FEATURES], log_size)
    smearing = float(np.mean(np.exp(log_size - reg.predict(growers[FEATURES]))))
    return clf, reg, smearing


def predict_two_part(models, frame):
    clf, reg, smearing = models
    chance = clf.predict_proba(frame[FEATURES])[:, 1]
    size = np.exp(reg.predict(frame[FEATURES])) * smearing
    return chance * size


def top_k_dollars(scores, dollars, k=TOP_K):
    k = min(k, len(scores))
    top = np.argpartition(-np.asarray(scores, dtype=float), k - 1)[:k]
    return float(np.asarray(dollars)[top].sum()), int(
        (np.asarray(dollars)[top] > 0).sum())


# ---------------------------------------------------------------

def main(away_table, away_name):
    print(f"Reading {HOME_TABLE} and {away_table} ...")
    home = load(HOME_TABLE)
    away = load(away_table)
    home, away = align_categories(home, away)

    home_train = home[home["split"] == "train"]
    away_train = away[away["split"] == "train"]
    away_test = away[away["split"] == "test"]

    print(f"{HOME_NAME:<22} train {len(home_train):>8,}")
    print(f"{away_name:<22} train {len(away_train):>8,}   "
          f"test {len(away_test):>8,}")
    print(f"{away_name} test year holds "
          f"${away_test['target_dollars'].sum() / 1e6:,.1f}M of unplanned growth "
          f"across {int(away_test['target_grew'].sum()):,} contracts that grew "
          f"({away_test['target_grew'].mean() * 100:.1f}%)")

    # How much of the second agency is even familiar? If most of its
    # industries never appear in Veterans Affairs, a transferred model is
    # guessing, and that explains the result before anyone argues about it.
    print("\nHow much of this agency did the Veterans Affairs model ever see?")
    for col in CATEGORICAL_FEATURES:
        seen = set(home_train[col].dropna().astype(str))
        vals = away_test[col].dropna().astype(str)
        if len(vals):
            print(f"  {col:<24}"
                  f"{vals.isin(seen).mean() * 100:5.1f}% of its contracts use a "
                  f"value that appears in {HOME_NAME}")

    results = []

    rng = np.random.default_rng(RANDOM_SEED)
    d, n = top_k_dollars(rng.random(len(away_test)), away_test["target_dollars"])
    results.append(("Random", d, n))

    d, n = top_k_dollars(away_test["original_award"].values,
                         away_test["target_dollars"])
    results.append(("Baseline: biggest award first", d, n))
    baseline = d

    print(f"\nTraining on {HOME_NAME}, scoring on {away_name} ...")
    transferred = fit_two_part(home_train)
    d, n = top_k_dollars(predict_two_part(transferred, away_test),
                         away_test["target_dollars"])
    results.append((f"Model trained on {HOME_NAME}", d, n))
    transfer = d

    print(f"Training on {away_name}, scoring on {away_name} ...")
    local = fit_two_part(away_train)
    d, n = top_k_dollars(predict_two_part(local, away_test),
                         away_test["target_dollars"])
    results.append((f"Model trained on {away_name}", d, n))
    local_score = d

    d, n = top_k_dollars(away_test["target_dollars"].values,
                         away_test["target_dollars"])
    results.append(("Perfect knowledge (ceiling)", d, n))
    ceiling = d

    print(f"\n{'=' * 74}")
    print(f"TOP {TOP_K} OF {away_name.upper()}'S TEST YEAR "
          f"({len(away_test):,} contracts)")
    print("=" * 74)
    for name, dollars, grew in results:
        print(f"{name:<38}{grew:>4} grew   "
              f"${dollars / 1e6:>7.1f}M   "
              f"{dollars / ceiling * 100 if ceiling else 0:>5.1f}% of ceiling")
    print("=" * 74)

    print()
    if transfer > baseline:
        print(f"TRANSFERS. The {HOME_NAME} model finds "
              f"${(transfer - baseline) / 1e6:,.1f}M more than the baseline on an "
              f"agency it\nhas never seen. The model itself travels.")
    else:
        print(f"DOES NOT TRANSFER. The {HOME_NAME} model finds "
              f"${(baseline - transfer) / 1e6:,.1f}M LESS than simply\nchecking the "
              f"biggest contracts. A model trained on one agency should not be\n"
              f"pointed at another.")

    if local_score > baseline:
        print(f"\nThe METHOD travels: retrained on {away_name}'s own earlier year it "
              f"finds\n${(local_score - baseline) / 1e6:,.1f}M more than the baseline.")
    else:
        print(f"\nThe method does NOT travel either: even retrained on {away_name}'s "
              f"own data\nit fails to beat the baseline. The approach appears "
              f"specific to {HOME_NAME}.")

    print("\nAll of these are single runs. Training is not repeatable "
          "(see the README),\nso treat differences of a few million as noise.")

    out = pd.DataFrame(results, columns=["method", "dollars", "contracts_grew"])
    out["pct_of_ceiling"] = (out["dollars"] / ceiling * 100).round(1)
    out.to_csv("scrum28_second_agency.csv", index=False)
    print("\nSaved to scrum28_second_agency.csv")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit('usage: python3 compare_agencies.py <table> "<Agency name>"')
    main(sys.argv[1], sys.argv[2])
