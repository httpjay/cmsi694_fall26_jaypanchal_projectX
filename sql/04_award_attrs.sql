-- ============================================================================
-- 04_award_attrs.sql
--
-- What this builds: the facts that were true on the day the contract was
-- signed, and nothing else.
--
-- Why this table exists:
--   Most columns in the raw data are rewritten on every later modification.
--   A row from month one will show the contract's total value as of the most
--   recent change, which is information from the future. Training on that
--   would produce a model that looks excellent and is useless.
--
--   The filter `action_type_code IS NULL` keeps only the original award row.
--   Everything in this table is therefore known at award time.
--
-- Columns:
--   under_umbrella      1 if the contract sits under a larger parent award
--   pop_start           planned start of the period of performance
--   pop_potential_end   planned end if every option is exercised
--
--   pop_potential_end minus pop_start gives the planned duration, which turned
--   out to be the strongest single predictor of growth.
--
-- Run after: 03_growth_12mo.sql
-- ============================================================================

DROP TABLE IF EXISTS award_attrs;

CREATE TABLE award_attrs AS
SELECT
  contract_award_unique_key,
  MAX(CASE WHEN NULLIF(parent_award_id_piid, '') IS NOT NULL THEN 1 ELSE 0 END) AS under_umbrella,
  MAX(NULLIF(period_of_performance_start_date, ''))::date           AS pop_start,
  MAX(NULLIF(period_of_performance_potential_end_date, ''))::date   AS pop_potential_end
FROM va_contracts_raw
WHERE action_type_code IS NULL   -- original award rows only
GROUP BY contract_award_unique_key;

CREATE INDEX ON award_attrs (contract_award_unique_key);
