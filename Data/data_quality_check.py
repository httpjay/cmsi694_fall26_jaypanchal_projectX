"""
SCRUM-13: Data quality report for the Veterans Affairs contract data.

Reads the va_contracts_raw table (loaded by load_data.sh), runs data
quality checks, and writes the results to docs/data_quality_report.md.

Run from the repository root:
    python3 Data/data_quality_check.py

To use a different database, set the DATABASE_URL environment variable.
"""

import os
import re
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, inspect

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://jaypanchal@localhost:5432/projectx"
)
TABLE = "va_contracts_raw"
REPORT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "docs", "data_quality_report.md"
)

EXPECTED_ROWS = {2017: 220_729, 2018: 184_728, 2019: 133_995}

ID_COLUMNS = [
    "contract_transaction_unique_key",
    "contract_award_unique_key",
    "award_id_piid",
    "modification_number",
]
DATE_COLUMNS = [
    "action_date",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "period_of_performance_potential_end_date",
]
DOLLAR_COLUMNS = [
    "federal_action_obligation",
    "base_and_exercised_options_value",
    "base_and_all_options_value",
    "current_total_value_of_award",
    "potential_total_value_of_award",
]
CATEGORY_COLUMNS = [
    "naics_code",
    "naics_description",
    "product_or_service_code",
    "type_of_contract_pricing",
    "award_type",
    "extent_competed",
    "number_of_offers_received",
    "awarding_sub_agency_name",
    "recipient_uei",
    "recipient_duns",
    "recipient_name",
]
YEAR_COLUMN = "action_date_fiscal_year"

# Missing-value rules used for the field verdicts
TRUSTWORTHY_MAX = 0.01   # under 1% missing
USE_WITH_CARE_MAX = 0.20  # 1% to 20% missing; above this is not trustworthy

LARGE_DOLLAR = 1_000_000_000  # one billion dollars
EARLIEST_DATE = pd.Timestamp("1980-01-01")
LATEST_DATE = pd.Timestamp("2100-01-01")


def pct(part, whole):
    return 0.0 if whole == 0 else 100.0 * part / whole


def fmt_int(n):
    return f"{int(n):,}"


def fmt_pct(p):
    return f"{p:.2f}%"


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def verdict(missing_share):
    if missing_share < TRUSTWORTHY_MAX:
        return "Trustworthy"
    if missing_share <= USE_WITH_CARE_MAX:
        return "Use with care"
    return "Not trustworthy"


def load(engine):
    available = {c["name"] for c in inspect(engine).get_columns(TABLE)}
    wanted = ID_COLUMNS + DATE_COLUMNS + DOLLAR_COLUMNS + CATEGORY_COLUMNS + [YEAR_COLUMN]
    present = [c for c in wanted if c in available]
    absent = [c for c in wanted if c not in available]
    cols = ", ".join(f'"{c}"' for c in present)
    df = pd.read_sql(f'SELECT {cols} FROM "{TABLE}"', engine, dtype=str)
    # Treat empty or blank text as missing
    df = df.apply(lambda s: s.str.strip()).replace("", pd.NA)
    return df, present, absent


def check_row_counts(df):
    if YEAR_COLUMN not in df:
        return "Column `action_date_fiscal_year` not found, so row counts per year were not checked.", []
    years = pd.to_numeric(df[YEAR_COLUMN], errors="coerce")
    counts = years.value_counts().sort_index()
    rows, problems = [], []
    for year, expected in EXPECTED_ROWS.items():
        actual = int(counts.get(year, 0))
        ok = "Yes" if actual == expected else "No"
        if actual != expected:
            problems.append(f"Fiscal year {year} has {fmt_int(actual)} rows, expected {fmt_int(expected)}.")
        rows.append([year, fmt_int(expected), fmt_int(actual), ok])
    other = int(years[~years.isin(EXPECTED_ROWS.keys())].shape[0])
    rows.append(["Other or missing", "0", fmt_int(other), "Yes" if other == 0 else "No"])
    if other:
        problems.append(f"{fmt_int(other)} rows have a fiscal year outside 2017 to 2019 or no fiscal year.")
    return md_table(["Fiscal year", "Expected rows", "Actual rows", "Matches"], rows), problems


def check_missing(df, present):
    n = len(df)
    rows, results = [], {}
    for c in present:
        missing = int(df[c].isna().sum())
        share = missing / n if n else 0.0
        results[c] = share
        rows.append([f"`{c}`", fmt_int(missing), fmt_pct(100 * share), verdict(share)])
    return md_table(["Field", "Missing rows", "Missing share", "Verdict"], rows), results


