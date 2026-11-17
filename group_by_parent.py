"""
SCRUM-32 - what happens if sibling orders are grouped?

Orders placed against the same umbrella agreement are separate contracts and
the model scores each one separately. That is correct: they are separately
awarded and separately modified. But a reviewer reading the list sees the
consequence - one vendor can hold five of the first ten slots, and those five
slots are gone whether or not the five orders are really five different
problems.

This asks whether that costs anything, three ways, all on the same held-out
test year:

  AS IT STANDS   the top 200 of the watchlist exactly as it is now.

  DEDUPLICATED   read down the same ranked list, but skip a contract whose
                 parent agreement has already appeared, until 200 are
                 collected. Same amount of reviewing - 200 things to look at
                 - spread over 200 different agreements.

  BY AGREEMENT   pick the 200 highest-ranked agreements and credit every
                 dollar of growth underneath them, across the whole test
                 year. This is NOT the same amount of work: 200 agreements
                 can contain far more than 200 contracts, so a bigger number
                 here is expected and does not on its own mean better. It is
                 reported because it answers a different question - whether
                 the money is concentrated in a few agreements - and the
                 contract count is printed alongside so the cost is visible.

The honest outcome is whichever comes out. Deduplication helps only if the
slots freed up are worth more than the siblings they displace; if the sibling
orders were genuinely growing, removing them loses real money.

    python3 group_by_parent.py                      # Veterans Affairs
    python3 group_by_parent.py usda_model_final     # a second agency
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

DB_URL = os.environ.get(
    "PROJECTX_DB", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx")

TOP_K = 200


def group_key(frame):
    """One key per agreement; a contract with no parent is its own group.

    Grouping on parent_award_id alone would put every standalone contract
    into one enormous 'no parent' group, and deduplication would then throw
    almost the whole list away.
    """
    return frame["parent_award_id"].where(
        frame["parent_award_id"].notna(),
        "SOLO:" + frame["contract_award_unique_key"].astype(str))


def deduplicate(frame, k):
    """Walk the ranked list, taking at most one contract per agreement."""
    seen, keep = set(), []
    for idx, key in zip(frame.index, group_key(frame)):
        if key in seen:
            continue
        seen.add(key)
        keep.append(idx)
        if len(keep) == k:
            break
    return frame.loc[keep]


def main(final_table="model_final", agency="Veterans Affairs"):
    engine = create_engine(DB_URL)

    watchlist = pd.read_sql(
        'SELECT * FROM watchlist ORDER BY "rank"', engine)
    test = pd.read_sql(
        f"SELECT * FROM {final_table} WHERE split = 'test'", engine)

    for frame in (watchlist, test):
        frame["target_dollars"] = pd.to_numeric(
            frame["target_dollars"], errors="coerce").fillna(0)

    print(f"{agency}: watchlist of {len(watchlist):,}, "
          f"test year of {len(test):,} contracts\n")

    # ---------------------------------------------------------------
    # How crowded is the list?
    # ---------------------------------------------------------------
    top = watchlist.head(TOP_K).copy()
    top["key"] = group_key(top)
    sizes = top["key"].value_counts()
    repeated = sizes[sizes > 1]

    print("=" * 72)
    print(f"HOW MUCH OF THE TOP {TOP_K} IS THE SAME AGREEMENT TWICE?")
    print("=" * 72)
    print(f"{TOP_K} contracts sit under {top['key'].nunique():,} "
          f"different agreements.")
    print(f"{int(repeated.sum()):,} of them share an agreement with at least "
          f"one other contract on the list.")
    if len(repeated):
        print(f"\nThe most crowded agreements:")
        for key, n in repeated.head(5).items():
            rows = top[top["key"] == key]
            name = rows["recipient_name"].dropna()
            name = name.iloc[0] if len(name) else "name not recorded"
            grew = int((rows["target_dollars"] > 0).sum())
            print(f"  {n} slots  {name[:44]:<44} "
                  f"{grew} of {n} actually grew")

    # ---------------------------------------------------------------
    # Three ways of spending the same review effort
    # ---------------------------------------------------------------
    as_it_stands = float(top["target_dollars"].sum())

    deduped = deduplicate(watchlist, TOP_K)
    deduped_total = float(deduped["target_dollars"].sum())

    # By agreement: rank agreements by their best-placed member, then credit
    # everything underneath them across the whole test year.
    test = test.copy()
    test["key"] = group_key(test)
    best_rank = (watchlist.assign(key=group_key(watchlist))
                 .groupby("key")["rank"].min())
    by_agreement_keys = best_rank.sort_values().head(TOP_K).index
    chosen = test[test["key"].isin(by_agreement_keys)]
    by_agreement_total = float(chosen["target_dollars"].sum())

    print(f"\n{'=' * 72}")
    print(f"WHAT THE SAME {TOP_K} SLOTS FIND, THREE WAYS")
    print("=" * 72)
    print(f"{'':<34}{'contracts':>11}{'found':>12}")
    print(f"{'As it stands':<34}{TOP_K:>11,}"
          f"{'$' + format(as_it_stands / 1e6, ',.1f') + 'M':>12}")
    print(f"{'Deduplicated by agreement':<34}{len(deduped):>11,}"
          f"{'$' + format(deduped_total / 1e6, ',.1f') + 'M':>12}")
    print(f"{'By agreement (not equal effort)':<34}{len(chosen):>11,}"
          f"{'$' + format(by_agreement_total / 1e6, ',.1f') + 'M':>12}")
    print("=" * 72)

    diff = deduped_total - as_it_stands
    print()
    if abs(diff) < 0.02 * max(as_it_stands, 1):
        print("Deduplicating makes almost no difference to the money found.")
        print("The repeated agreements are not crowding out anything better,")
        print("so grouping is a readability change, not a performance one.")
    elif diff > 0:
        print(f"Deduplicating finds ${diff / 1e6:,.1f}M MORE with the same 200")
        print("slots. The repeated agreements were crowding out contracts that")
        print("were worth more, so showing one row per agreement is worth doing")
        print("for the result as well as for readability.")
    else:
        print(f"Deduplicating finds ${abs(diff) / 1e6:,.1f}M LESS with the same")
        print("200 slots. The sibling orders really were growing, so collapsing")
        print("them costs money. Grouping should be a display choice the")
        print("reviewer can switch on, not something done to the ranking.")

    print(f"\nReading at agreement level covers {len(chosen):,} contracts "
          f"instead of {TOP_K},")
    print(f"so its ${by_agreement_total / 1e6:,.1f}M is not comparable to the "
          f"other two. It is\nhere to show how concentrated the money is, not "
          f"to claim an improvement.")

    out = pd.DataFrame([
        {"method": "as it stands", "contracts": TOP_K, "dollars": as_it_stands},
        {"method": "deduplicated", "contracts": len(deduped),
         "dollars": deduped_total},
        {"method": "by agreement", "contracts": len(chosen),
         "dollars": by_agreement_total},
    ])
    out.to_csv("scrum32_grouping.csv", index=False)
    print("\nSaved to scrum32_grouping.csv")


if __name__ == "__main__":
    table = sys.argv[1] if len(sys.argv) > 1 else "model_final"
    name = sys.argv[2] if len(sys.argv) > 2 else "Veterans Affairs"
    main(table, name)
