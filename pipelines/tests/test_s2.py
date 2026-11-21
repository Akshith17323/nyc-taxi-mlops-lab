"""Tests for S2 definitions: feature_contract check, training_set, trained_model, eval_report, beats_champion, challenger."""

import dagster as dg
import mlflow.exceptions
import pytest
from fakes import FakeRedshift, LocalArtifacts, unloading_redshift

from labpipes.contracts import mlflow_contract
from labpipes.defs.feature_check import feature_contract
from labpipes.defs.training import beats_champion, challenger, eval_report, trained_model, training_set
from labpipes.resources import MlflowTracking


def check_context(partition_key: str):
    ctx = dg.build_asset_check_context()
    ctx.op_execution_context._partition_key = partition_key
    return ctx


class ContractRedshift(FakeRedshift):
    forbidden_col: str | None = None

    def query(self, sql: str) -> list[dict]:
        if "from information_schema.columns" in sql:
            cols = ["trip_month", "pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow", "duration_min"]
            if self.forbidden_col:
                cols.append(self.forbidden_col)
            return [{"column_name": c} for c in cols]
        if "from staging.trip_features" in sql:
            return [{"rows": 100, "bad_zones": 0, "bad_time": 0, "bad_duration": 0}]
        return super().query(sql)


def test_feature_contract_passes():
    rs = ContractRedshift(cluster_id="lab", database="lab", db_user="labadmin")
    ctx = check_context("2024-01")
    res = feature_contract(ctx, redshift=rs)
    assert res.passed
    assert res.severity == dg.AssetCheckSeverity.ERROR


def test_feature_contract_fails_on_forbidden_column():
    rs = ContractRedshift(cluster_id="lab", database="lab", db_user="labadmin", forbidden_col="fare_amount")
    ctx = check_context("2024-01")
    res = feature_contract(ctx, redshift=rs)
    assert not res.passed
    assert "fare_amount" in res.description


def test_training_pipeline_end_to_end(tmp_path):
    # Setup local artifacts and fake unloading redshift
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True)
    artifacts = LocalArtifacts(root=str(tmp_path), bucket="artifacts")
    rs = unloading_redshift(root=str(tmp_path))

    # Setup local MLflow
    mlflow_db = tmp_path / "mlflow.db"
    tracking_uri = f"sqlite:///{mlflow_db}"
    tracking = MlflowTracking(tracking_uri=tracking_uri)

    # 1. training_set
    res_ts = training_set(redshift=rs, artifacts=artifacts)
    assert res_ts.metadata["training_window"].value == "2024-01..2024-03"

    # 2. trained_model
    res_tm = trained_model(artifacts=artifacts, tracking=tracking)
    version = res_tm.metadata["model_version"].value
    assert int(version) >= 1

    # 3. eval_report
    res_er = eval_report(artifacts=artifacts, tracking=tracking, redshift=rs)
    assert res_er.metadata["mae_min"].value < res_er.metadata["champion_mae_min"].value
    assert res_er.metadata["p95_latency_ms"].value < 10.0

    # Verify version tags on MLflow model
    client = tracking.client()
    contract = mlflow_contract()
    reg_name = contract["registered_model"]
    mv = client.get_model_version(reg_name, version)
    for tag in contract["version_tags"]:
        assert tag in mv.tags, f"Missing tag {tag} on model version"

    # 4. beats_champion check
    res_bc = beats_champion(tracking=tracking)
    assert res_bc.passed

    # 5. challenger asset
    res_ch = challenger(tracking=tracking)
    assert res_ch.metadata["challenger_version"].value == version

    # Verify alias
    ch_mv = client.get_model_version_by_alias(reg_name, "challenger")
    assert str(ch_mv.version) == str(version)

    # Ensure champion alias was never set
    with pytest.raises(mlflow.exceptions.MlflowException):
        client.get_model_version_by_alias(reg_name, "champion")
