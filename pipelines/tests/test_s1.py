"""Tests for S1 definitions: schema_contract, raw_trips, stg_trips_quality, and trip_files_sensor."""

import dagster as dg
from fakes import fake_bucket, fake_redshift

from labpipes.contracts import trips_schema
from labpipes.defs.quality import stg_trips_quality
from labpipes.defs.raw_trips import raw_trips
from labpipes.defs.schema_check import schema_contract
from labpipes.defs.sensor import trip_files_sensor


def check_context(partition_key: str):
    ctx = dg.build_asset_check_context()
    ctx.op_execution_context._partition_key = partition_key
    return ctx


def test_schema_contract_passes_on_contract_schema():
    bucket = fake_bucket({"2024-01": ("etag1", trips_schema())})
    ctx = check_context("2024-01")
    res = schema_contract(ctx, data_bucket=bucket)
    assert res.passed
    assert res.severity == dg.AssetCheckSeverity.ERROR


def test_schema_contract_fails_on_drifted_columns():
    cols = trips_schema()[:-1]  # drop last column
    bucket = fake_bucket({"2024-01": ("etag1", cols)})
    ctx = check_context("2024-01")
    res = schema_contract(ctx, data_bucket=bucket)
    assert not res.passed
    assert "mismatch" in res.description.lower()


def test_raw_trips_issues_idempotent_copy_and_delete():
    rs = fake_redshift()
    bucket = fake_bucket({"2024-01": ("etag1", trips_schema())})
    ctx = dg.build_asset_context(partition_key="2024-01")
    res = raw_trips(ctx, redshift=rs, data_bucket=bucket)
    assert res.metadata["rows"].value == 3
    assert res.metadata["source_file"] == "yellow_tripdata_2024-01.parquet"


def test_quality_check_queries_stg_trips():
    rs = fake_redshift()
    ctx = check_context("2024-01")
    res = stg_trips_quality(ctx, redshift=rs)
    assert res.passed
    assert res.severity == dg.AssetCheckSeverity.WARN


def test_sensor_emits_partitions_and_skips_when_clean():
    bucket = fake_bucket({
        "2024-01": ("etag1", trips_schema()),
        "2024-02": ("etag2", trips_schema()),
    })
    ctx = dg.build_sensor_context()
    res = trip_files_sensor(ctx, data_bucket=bucket)
    assert isinstance(res, dg.SensorResult)
    assert len(res.run_requests) == 2
    assert len(res.dynamic_partitions_requests) == 1

    # Second evaluation with cursor: nothing new
    ctx2 = dg.build_sensor_context(cursor=res.cursor)
    res2 = trip_files_sensor(ctx2, data_bucket=bucket)
    assert isinstance(res2, dg.SkipReason)
