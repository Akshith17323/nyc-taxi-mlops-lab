"""S1: data-quality checks on stg_trips (nulls, ranges, duplicates, row counts).

Decision 005: Staging tables capture uncleaned operational data. Row-level noise is surfaced
as non-blocking warnings (blocking=False), deferring filtering to downstream feature engineering.
"""

import dagster as dg

from ..partitions import trip_months
from ..resources import RedshiftData
from .staging import stg_trips


@dg.asset_check(
    asset=stg_trips,
    partitions_def=trip_months,
    blocking=False,
    description="Check trip durations, null passengers, and unknown zones on stg_trips.",
)
def stg_trips_quality(
    context: dg.AssetCheckExecutionContext, redshift: RedshiftData
) -> dg.AssetCheckResult:
    month = context.partition_key
    res = redshift.query(
        f"select count(*) as rows, "
        f"count(case when duration_min <= 0 then 1 end) as nonpositive_duration, "
        f"count(case when duration_min > 180 then 1 end) as over_3h, "
        f"count(case when passenger_count is null then 1 end) as null_passengers, "
        f"count(case when pickup_zone_id not between 1 and 263 or dropoff_zone_id not between 1 and 263 then 1 end) as unknown_zone "
        f"from staging.stg_trips where trip_month = '{month}'"
    )[0]

    rows = int(res.get("rows") or 0)
    nonpos = int(res.get("nonpositive_duration") or 0)
    over_3h = int(res.get("over_3h") or 0)
    null_pass = int(res.get("null_passengers") or 0)
    unk_zone = int(res.get("unknown_zone") or 0)

    nonpos_rate = (nonpos / rows) if rows > 0 else 0.0
    passed = nonpos_rate < 0.01

    return dg.AssetCheckResult(
        passed=passed,
        severity=dg.AssetCheckSeverity.WARN,
        description=f"{nonpos} nonpositive durations ({nonpos_rate:.2%}), {unk_zone} unknown zone trips",
        metadata={
            "rows": dg.MetadataValue.int(rows),
            "nonpositive_duration": dg.MetadataValue.int(nonpos),
            "over_3h": dg.MetadataValue.int(over_3h),
            "null_passengers": dg.MetadataValue.int(null_pass),
            "unknown_zone": dg.MetadataValue.int(unk_zone),
        },
    )
