"""
SCRUM-33 - check the pipeline.

    python3 check_pipeline.py               # Veterans Affairs
    python3 check_pipeline.py usda_         # Agriculture

Every check here exists because something went wrong once. They are not
decoration: each one would have caught a real bug in this project, and they
are named after the thing that broke rather than after the table.

sql/99_verify.sql does something similar but prints numbers for a person to
compare by eye, hardcodes Veterans Affairs' row counts, and names
va_contracts_raw directly. This runs against any agency, decides pass or
fail itself, and exits non-zero so it can be wired into anything later.

What is deliberately NOT checked: exact row counts. They differ per agency
and change whenever the source files are refreshed, so asserting them would
mean a test that fails for the wrong reason. Everything below is a
relationship that must hold whatever the numbers are.
"""
import os
import sys

from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "PROJECTX_DB", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx")

# Columns that are rewritten by later modifications. If any of these ever
# reach the modelling table the model would be reading the future, and the
# results would look excellent and mean nothing.
LEAKY_COLUMNS = [
    "current_total_value_of_award",
    "base_and_exercised_options_value",
    "base_and_all_options_value",
    "potential_total_value_of_award",
    "total_dollars_obligated",
    "number_of_actions",
    "period_of_performance_current_end_date",
]

CHECKS = []


class SKIP(str):
    """A check that does not apply here. Reported as skipped, never as a pass.

    Printing "pass" for a check that did not run is worse than printing
    nothing: it is a green tick for work nobody did.
    """


def check(name, why):
    """Register a check. `why` says which real failure it guards against."""
    def wrap(fn):
        CHECKS.append((name, why, fn))
        return fn
    return wrap


# ---------------------------------------------------------------------------

@check("tables exist and are not empty",
       "a script that silently did nothing leaves an empty table behind")
def tables_present(conn, px, raw):
    problems = []
    for t in [raw, f"{px}contract_summary", f"{px}model_data",
              f"{px}growth_12mo", f"{px}award_attrs", f"{px}model_final"]:
        n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        if not n:
            problems.append(f"{t} is empty")
    return problems


@check("obligations are numeric, not text",
       "loading from a CSV header made every column text; the first run "
       "failed with 'sum(text) does not exist'")
def obligations_numeric(conn, px, raw):
    kind = conn.execute(text("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = :t AND column_name = 'federal_action_obligation'
    """), {"t": raw}).scalar()
    if kind not in ("numeric", "double precision", "real", "integer", "bigint"):
        return [f"federal_action_obligation is {kind}, not a number"]
    return []


@check("every dollar lands in exactly one category",
       "the action-type groups must partition the money, or growth is "
       "being double counted or dropped")
def dollars_reconcile(conn, px, raw):
    n = conn.execute(text(f"""
        SELECT COUNT(*) FROM {px}contract_summary
        WHERE ABS(final_total - (original_award + unplanned_growth
                  + planned_growth + reductions + other_actions)) > 0.01
    """)).scalar()
    return [f"{n:,} contracts do not reconcile"] if n else []


@check("the original award is always the earliest action",
       "the whole reconstruction rests on action_type_code IS NULL marking "
       "the base award")
def base_is_earliest(conn, px, raw):
    n = conn.execute(text(f"""
        SELECT COUNT(*) FROM (
          SELECT MIN(action_date) FILTER (WHERE action_type_code IS NULL) AS base_date,
                 MIN(action_date) AS first_date
          FROM {raw} GROUP BY contract_award_unique_key
        ) t WHERE base_date IS NOT NULL AND base_date > first_date
    """)).scalar()
    return [f"{n:,} contracts have a base award that is not the earliest row"] if n else []


@check("the modelling table is a subset of model_data",
       "growth_12mo was once built straight off the raw table, which let "
       "umbrella agreements and tiny awards back in and inflated the counts")
def final_subset_of_model_data(conn, px, raw):
    n = conn.execute(text(f"""
        SELECT COUNT(*) FROM {px}model_final f
        WHERE NOT EXISTS (SELECT 1 FROM {px}model_data m
                          WHERE m.contract_award_unique_key = f.contract_award_unique_key)
    """)).scalar()
    return [f"{n:,} contracts are in model_final but not model_data"] if n else []


@check("model_data's filters actually held",
       "the filters are what make the population comparable; if one stops "
       "applying the result changes without any visible error")
def filters_held(conn, px, raw):
    row = conn.execute(text(f"""
        SELECT COUNT(*) FILTER (WHERE cs.original_award <= 1000)      AS too_small,
               COUNT(*) FILTER (WHERE cs.award_or_idv_flag <> 'AWARD') AS umbrellas
        FROM {px}contract_summary cs
        JOIN {px}model_data m USING (contract_award_unique_key)
    """)).mappings().one()
    out = []
    if row["too_small"]:
        out.append(f"{row['too_small']:,} contracts of $1,000 or less got through")
    if row["umbrellas"]:
        out.append(f"{row['umbrellas']:,} umbrella agreements got through")
    return out


@check("no contract is in both halves of the experiment",
       "a contract appearing in training and testing would make the "
       "held-out year meaningless")
def splits_disjoint(conn, px, raw):
    n = conn.execute(text(f"""
        SELECT COUNT(*) FROM (
          SELECT contract_award_unique_key FROM {px}model_final
          GROUP BY 1 HAVING COUNT(DISTINCT split) > 1
        ) t
    """)).scalar()
    return [f"{n:,} contracts appear in both splits"] if n else []


@check("the train/test boundary is where it should be",
       "the split is by date; if the boundary moves, training can see the "
       "test year")
def split_boundary(conn, px, raw):
    row = conn.execute(text(f"""
        SELECT MAX(award_date) FILTER (WHERE split = 'train') AS train_last,
               MIN(award_date) FILTER (WHERE split = 'test')  AS test_first,
               MAX(award_date) FILTER (WHERE split = 'test')  AS test_last
        FROM {px}model_final
    """)).mappings().one()
    out = []
    if row["train_last"] and str(row["train_last"]) > "2017-09-30":
        out.append(f"training runs to {row['train_last']}, past 2017-09-30")
    if row["test_first"] and str(row["test_first"]) < "2017-10-01":
        out.append(f"testing starts {row['test_first']}, before 2017-10-01")
    if row["test_last"] and str(row["test_last"]) > "2018-09-30":
        out.append(f"testing runs to {row['test_last']}, past 2018-09-30")
    return out


@check("the two targets agree with each other",
       "target_grew is derived from target_dollars; if they disagree one "
       "of them is stale")
def targets_agree(conn, px, raw):
    n = conn.execute(text(f"""
        SELECT COUNT(*) FROM {px}model_final
        WHERE (target_dollars > 0) <> (target_grew = 1)
    """)).scalar()
    return [f"{n:,} contracts where target_grew and target_dollars disagree"] if n else []


@check("no column that contains the future reached the model",
       "these columns are rewritten on every modification, so a row from "
       "month one already shows the contract's final total")
def no_leakage(conn, px, raw):
    found = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = :t AND column_name = ANY(:cols)
    """), {"t": f"{px}model_final", "cols": LEAKY_COLUMNS}).scalars().all()
    return [f"post-award column in the modelling table: {c}" for c in found]


