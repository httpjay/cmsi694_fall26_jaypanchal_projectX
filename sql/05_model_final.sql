-- ============================================================================
-- 05_model_final.sql
--
-- What this builds: the table the model trains on. One row per contract,
-- features on the left, targets on the right, and a train/test marker.
--
-- The train/test split is by award date, not random:
--   train  contracts awarded 1 October 2016 to 30 September 2017
--   test   contracts awarded 1 October 2017 to 30 September 2018
--
-- Why by date rather than at random:
--   A random split lets the model learn from contracts awarded after the ones
--   it is tested on. That is not how the tool would be used. Splitting by date
--   asks the honest question: trained on last year, does it help this year?
--
-- Why these two years specifically:
--   Both are complete federal budget years (October to September). Award month
--   matters a lot -- October grows at 5.1%, July and August at 2.8% -- so two
--   complete years have the same month mix and are directly comparable.
--
-- The cut-off:
--   Contracts awarded after 30 September 2018 are dropped. The data ends in
--   fiscal year 2019, so they cannot have a full 12 months of visible history.
--
-- Run after: 04_award_attrs.sql
-- ============================================================================

DROP TABLE IF EXISTS model_final;

CREATE TABLE model_final AS
SELECT
  m.contract_award_unique_key,
  g.award_date,

  -- features: all known on the day of award
  m.award_month,
  m.original_award,
  m.log_award,
  m.naics_code,
  m.product_service_code,
  m.contract_pricing_type,
  m.extent_competed,
  a.under_umbrella,
  (a.pop_potential_end - a.pop_start) AS planned_duration_days,

  -- targets
  g.growth_12mo AS target_dollars,
  CASE WHEN g.growth_12mo > 0 THEN 1 ELSE 0 END AS target_grew,

  -- which half of the experiment this contract belongs to
  CASE WHEN g.award_date <= DATE '2017-09-30' THEN 'train' ELSE 'test' END AS split

FROM model_data m
JOIN growth_12mo g USING (contract_award_unique_key)
LEFT JOIN award_attrs a USING (contract_award_unique_key)
WHERE g.award_date <= DATE '2018-09-30';

CREATE INDEX ON model_final (contract_award_unique_key);
CREATE INDEX ON model_final (split);
