-- ============================================================================
-- 99_verify.sql
--
-- Checks that the scripts in this folder produce the tables the results were
-- computed from. Run it after 01 to 05.
--
-- Every number below should be as stated. Anything else means a script and
-- the database have drifted apart.
-- ============================================================================

-- 1. Row counts
SELECT 'contract_summary' AS table_name, COUNT(*) AS rows, 359060 AS expected
  FROM contract_summary
UNION ALL SELECT 'model_data',  COUNT(*), 304789 FROM model_data
UNION ALL SELECT 'growth_12mo', COUNT(*), 359060 FROM growth_12mo
UNION ALL SELECT 'model_final', COUNT(*), 242775 FROM model_final;


-- 2. Every dollar lands in exactly one category.
--    Expected: 0
SELECT COUNT(*) AS contracts_that_do_not_reconcile
FROM contract_summary
WHERE ABS(final_total - (original_award + unplanned_growth
                         + planned_growth + reductions + other_actions)) > 0.01;


-- 3. The original award is always the earliest action.
--    Expected: 0
SELECT COUNT(*) AS base_rows_that_are_not_earliest
FROM (
  SELECT contract_award_unique_key,
         MIN(action_date) FILTER (WHERE action_type_code IS NULL) AS base_date,
         MIN(action_date)                                         AS first_date
  FROM va_contracts_raw
  GROUP BY 1
) t
WHERE base_date IS NOT NULL AND base_date > first_date;


-- 4. The training and test halves are the two complete federal budget years.
--    Expected: train 2016-10-01 to 2017-09-30, test 2017-10-01 to 2018-09-30
SELECT split, COUNT(*) AS contracts,
       MIN(award_date) AS earliest, MAX(award_date) AS latest
FROM model_final
GROUP BY split ORDER BY split;


-- 5. No award-time feature is missing for a large share of contracts.
SELECT
  COUNT(*)                                                  AS contracts,
  COUNT(*) FILTER (WHERE planned_duration_days IS NULL)     AS missing_duration,
  COUNT(*) FILTER (WHERE naics_code IS NULL)                AS missing_naics,
  COUNT(*) FILTER (WHERE extent_competed IS NULL)           AS missing_competed
FROM model_final;
