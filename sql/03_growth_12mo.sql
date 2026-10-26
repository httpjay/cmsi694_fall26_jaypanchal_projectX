-- ============================================================================
-- 03_growth_12mo.sql
--
-- What this builds: the prediction target.
--
-- For every contract, how many dollars of UNPLANNED growth were added in the
-- first 12 months after the award was signed.
--
-- Why a fixed 12-month window:
--   The data covers a closed period. A contract awarded in October 2016 has
--   almost three years of visible history. One awarded in August 2018 has a
--   few weeks. Without a window, older contracts look riskier purely because
--   we can see more of them. Counting only the first 12 months of every
--   contract makes them comparable.
--
-- Which action types count as unplanned growth:
--   B  supplemental agreement for work within scope
--   D  change order
--   A  additional work (new agreement, justification required)
--   L  definitize letter contract
--
--   Exercised options (G) and funding-only actions (C) are deliberately left
--   out. An option agreed on the day of award and exercised later is planned,
--   not a surprise.
--
-- Run after: 01_contract_summary.sql
-- ============================================================================

DROP TABLE IF EXISTS growth_12mo;

CREATE TABLE growth_12mo AS
WITH first_dates AS (
  -- The award date is the earliest action on the contract.
  SELECT contract_award_unique_key,
         MIN(action_date::date) AS award_date
  FROM va_contracts_raw
  GROUP BY contract_award_unique_key
)
SELECT
  r.contract_award_unique_key,
  f.award_date,
  COALESCE(SUM(r.federal_action_obligation) FILTER (
    WHERE r.action_type_code IN ('B','D','A','L')
      AND r.action_date::date <= f.award_date + INTERVAL '12 months'
  ), 0) AS growth_12mo
FROM va_contracts_raw r
JOIN first_dates f USING (contract_award_unique_key)
GROUP BY r.contract_award_unique_key, f.award_date;

CREATE INDEX ON growth_12mo (contract_award_unique_key);
