"""S2: the feature_contract check on trip_features.

contracts/features.yaml lists the model's inputs, label and the post-trip columns that must never be
inputs; contracts/mlflow.yaml says this check blocks.
"""

import dagster as dg

from ..contracts import features_contract
from ..partitions import trip_months
from ..resources import RedshiftData
from .features import trip_features


@dg.asset_check(
    asset=trip_features,
    partitions_def=trip_months,
    blocking=True,
    description="Validate staging.trip_features against contracts/features.yaml for forbidden columns and value ranges.",
)
def feature_contract(
    context: dg.AssetCheckExecutionContext, redshift: RedshiftData
) -> dg.AssetCheckResult:
    month = context.partition_key
    contract = features_contract()
    forbidden = set(contract.get("forbidden", []))

    # Inspect column names in staging.trip_features
    cols_query = (
        "select column_name from information_schema.columns "
        "where table_schema = 'staging' and table_name = 'trip_features'"
    )
    cols = {r["column_name"].lower() for r in redshift.query(cols_query)}

    leaked = forbidden.intersection(cols)
    if leaked:
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            description=f"Forbidden target-leaking columns present: {', '.join(sorted(leaked))}",
            metadata={"leaked_columns": dg.MetadataValue.json(list(leaked))},
        )

    # Validate value ranges on data rows for this month
    stats = redshift.query(
        f"select count(*) as rows, "
        f"count(case when pickup_zone_id not between 1 and 263 or dropoff_zone_id not between 1 and 263 then 1 end) as bad_zones, "
        f"count(case when pickup_hour not between 0 and 23 or pickup_dow not between 0 and 6 then 1 end) as bad_time, "
        f"count(case when duration_min <= 0 or duration_min > 180 then 1 end) as bad_duration "
        f"from staging.trip_features where trip_month = '{month}'"
    )[0]

    rows = int(stats.get("rows") or 0)
    bad_zones = int(stats.get("bad_zones") or 0)
    bad_time = int(stats.get("bad_time") or 0)
    bad_duration = int(stats.get("bad_duration") or 0)

    total_bad = bad_zones + bad_time + bad_duration
    if total_bad > 0:
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            description=f"Contract violation: {bad_zones} bad zones, {bad_time} bad hours/dows, {bad_duration} bad durations out of {rows} rows",
            metadata={
                "rows": dg.MetadataValue.int(rows),
                "bad_zones": dg.MetadataValue.int(bad_zones),
                "bad_time": dg.MetadataValue.int(bad_time),
                "bad_duration": dg.MetadataValue.int(bad_duration),
            },
        )

    return dg.AssetCheckResult(
        passed=True,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"feature_contract passed: {rows} rows verified without forbidden columns or out-of-range values",
        metadata={"rows": dg.MetadataValue.int(rows)},
    )
