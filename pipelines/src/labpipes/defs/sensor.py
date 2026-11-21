"""S1: the S3 sensor (and the ingest_month job it starts).

Watch trips/ in the data bucket (DataBucket.trip_files). When a month's file appears or changes,
add the month to trip_months partitions and request an execution from trip_files to zone_hour_stats.
"""

import json

import dagster as dg

from ..partitions import trip_months
from ..resources import DataBucket

ingest_month = dg.define_asset_job(
    "ingest_month",
    selection=dg.AssetSelection.assets("trip_files", "raw_trips", "stg_trips", "zone_hour_stats"),
    description="Ingest a monthly trip file from S3 through raw and staging tables to zone_hour_stats mart.",
)


@dg.sensor(name="trip_files_sensor", job=ingest_month, minimum_interval_seconds=60)
def trip_files_sensor(context: dg.SensorEvaluationContext, data_bucket: DataBucket):
    cursor_raw = context.cursor
    seen: dict[str, str] = {}
    if cursor_raw:
        try:
            loaded = json.loads(cursor_raw)
            if isinstance(loaded, dict):
                seen = loaded
            elif isinstance(loaded, list):
                seen = {m: "" for m in loaded}
        except Exception:
            seen = {}

    files = data_bucket.trip_files()
    if not files:
        return dg.SkipReason("no trip files found in data bucket")

    new_months = [f.month for f in files if f.month not in seen]
    changed_files = [f for f in files if f.month not in seen or seen[f.month] != f.etag]

    if not changed_files:
        return dg.SkipReason("all files up to date")

    run_requests = [
        dg.RunRequest(partition_key=f.month, run_key=f"{f.month}:{f.etag}")
        for f in changed_files
    ]
    dynamic_partitions_requests = (
        [trip_months.build_add_request(new_months)] if new_months else []
    )
    new_cursor = json.dumps({f.month: f.etag for f in files})

    return dg.SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=dynamic_partitions_requests,
        cursor=new_cursor,
    )
