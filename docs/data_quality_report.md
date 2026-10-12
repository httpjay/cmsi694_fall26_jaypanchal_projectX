# Data Quality Report

**User story:** SCRUM-13  
**Data:** Department of Veterans Affairs contract transactions, fiscal years 2017 to 2019 (table `va_contracts_raw`, 539,452 rows)  
**Generated:** 2026-10-11 by `Data/data_quality_check.py`

**Purpose:** show which contracts and fields are trustworthy, so later analysis only uses data we can rely on.

## Summary

- **Trustworthy fields** (under 1% missing): `contract_transaction_unique_key`, `contract_award_unique_key`, `award_id_piid`, `modification_number`, `action_date`, `period_of_performance_start_date`, `federal_action_obligation`, `base_and_all_options_value`, `naics_code`, `naics_description`, `product_or_service_code`, `type_of_contract_pricing`, `awarding_sub_agency_name`, `recipient_uei`, `recipient_name`, `action_date_fiscal_year`
- **Use with care** (1% to 20% missing): `period_of_performance_current_end_date`, `period_of_performance_potential_end_date`, `base_and_exercised_options_value`, `award_type`, `extent_competed`, `number_of_offers_received`, `recipient_duns`
- **Not trustworthy** (over 20% missing): `current_total_value_of_award`, `potential_total_value_of_award`

### Issues found

- Only 88.14% of contracts have their original award in fiscal years 2017 to 2019. Cost growth needs the award-time value, so the other contracts cannot be measured from this data alone.
- `period_of_performance_start_date` has 2 dates before 1980 or after 2100.
- `period_of_performance_current_end_date` has 1 dates before 1980 or after 2100.
- `period_of_performance_potential_end_date` has 7 dates before 1980 or after 2100.
- 21,185 rows end before they start.
- `federal_action_obligation` has 3 values over one billion dollars; these should be checked by hand.
- `base_and_exercised_options_value` has 4 values over one billion dollars; these should be checked by hand.
- `base_and_all_options_value` has 218 values over one billion dollars; these should be checked by hand.
- `current_total_value_of_award` has 201 values over one billion dollars; these should be checked by hand.
- `potential_total_value_of_award` has 3,431 values over one billion dollars; these should be checked by hand.

## 1. Row counts

| Fiscal year | Expected rows | Actual rows | Matches |
|---|---|---|---|
| 2017 | 220,729 | 220,729 | Yes |
| 2018 | 184,728 | 184,728 | Yes |
| 2019 | 133,995 | 133,995 | Yes |
| Other or missing | 0 | 0 | Yes |

## 2. Missing values

A field is **Trustworthy** if under 1% of rows are missing, **Use with care** if 1% to 20% are missing, and **Not trustworthy** if more than 20% are missing.

| Field | Missing rows | Missing share | Verdict |
|---|---|---|---|
| `contract_transaction_unique_key` | 0 | 0.00% | Trustworthy |
| `contract_award_unique_key` | 0 | 0.00% | Trustworthy |
| `award_id_piid` | 0 | 0.00% | Trustworthy |
| `modification_number` | 0 | 0.00% | Trustworthy |
| `action_date` | 0 | 0.00% | Trustworthy |
| `period_of_performance_start_date` | 0 | 0.00% | Trustworthy |
| `period_of_performance_current_end_date` | 45,874 | 8.50% | Use with care |
| `period_of_performance_potential_end_date` | 45,874 | 8.50% | Use with care |
| `federal_action_obligation` | 0 | 0.00% | Trustworthy |
| `base_and_exercised_options_value` | 45,874 | 8.50% | Use with care |
| `base_and_all_options_value` | 0 | 0.00% | Trustworthy |
| `current_total_value_of_award` | 165,668 | 30.71% | Not trustworthy |
| `potential_total_value_of_award` | 125,753 | 23.31% | Not trustworthy |
| `naics_code` | 12 | 0.00% | Trustworthy |
| `naics_description` | 12 | 0.00% | Trustworthy |
| `product_or_service_code` | 0 | 0.00% | Trustworthy |
| `type_of_contract_pricing` | 4 | 0.00% | Trustworthy |
| `award_type` | 45,874 | 8.50% | Use with care |
| `extent_competed` | 8,643 | 1.60% | Use with care |
| `number_of_offers_received` | 73,947 | 13.71% | Use with care |
| `awarding_sub_agency_name` | 0 | 0.00% | Trustworthy |
| `recipient_uei` | 0 | 0.00% | Trustworthy |
| `recipient_duns` | 51,562 | 9.56% | Use with care |
| `recipient_name` | 1 | 0.00% | Trustworthy |
| `action_date_fiscal_year` | 0 | 0.00% | Trustworthy |

