"""
Load one agency's USAspending contract files into its own raw table.

    python3 Data/load_agency.py ~/Downloads/usda usda_contracts_raw

The Veterans Affairs equivalent is Data/load_data.sh, kept as it was. This
script does the same job for any agency, and is what SCRUM-28 uses to bring
in a second one.

Two things it does that the shell version did not:

  * Columns are named explicitly in the COPY. "COPY table FROM STDIN CSV
    HEADER" skips the header line but then loads by POSITION, so if two
    agencies' exports ever listed their columns in a different order the
    data would land in the wrong columns without any error at all.

  * federal_action_obligation is converted to numeric at the end. Loading
    from a CSV header makes every column text, and the first run of the
    Veterans Affairs pipeline failed on "sum(text) does not exist".
"""
import glob
import os
import sys

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "PROJECTX_DB", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx")


def main(folder, table):
    files = sorted(glob.glob(os.path.join(os.path.expanduser(folder), "*.csv")))
    if not files:
        sys.exit(f"No .csv files in {folder}")

    print(f"Found {len(files)} file(s):")
    for f in files:
        print(f"  {os.path.basename(f)}  "
              f"({os.path.getsize(f) / 1e6:,.0f} MB)")

    engine = create_engine(DB_URL)

    # Build the table from the first file's header, so the columns match the
    # export exactly. Everything arrives as text and is fixed up below.
    header = pd.read_csv(files[0], nrows=0)
    header.to_sql(table, engine, if_exists="replace", index=False)
    print(f"\nCreated {table} with {len(header.columns)} columns")

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for f in files:
            cols = list(pd.read_csv(f, nrows=0).columns)
            quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
            print(f"Loading {os.path.basename(f)} ...", flush=True)
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                cur.copy_expert(
                    f'COPY {table} ({quoted}) FROM STDIN WITH (FORMAT csv, HEADER true)',
                    fh)
        raw.commit()
    finally:
        raw.close()

    with engine.begin() as conn:
        conn.execute(text(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN federal_action_obligation TYPE numeric "
            f"USING NULLIF(federal_action_obligation, '')::numeric"))

        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"\n{table}: {total:,} rows")
        print("\nRows per fiscal year:")
        for year, n in conn.execute(text(
                f"SELECT action_date_fiscal_year, COUNT(*) FROM {table} "
                f"GROUP BY 1 ORDER BY 1")):
            print(f"  {year}  {n:,}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python3 Data/load_agency.py <folder> <table_name>")
    main(sys.argv[1], sys.argv[2])