@check("the watchlist is ranked 1..N with no gaps or ties",
       "the running total and the top-K measure both read the list in rank "
       "order, so a duplicate or missing rank silently shifts them")
def watchlist_ranked(conn, px, raw):
    if px:
        return SKIP("the watchlist is only built for the main agency")
    exists = conn.execute(text(
        "SELECT to_regclass('watchlist') IS NOT NULL")).scalar()
    if not exists:
        return ["watchlist table does not exist - has train_model.py been run?"]
    row = conn.execute(text("""
        SELECT COUNT(*) AS n, COUNT(DISTINCT "rank") AS distinct_ranks,
               MIN("rank") AS lo, MAX("rank") AS hi FROM watchlist
    """)).mappings().one()
    out = []
    repeated = row["n"] - row["distinct_ranks"]
    if repeated:
        out.append(f"{repeated:,} rank{'s are' if repeated > 1 else ' is'} used twice")
    if row["lo"] != 1 or row["hi"] != row["n"]:
        out.append(f"ranks run {row['lo']}..{row['hi']} over {row['n']:,} rows")
    return out


# ---------------------------------------------------------------------------

def main(px="", agency=None):
    raw = f"{px}contracts_raw" if px else "va_contracts_raw"
    # The prefix is a table name, not a readable name, so the second argument
    # supplies one. Without it the prefix is printed as it is rather than
    # guessed at.
    agency = agency or (f"'{px}'" if px else "Veterans Affairs")

    print(f"Checking the {agency} pipeline\n")
    engine = create_engine(DB_URL)
    failures = skipped = 0

    with engine.connect() as conn:
        for name, why, fn in CHECKS:
            try:
                problems = fn(conn, px, raw)
            except Exception as exc:                      # a check that cannot
                problems = [f"could not run: {exc}"]      # run has not passed
            finally:
                # One failed query leaves the connection in an aborted
                # transaction, and every later check then fails with
                # "current transaction is aborted" instead of its own
                # result. Rolling back after each check keeps the checks
                # independent, so the report says what is really wrong.
                conn.rollback()
            if isinstance(problems, SKIP):
                skipped += 1
                print(f"skip  {name}\n        {problems}")
            elif problems:
                failures += 1
                print(f"FAIL  {name}")
                for p in problems:
                    print(f"        {p}")
                print(f"        why this matters: {why}")
            else:
                print(f"pass  {name}")

    ran = len(CHECKS) - skipped
    tail = f" ({skipped} skipped)" if skipped else ""
    print()
    if failures:
        print(f"{failures} of {ran} checks failed{tail}.")
        sys.exit(1)
    print(f"All {ran} checks passed{tail}.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