## 3. Duplicates and contract coverage

- Extra rows sharing a `contract_transaction_unique_key` (should be 0): **0**
- Rows that are exact copies of another row (in the checked fields): **0**
- Distinct contracts (`contract_award_unique_key`): **359,060** across 539,452 transactions
- Transactions per contract: median 1, maximum 336
- Contracts whose original award (modification number 0) is in this data: **316,486** (88.14%)

## 4. Dates

| Field | Values present | Not a valid date | Before 1980 | After 2100 | Earliest | Latest |
|---|---|---|---|---|---|---|
| `action_date` | 539,452 | 0 | 0 | 0 | 2016-10-01 | 2019-09-30 |
| `period_of_performance_start_date` | 539,452 | 0 | 0 | 2 | 2007-10-01 | 3017-03-09 |
| `period_of_performance_current_end_date` | 493,578 | 0 | 0 | 1 | 2008-12-24 | 2103-08-11 |
| `period_of_performance_potential_end_date` | 493,578 | 0 | 0 | 7 | 2009-01-31 | 2121-11-30 |

- Contracts where the current end date is before the start date: **21,185**
- Rows where `action_date` does not fall in the stated fiscal year: **0**

## 5. Dollar amounts

| Field | Values present | Not a number | Negative | Zero | Over $1 billion | Median |
|---|---|---|---|---|---|---|
| `federal_action_obligation` | 539,452 | 0 | 71,168 | 75,682 | 3 | $8,842 |
| `base_and_exercised_options_value` | 493,578 | 0 | 69,954 | 30,772 | 4 | $10,802 |
| `base_and_all_options_value` | 539,452 | 0 | 70,416 | 88,885 | 218 | $8,200 |
| `current_total_value_of_award` | 373,784 | 0 | 0 | 10,495 | 201 | $27,764 |
| `potential_total_value_of_award` | 413,699 | 0 | 0 | 11,797 | 3,431 | $39,600 |

Note: negative values are normal for some modifications (for example, money taken back or options removed), so they are not errors by themselves. They matter when measuring growth, because a contract can shrink as well as grow.

## 6. Categories

| Field | Distinct values | Most common values |
|---|---|---|
| `type_of_contract_pricing` | 14 | FIRM FIXED PRICE (507,861), FIXED PRICE WITH ECONOMIC PRICE ADJUSTMENT (27,959), ORDER DEPENDENT (IDV ALLOWS PRICING ARRANGEMENT TO BE DETERMINED SEPARATELY FOR EACH ORDER) (991) |
| `award_type` | 4 | DELIVERY ORDER (252,276), PURCHASE ORDER (167,031), DEFINITIVE CONTRACT (49,379) |
| `extent_competed` | 9 | FULL AND OPEN COMPETITION (193,235), NOT COMPETED (127,199), COMPETED UNDER SAP (67,535) |
| `awarding_sub_agency_name` | 1 | Department of Veterans Affairs (539,452) |

- Industry codes (`naics_code`) that are not 6 digits: **0**
- Distinct industry codes: **804**
- `number_of_offers_received` values that are not numbers: **0**

## How to re-run

```bash
python3 Data/data_quality_check.py
```
