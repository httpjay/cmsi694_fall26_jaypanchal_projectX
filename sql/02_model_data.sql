-- ============================================================================
-- 02_model_data.sql
--
-- What this builds: the contracts that are actually worth modelling, with
-- their award-time features and three different versions of the target.
--
-- Three filters, and the reason for each:
--
--   has_original_award
--     The data covers fiscal years 2017 to 2019. A contract first awarded in
--     2015 shows up here as modifications with no original award attached.
--     Its starting price is unknown, so growth cannot be measured against it.
--
--   award_or_idv_flag = 'AWARD'
--     An IDV (indefinite delivery vehicle) is an umbrella agreement, not a
--     contract for specific work. Orders placed against it are separate rows
--     and are kept. The umbrella itself is dropped.
--     Removes 15,072 of 359,060.
--
--   original_award > 1000
--     Contracts under one thousand dollars are micro-purchases. A $600
--     contract that later grows by $2,000 is a rounding difference, not a
--     cost overrun worth a reviewer's time, and the percentage growth on
--     such contracts is wild enough to distort any model trained on it.
--     Removes a further 1,345.
--
-- Three targets, because the right one was not obvious at the start:
--   target_dollars   dollars of unplanned growth      <- the one used
--   target_ratio     growth as a share of the award
--   target_grew      1 if it grew at all, else 0
--
--   target_ratio was tried and rejected. The highest-percentage contracts
--   all started with a tiny obligation and had the real money added later,
--   which is incremental funding, not overrun. Ranking by dollars finds the
--   contracts where the money actually is.
--
-- Run after: 01_contract_summary.sql
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Agency-agnostic. Run with no variables and this behaves exactly as before,
-- building the Veterans Affairs tables. To run the same pipeline for another
-- agency, pass a prefix and the raw table:
--
--   psql projectx -v px=usda_ -v src=usda_contracts_raw -f sql/<this file>
--
-- SCRUM-28 added this. Nothing about the method changes between agencies -
-- that is the point of the test.
-- ---------------------------------------------------------------------------
\if :{?px}
\else
  \set px ''
\endif
\if :{?src}
\else
  \set src 'va_contracts_raw'
\endif
\set t_summary :px 'contract_summary'
\set t_model   :px 'model_data'
\set t_growth  :px 'growth_12mo'
\set t_attrs   :px 'award_attrs'
\set t_final   :px 'model_final'

DROP TABLE IF EXISTS :t_model;

CREATE TABLE :t_model AS
SELECT
  contract_award_unique_key,

  first_action_date                                  AS award_date,
  EXTRACT(YEAR  FROM first_action_date::date)        AS award_year,
  EXTRACT(MONTH FROM first_action_date::date)        AS award_month,

  original_award,
  LN(original_award)                                 AS log_award,

  awarding_sub_agency,
  naics_code,
  product_service_code,
  contract_pricing_type,
  extent_competed,

  unplanned_growth                                   AS target_dollars,
  unplanned_growth / original_award                  AS target_ratio,
  CASE WHEN unplanned_growth > 0 THEN 1 ELSE 0 END   AS target_grew

FROM :t_summary
WHERE has_original_award
  AND award_or_idv_flag = 'AWARD'
  AND original_award > 1000;

CREATE INDEX ON :t_model (contract_award_unique_key);

-- Expected: 304,789 rows.
--   359,060  all contracts
--   -42,574  no original award inside the data window
--    -8,054  umbrella agreements (IDV)
--    -3,643  awards of one thousand dollars or less, including zero
--   =304,789