def check_duplicates(df):
    lines, problems = [], []
    n = len(df)
    key = "contract_transaction_unique_key"
    if key in df:
        dup_extra = int(df[key].dropna().duplicated().sum())
        lines.append(f"- Extra rows sharing a `{key}` (should be 0): **{fmt_int(dup_extra)}**")
        if dup_extra:
            problems.append(f"Repeated transaction keys: {fmt_int(dup_extra)} extra rows.")
    full_dupes = int(df.duplicated().sum())
    lines.append(f"- Rows that are exact copies of another row (in the checked fields): **{fmt_int(full_dupes)}**")
    if full_dupes:
        problems.append(f"Rows that are exact copies of another row: {fmt_int(full_dupes)}.")

    award = "contract_award_unique_key"
    if award in df:
        per_award = df[award].dropna().value_counts()
        lines.append(f"- Distinct contracts (`{award}`): **{fmt_int(per_award.shape[0])}** across {fmt_int(n)} transactions")
        if len(per_award):
            lines.append(
                f"- Transactions per contract: median {per_award.median():.0f}, "
                f"maximum {fmt_int(per_award.max())}"
            )
        mod = "modification_number"
        if mod in df:
            is_base = df[mod].fillna("").str.fullmatch(r"0+")
            with_base = df.loc[is_base, award].dropna().nunique()
            share = pct(with_base, per_award.shape[0])
            lines.append(
                f"- Contracts whose original award (modification number 0) is in this data: "
                f"**{fmt_int(with_base)}** ({fmt_pct(share)})"
            )
            if with_base < per_award.shape[0]:
                problems.append(
                    f"Only {fmt_pct(share)} of contracts have their original award in fiscal years 2017 to 2019. "
                    "Cost growth needs the award-time value, so the other contracts cannot be measured from this data alone."
                )
    return "\n".join(lines), problems


def fiscal_year(ts):
    return ts.dt.year + (ts.dt.month >= 10).astype("Int64")


