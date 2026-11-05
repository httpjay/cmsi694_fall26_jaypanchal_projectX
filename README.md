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

Measured on a held-out year the model never saw during training. Training is
not deterministic, so the two learned models are given as the range across five
seeds rather than as a single number — see **Reproducibility** below.

| Ranking method | Growth captured in the top 200 |
|---|---|
| Random | about $3M |
| Biggest award first (baseline) | $56.2M — no randomness, always the same |
| Model A, dollars predicted directly | $64.7M to $71.9M |
| **Model C, two-part — used for the watchlist** | **$65.9M to $77.0M** |
| Perfect knowledge (ceiling) | $225.5M |

So between 17% and 37% better than the baseline depending on the training run,
and 29% to 34% of what perfect foresight would capture. The advantage holds at
watchlist sizes of 100, 200 and 500.

Model A and Model C overlap, so no single run can say which ranks better. The
watchlist uses Model C because its dollar figures are defensible (see
**Calibration** below), not because it ranks higher.

**Two separate checks on whether that advantage is real.** They ask different
questions and give different answers, and both belong in any honest summary.

*Changing how the model is trained.* Across five seeds, every run of both
models beat the baseline's $56.2M; the worst was $64.7M. The advantage does not
depend on a lucky training run.

*Changing which year is tested.* Resampling the test year 400 times, Model C
captured a typical $66M against the baseline's $53M and beat it in roughly 9
out of every 10 resampled years. But the 95% range for the difference runs from
about −$6M to +$31M. It crosses zero, so the improvement is **not** established
at that level: in roughly one plausible year in ten, simply checking the
biggest contracts would have done as well or better. (These figures shift by a
million or two between runs, for the reason below.)

So: robust to how the model is trained, probable but unproven against the luck
of which contracts fell in the test year. The second is the weaker claim and is
the one to quote.

**Reproducibility.** Running this code twice does not give the same answer.
Model C has come out anywhere between $65.9M and $77.0M on the same data.

Two causes were investigated. The first was a real bug: the modelling table was
read with a plain `SELECT`, which guarantees no row order, and XGBoost's
`subsample` picks rows by position. The query now orders by contract key. That
was worth fixing, but it did not stop the variation.

The remaining cause is XGBoost itself. `tree_method="hist"` splits work across
threads and the order they finish in is not fixed, so identical code on
identical data builds slightly different trees. It would barely matter for a
stable measure. It matters here because the top 200 is decided by a handful of
enormous contracts, and a small change in the model reshuffles which of them
make the cut.

Forcing a single thread would make runs repeatable at a large cost in speed.
The choice made instead was to measure the variation and report it, which is
why every figure above is a range. A single number from this pipeline should
not be quoted, including by its author.

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

**Calibration, not just ranking.** A first model predicted growth in dollars
directly, using squared-error loss. It ranked contracts usefully but its
amounts were not believable: it predicted $641M of growth against $277M that
actually occurred, its largest single prediction was $150.6M against a real
maximum of $23.0M, and on 503 contracts it predicted more growth than the
contract was worth in the first place. Fitting the average of a target where
96% of values are zero and a few are enormous pulls every prediction upward.

The watchlist therefore uses a two-part model. One model gives the chance a
contract grows at all; a second, trained only on contracts that did grow,
gives the size on a log scale. Expected growth is the product of the two.
Because the exponential of an average logarithm understates the mean, Duan's
smearing estimate is applied, using the spread of the training residuals; the
correction factor was about 2.0 across every seed tried (2.002 to 2.015),
so the uncorrected figures would have been roughly half what they should be.

The two-part model is far better calibrated. On a representative run it
predicted $349M of growth against $277M that actually occurred, where the
direct model predicted $677M; its largest single prediction was $37M against a
real maximum of $23M, where the direct model's was $151M; and it predicted
more growth than the contract's own value on 99 contracts rather than 477.
It is still not well calibrated in absolute terms — it overstates total growth
by about a third, and those 99 contracts still receive a prediction larger than
the contract itself. These counts move a little between runs.

**Why each contract is on the list.** A ranking nobody can question is a
ranking nobody will act on, so every contract carries the three facts that
moved its score the most. The figures come from TreeSHAP, built into XGBoost,
which reports how much each feature added to or removed from the prediction;
the contributions plus a bias term reconstruct the prediction exactly.

The score is a product — chance of growing times size if it grows — so the two
models' contributions cannot simply be added. Logarithms turn the product into
a sum, which makes them addable: model C already predicts in log dollars, and
the classifier works in log-odds, which for a 4% base rate is within a few per
cent of log-chance. The approximation is close and is the right shape, since a
feature that makes growth both more likely and larger appears as one effect
rather than two half-effects.

Each factor is reported as its share of the total movement rather than as a
multiplier. A multiplier is the natural reading of a log contribution, but
contract size dominates so heavily that it emerges as "raised the estimate
2,900 times" — true, and useless to a reader.

On ranking the two are indistinguishable. Across five seeds their ranges
overlap, so the watchlist uses Model C for the calibration reasons above and
because it is the steadier of the two, not because it ranks better.

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
- The model reaches about a third of what a perfect ranking would capture.
  Most available
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