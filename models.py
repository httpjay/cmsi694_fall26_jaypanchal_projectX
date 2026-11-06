"""
The model settings, in one place.

train_model.py and compare_agencies.py both build the same three models. If
each kept its own copy of the settings they could drift apart, and the
second-agency comparison would then be measuring a different model from the
one the watchlist uses - which would make the comparison worthless without
anyone noticing.

The feature list lives here for the same reason.
"""
import xgboost as xgb

# Everything here is known on the day of award.
NUMERIC_FEATURES = [
    "original_award",
    "log_award",
    "award_month",
    "under_umbrella",
    "planned_duration_days",
]

CATEGORICAL_FEATURES = [
    "naics_code",
    "product_service_code",
    "contract_pricing_type",
    "extent_competed",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def make_regressor(seed, max_depth=6):
    return xgb.XGBRegressor(
        n_estimators=400,
        max_depth=max_depth,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        enable_categorical=True,
        tree_method="hist",
        random_state=seed,
    )


def make_classifier(seed):
    return xgb.XGBClassifier(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        enable_categorical=True,
        tree_method="hist",
        eval_metric="logloss",
        random_state=seed,
    )