def check_dates(df):
    rows, problems, parsed = [], [], {}
    for c in DATE_COLUMNS:
        if c not in df:
            continue
        raw = df[c]
        ts = pd.to_datetime(raw.str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
        parsed[c] = ts
        present = int(raw.notna().sum())
        bad = int((raw.notna() & ts.isna()).sum())
        too_early = int((ts < EARLIEST_DATE).sum())
        too_late = int((ts > LATEST_DATE).sum())
        lo = ts.min().date() if ts.notna().any() else "-"
        hi = ts.max().date() if ts.notna().any() else "-"
        rows.append([f"`{c}`", fmt_int(present), fmt_int(bad), fmt_int(too_early), fmt_int(too_late), lo, hi])
        if bad:
            problems.append(f"`{c}` has {fmt_int(bad)} values that are not valid dates.")
        if too_early or too_late:
            problems.append(f"`{c}` has {fmt_int(too_early + too_late)} dates before 1980 or after 2100.")
    table = md_table(
        ["Field", "Values present", "Not a valid date", "Before 1980", "After 2100", "Earliest", "Latest"], rows
    )

    extra = []
    start, end = "period_of_performance_start_date", "period_of_performance_current_end_date"
    if start in parsed and end in parsed:
        backwards = int((parsed[end] < parsed[start]).sum())
        extra.append(f"- Contracts where the current end date is before the start date: **{fmt_int(backwards)}**")
        if backwards:
            problems.append(f"{fmt_int(backwards)} rows end before they start.")
    if "action_date" in parsed and YEAR_COLUMN in df:
        fy = fiscal_year(parsed["action_date"])
        stated = pd.to_numeric(df[YEAR_COLUMN], errors="coerce").astype("Int64")
        both = fy.notna() & stated.notna()
        mismatch = int((fy[both] != stated[both]).sum())
        extra.append(
            f"- Rows where `action_date` does not fall in the stated fiscal year: **{fmt_int(mismatch)}**"
        )
        if mismatch:
            problems.append(f"{fmt_int(mismatch)} rows have an action date outside their fiscal year.")
    return table + ("\n\n" + "\n".join(extra) if extra else ""), problems


def check_dollars(df):
    rows, problems = [], []
    for c in DOLLAR_COLUMNS:
        if c not in df:
            continue
        raw = df[c]
        num = pd.to_numeric(raw, errors="coerce")
        present = int(raw.notna().sum())
        bad = int((raw.notna() & num.isna()).sum())
        neg = int((num < 0).sum())
        zero = int((num == 0).sum())
        large = int((num.abs() > LARGE_DOLLAR).sum())
        median = f"${num.median():,.0f}" if num.notna().any() else "-"
        rows.append([f"`{c}`", fmt_int(present), fmt_int(bad), fmt_int(neg), fmt_int(zero), fmt_int(large), median])
        if bad:
            problems.append(f"`{c}` has {fmt_int(bad)} values that are not numbers.")
        if large:
            problems.append(f"`{c}` has {fmt_int(large)} values over one billion dollars; these should be checked by hand.")
    table = md_table(
        ["Field", "Values present", "Not a number", "Negative", "Zero", "Over $1 billion", "Median"], rows
    )
    note = (
        "Note: negative values are normal for some modifications (for example, money taken back "
        "or options removed), so they are not errors by themselves. They matter when measuring "
        "growth, because a contract can shrink as well as grow."
    )
    return table + "\n\n" + note, problems


def check_categories(df):
    rows, problems = [], []
    for c in ["type_of_contract_pricing", "award_type", "extent_competed", "awarding_sub_agency_name"]:
        if c not in df:
            continue
        counts = df[c].value_counts()
        top = ", ".join(f"{k} ({fmt_int(v)})" for k, v in counts.head(3).items()) or "-"
        rows.append([f"`{c}`", fmt_int(counts.shape[0]), top])
    lines = [md_table(["Field", "Distinct values", "Most common values"], rows)]

    if "naics_code" in df:
        codes = df["naics_code"].dropna().str.replace(r"\.0$", "", regex=True)
        bad = int((~codes.str.fullmatch(r"\d{6}")).sum())
        lines.append(f"\n- Industry codes (`naics_code`) that are not 6 digits: **{fmt_int(bad)}**")
        lines.append(f"- Distinct industry codes: **{fmt_int(codes.nunique())}**")
        if bad:
            problems.append(f"{fmt_int(bad)} industry codes are not in the 6-digit format.")
    if "number_of_offers_received" in df:
        offers = pd.to_numeric(df["number_of_offers_received"], errors="coerce")
        bad = int((df["number_of_offers_received"].notna() & offers.isna()).sum())
        lines.append(f"- `number_of_offers_received` values that are not numbers: **{fmt_int(bad)}**")
    return "\n".join(lines), problems


def build_report(df, present, absent, sections):
    n = len(df)
    missing_results = sections["missing_results"]
    trusted = [c for c, s in missing_results.items() if verdict(s) == "Trustworthy"]
    care = [c for c, s in missing_results.items() if verdict(s) == "Use with care"]
    untrusted = [c for c, s in missing_results.items() if verdict(s) == "Not trustworthy"]
    problems = sections["problems"]

    def names(cols):
        return ", ".join(f"`{c}`" for c in cols) if cols else "none"

    parts = [
        "# Data Quality Report",
        "",
        f"**User story:** SCRUM-13  ",
        f"**Data:** Department of Veterans Affairs contract transactions, fiscal years 2017 to 2019 "
        f"(table `{TABLE}`, {fmt_int(n)} rows)  ",
        f"**Generated:** {date.today().isoformat()} by `Data/data_quality_check.py`",
        "",
        "**Purpose:** show which contracts and fields are trustworthy, so later analysis only uses data we can rely on.",
        "",
        "## Summary",
        "",
        f"- **Trustworthy fields** (under 1% missing): {names(trusted)}",
        f"- **Use with care** (1% to 20% missing): {names(care)}",
        f"- **Not trustworthy** (over 20% missing): {names(untrusted)}",
        "",
        "### Issues found",
        "",
    ]
    parts += [f"- {p}" for p in problems] if problems else ["- No issues found."]
    parts += [
        "",
        "## 1. Row counts",
        "",
        sections["rows"],
        "",
        "## 2. Missing values",
        "",
        "A field is **Trustworthy** if under 1% of rows are missing, **Use with care** if 1% to 20% "
        "are missing, and **Not trustworthy** if more than 20% are missing.",
        "",
        sections["missing"],
        "",
        "## 3. Duplicates and contract coverage",
        "",
        sections["duplicates"],
        "",
        "## 4. Dates",
        "",
        sections["dates"],
        "",
        "## 5. Dollar amounts",
        "",
        sections["dollars"],
        "",
        "## 6. Categories",
        "",
        sections["categories"],
        "",
    ]
    if absent:
        parts += [
            "## Fields not found",
            "",
            "These fields were expected but are not in the table, so they were not checked: "
            + names(absent),
            "",
        ]
    parts += [
        "## How to re-run",
        "",
        "```bash",
        "python3 Data/data_quality_check.py",
        "```",
        "",
    ]
    return "\n".join(parts)


def main():
    engine = create_engine(DATABASE_URL)
    print(f"Reading {TABLE} ...")
    df, present, absent = load(engine)
    print(f"Loaded {len(df):,} rows and {len(present)} fields.")

    problems = []
    rows_md, p = check_row_counts(df); problems += p
    missing_md, missing_results = check_missing(df, present)
    dup_md, p = check_duplicates(df); problems += p
    dates_md, p = check_dates(df); problems += p
    dollars_md, p = check_dollars(df); problems += p
    cat_md, p = check_categories(df); problems += p

    report = build_report(
        df,
        present,
        absent,
        {
            "rows": rows_md,
            "missing": missing_md,
            "missing_results": missing_results,
            "duplicates": dup_md,
            "dates": dates_md,
            "dollars": dollars_md,
            "categories": cat_md,
            "problems": problems,
        },
    )
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"Report written to {os.path.normpath(REPORT_PATH)}")
    print(f"{len(problems)} issues found.")


if __name__ == "__main__":
    main()
