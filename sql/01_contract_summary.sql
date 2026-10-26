-- ============================================================================
-- 01_contract_summary.sql
--
-- What this builds: one row per contract, from many rows per contract.
--
-- The raw data has one row per ACTION. A single contract appears as an
-- original award plus every later modification to it. Nothing in the source
-- gives you the contract as a whole, so it has to be rebuilt.
--
-- Identifying the original award:
--   The row where action_type_code is null is the original award. This was
--   checked across all 359,060 contracts: no row is marked as a base award
--   while not also being the earliest row, so the marker is reliable.
--
-- Grouping the 23 action types by what they mean:
--
--   unplanned growth   B  supplemental agreement, work within scope
--                      D  change order
--                      A  additional work, new agreement
--                      L  definitize change order
--
--   planned growth     G  exercise an option
--                      C  funding only action
--                      H  definitize letter contract
--
--   reductions         E  terminate for default
--                      F  terminate for convenience
--                      K  close out
--                      N  legal contract cancellation
--                      X  other termination
--
--   other actions      everything else (administrative, novation, and so on)
--
--   The split matters. An option agreed on the day of award and exercised
--   later is planned spending, not a surprise. Only unplanned growth is
--   treated as the thing worth predicting.
--
-- Run first. Requires: va_contracts_raw (see Data/load_data.sh)
-- ============================================================================

DROP TABLE IF EXISTS contract_summary;

CREATE TABLE contract_summary AS
SELECT
  contract_award_unique_key,

  MIN(action_date)                       AS first_action_date,
  MAX(action_date)                       AS last_action_date,
  COUNT(*)                               AS number_of_actions,

  COALESCE(SUM(federal_action_obligation)
    FILTER (WHERE action_type_code IS NULL), 0)                       AS original_award,

  COALESCE(SUM(federal_action_obligation)
    FILTER (WHERE action_type_code IN ('B','D','A','L')), 0)          AS unplanned_growth,

  COALESCE(SUM(federal_action_obligation)
    FILTER (WHERE action_type_code IN ('G','C','H')), 0)              AS planned_growth,

  COALESCE(SUM(federal_action_obligation)
    FILTER (WHERE action_type_code IN ('E','F','K','N','X')), 0)      AS reductions,

  COALESCE(SUM(federal_action_obligation)
    FILTER (WHERE action_type_code IS NOT NULL
              AND action_type_code NOT IN
                  ('B','D','A','L','G','C','H','E','F','K','N','X')), 0) AS other_actions,

  SUM(federal_action_obligation)         AS final_total,

  COUNT(*) FILTER (WHERE action_type_code IS NULL) > 0 AS has_original_award,

  -- Attributes. The same value repeats on every row of a contract, so MAX()
  -- just picks it up.
  MAX(award_or_idv_flag)                 AS award_or_idv_flag,
  MAX(awarding_sub_agency_name)          AS awarding_sub_agency,
  MAX(recipient_name)                    AS recipient_name,
  MAX(naics_code)                        AS naics_code,
  MAX(product_or_service_code)           AS product_service_code,
  MAX(type_of_contract_pricing)          AS contract_pricing_type,
  MAX(extent_competed)                   AS extent_competed,
  MAX(usaspending_permalink)             AS permalink

FROM va_contracts_raw
GROUP BY contract_award_unique_key;

CREATE INDEX ON contract_summary (contract_award_unique_key);

-- Expected: 359,060 rows.
