# Project X — Predicting Federal Contract Cost Growth

CMSI 694 Capstone · Jay Panchal · Loyola Marymount University

Federal contracts are awarded at one price and frequently cost more by the end.
The record of that growth is public, but there is no practical way for someone
with limited hours to work out which contracts deserve watching.

This project predicts how much a contract will grow using only information
available on the day it was awarded, and ranks contracts into a watchlist by
expected dollars of growth.

---

## Result

Measured on a held-out year the model never saw during training:

| Ranking method | Contracts that grew (of 200) | Growth captured |
|---|---|---|
| Random | 6 | $0.2M |
| Biggest award first (baseline) | 22 | $56.2M |
| **Model** | **50** | **$68.1M** |
| Perfect knowledge (ceiling) | 200 | $225.5M |

A 21% improvement over the baseline. The improvement holds at watchlist sizes
of 100, 200 and 500.

---

## Getting the data

The raw data is not stored in this repository because the files are too large.

1. Go to https://www.usaspending.gov/download_center/award_data_archive
2. Select agency: Department of Veterans Affairs
3. Select award type: Contracts
4. Select fiscal year: 2017, and download the Full file
5. Repeat for fiscal years 2018 and 2019
6. Unzip into `Data/`

Scope: 3 files, approximately 1 GB, 539,452 transaction rows.

---

## Running the pipeline

### 1. Load

```bash
bash load_data.sh          # creates and populates va_contracts_raw
```

Each row is one action on a contract. A contract appears as several rows: one
original award plus any later modifications.

### 2. Build the contract-level tables

Run in `psql` or pgAdmin, in order:

```sql
-- One row per contract, with growth split by action type
\i sql/01_contract_summary.sql

-- Growth counted over a fixed 12-month window after award
\i sql/02_growth_12mo.sql

-- Award-time attributes taken from the base award row only
\i sql/03_award_attrs.sql

-- Final modelling table with the train/test split
\i sql/04_model_final.sql
```

### 3. Train and score

```bash
python3 train_model.py
```

Trains on contracts awarded October 2016 to September 2017, scores contracts
awarded October 2017 to September 2018, and writes the ranked `watchlist` table.

### 4. Serve the watchlist

```bash
python3 -m uvicorn api.main:app
```

Open http://127.0.0.1:8000

---

## Architecture

Four components with different update cadences:

| Component | What it does | Runs |
|---|---|---|
| Ingestion | Downloads and loads published award files | Monthly, when new files are published |
| Reconstruction and scoring | Rebuilds contract histories and scores them | Batch, after each ingestion |
| Serving | Exposes the watchlist and contract detail | Continuously |
| Interface | Ranked list and per-contract explanation | In the browser |

---

## Method

**Reconstruction.** Contracts are grouped by `contract_award_unique_key`. The
original award is the row where `action_type_code` is null; everything else is a
modification. Across 359,060 contracts, zero rows are marked as a base award
while not being the earliest row, so this marker is reliable.

**What counts as growth.** The 23 action types are grouped by meaning.
Unplanned growth is supplemental agreements, change orders and additional work.
Exercised options and funding actions are counted separately as planned growth,
because an option agreed on the day of award is not a surprise. Every dollar
reconciles across the categories with zero mismatches.

**Fixed observation window.** The data covers a closed period, so a contract
awarded near the end has less visible history than one awarded at the start.
Growth is therefore counted only over the first 12 months after award, and
contracts awarded too late to have a full 12 months are excluded.

**No leakage.** Several columns look useful but contain post-award information.
`current_total_value_of_award` and its relatives are rewritten on every row to
show the contract's total as of the most recent modification, so a row from the
first month displays the final total. These are excluded. Award-time attributes
are read from the base award row only.

**Time-based holdout.** The split is by award date, not random — training on
fiscal year 2017 and testing on fiscal year 2018. Both halves are complete
federal budget years, so the month mix is identical between them.

**Measure.** Dollars of unplanned growth captured in the top 200 of the
watchlist. Accuracy is not used: under 4% of contracts grow, so a model
predicting "no growth" every time would be 96% accurate and useless.

---

## Findings

**Growth is rare but concentrated.** 3.9% of contracts grew for unplanned
reasons. In the test year, 200 contracts out of 109,216 hold $225.5M of the
$277.3M total.

**Percentage growth is a misleading ranking metric.** The five
highest-percentage contracts all began with very small initial obligations and
had the real money added later — incremental funding rather than cost overrun.
The watchlist ranks by dollars.

**Planned duration is the strongest predictor.** Contracts planned to run over
three years are 4% of the data and hold more than half the growth dollars.
Contracts under three months shrink overall.

**Restricted competition matters.** Contracts competed "full and open after
exclusion of sources" grew at 8.6% against 4.1% overall, and hold 35% of growth
dollars from under 7% of contracts.

**Award month predicts growth.** October, the start of the federal budget year,
is the highest at 5.1%; July and August are lowest at 2.8%.

---

## Limitations

- One agency, three fiscal years. Patterns may not transfer to other agencies.
- The 12-month window is a choice. Six or 24 months were not tested.
- Growth is predicted, not impropriety. Most contract growth is legitimate.
- The model reaches 30% of what a perfect ranking would capture. Most available
  growth is still missed.
- The interface shows what actually happened to each contract. A live tool would
  not have that column; it is shown here because this is an evaluation.

---

## Repository layout

```
Data/              raw award files (not committed)
sql/               table-building scripts, run in order
train_model.py     trains and scores, writes the watchlist table
api/main.py        serving layer
api/static/        interface
docs/              report and findings
```