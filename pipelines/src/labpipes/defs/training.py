"""S2: training_set, trained_model, eval_report, the challenger gate and the challenger asset.

- training_set: UNLOAD a window of staging.trip_features (and the holdout month) to the artifact bucket.
  The zone-pair distance lookup (contracts/features.yaml, est_distance_miles) comes from the window only.
- trained_model: fit tripmodel.LightGBMModel (the given v2), log it to MLflow as a pyfunc with
  tripmodel.model_signature() and the tripmodel package bundled, register a version of the model named
  in contracts/mlflow.yaml, and tag it as that contract says.
- eval_report: tripmodel.evaluate the new version and the champion (or the v1 baseline before there is
  one) on the same holdout; log the metrics.
- A blocking check that guards a `challenger` asset, which sets the alias. The pipeline never moves
  `champion`.
Decision points: what stays in the notebook; the promotion metric and margin; the training window.
"""

import os
import subprocess
from pathlib import Path

import dagster as dg
import mlflow
import mlflow.pyfunc

import tripmodel
from tripmodel import LABEL, REQUIRED

from ..contracts import mlflow_contract
from ..resources import ArtifactBucket, MlflowTracking, RedshiftData

TRAINING_WINDOW = ("2024-01", "2024-02", "2024-03")
HOLDOUT_MONTH = "2024-04"
WINDOW_STR = "2024-01..2024-03"

TRAIN_PREFIX = "datasets/train_2024-01_2024-03"
HOLDOUT_PREFIX = "datasets/holdout_2024-04"
DIST_PREFIX = "datasets/distances_2024-01_2024-03"


def _git_sha() -> str:
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


@dg.asset(
    deps=["trip_features"],
    group_name="model",
    kinds={"redshift", "s3"},
    pool="redshift",
    description="UNLOAD training window (2024-01..2024-03) and holdout (2024-04) from staging.trip_features and distances to artifact bucket.",
)
def training_set(redshift: RedshiftData, artifacts: ArtifactBucket) -> dg.MaterializeResult:
    train_uri = f"{artifacts.uri(TRAIN_PREFIX)}/"
    holdout_uri = f"{artifacts.uri(HOLDOUT_PREFIX)}/"
    dist_uri = f"{artifacts.uri(DIST_PREFIX)}/"

    train_sql = (
        f"unload ('select pickup_zone_id, dropoff_zone_id, pickup_hour, pickup_dow, duration_min "
        f"from staging.trip_features where trip_month in (\'\'2024-01\'\', \'\'2024-02\'\', \'\'2024-03\'\')') "
        f"to '{train_uri}' iam_role default format as parquet allowoverwrite parallel off"
    )
    holdout_sql = (
        f"unload ('select pickup_zone_id, dropoff_zone_id, pickup_hour, pickup_dow, duration_min "
        f"from staging.trip_features where trip_month in (\'\'2024-04\'\')') "
        f"to '{holdout_uri}' iam_role default format as parquet allowoverwrite parallel off"
    )
    dist_sql = (
        f"unload ('select pickup_zone_id, dropoff_zone_id, median(trip_distance) as est_distance_miles "
        f"from staging.stg_trips where trip_month in (\'\'2024-01\'\', \'\'2024-02\'\', \'\'2024-03\'\') "
        f"and duration_min > 0 and duration_min <= 180 and trip_distance > 0 group by 1, 2') "
        f"to '{dist_uri}' iam_role default format as parquet allowoverwrite parallel off"
    )
    redshift.execute(train_sql, holdout_sql, dist_sql)
    return dg.MaterializeResult(
        metadata={
            "training_window": dg.MetadataValue.text(WINDOW_STR),
            "holdout_month": dg.MetadataValue.text(HOLDOUT_MONTH),
            "train_uri": dg.MetadataValue.text(train_uri),
            "holdout_uri": dg.MetadataValue.text(holdout_uri),
            "dist_uri": dg.MetadataValue.text(dist_uri),
        }
    )


@dg.asset(
    deps=[training_set],
    group_name="model",
    kinds={"mlflow"},
    description="Fit LightGBMModel on 2024-01..2024-03, log to MLflow as pyfunc, register to trip-duration.",
)
def trained_model(artifacts: ArtifactBucket, tracking: MlflowTracking) -> dg.MaterializeResult:
    train = artifacts.read_parquet(TRAIN_PREFIX)
    distances = artifacts.read_parquet(DIST_PREFIX)

    train[REQUIRED] = train[REQUIRED].astype("int64")
    train[LABEL] = train[LABEL].astype("float64")
    distances[["pickup_zone_id", "dropoff_zone_id"]] = distances[["pickup_zone_id", "dropoff_zone_id"]].astype("int64")
    distances["est_distance_miles"] = distances["est_distance_miles"].astype("float64")

    model = tripmodel.LightGBMModel().fit(train, distances, num_rounds=200)

    tracking.client()  # ensures experiment exists and tracking uri is set
    contract = mlflow_contract()
    exp_name = contract["experiment"]
    reg_name = contract["registered_model"]

    mlflow.set_tracking_uri(tracking.tracking_uri)
    mlflow.set_experiment(exp_name)

    tripmodel_dir = str(Path(tripmodel.__file__).parent)

    with mlflow.start_run(run_name=f"train_{WINDOW_STR}") as run:
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=model,
            signature=tripmodel.model_signature(),
            code_paths=[tripmodel_dir],
            registered_model_name=reg_name,
        )
        run_id = run.info.run_id
        version = info.registered_model_version

    return dg.MaterializeResult(
        metadata={
            "run_id": dg.MetadataValue.text(run_id),
            "model_version": dg.MetadataValue.text(str(version)),
            "model_uri": dg.MetadataValue.text(f"models:/{reg_name}/{version}"),
        }
    )


@dg.asset(
    deps=[trained_model],
    group_name="model",
    kinds={"mlflow"},
    description="Evaluate new model version vs champion (or v1 baseline) on 2024-04 holdout, tag version and log metrics.",
)
def eval_report(artifacts: ArtifactBucket, tracking: MlflowTracking, redshift: RedshiftData) -> dg.MaterializeResult:
    client = tracking.client()
    contract = mlflow_contract()
    exp_name = contract["experiment"]
    reg_name = contract["registered_model"]

    vs = client.search_model_versions(f"name = '{reg_name}'", order_by=["version_number DESC"])
    if not vs:
        raise RuntimeError(f"No model versions found in {reg_name}")
    candidate = vs[0]
    candidate_ver = candidate.version
    candidate_run_id = candidate.run_id

    holdout = artifacts.read_parquet(HOLDOUT_PREFIX)
    holdout[REQUIRED] = holdout[REQUIRED].astype("int64")
    holdout[LABEL] = holdout[LABEL].astype("float64")

    zones = redshift.query("select location_id, borough from ingest.taxi_zones")
    boroughs = {int(z["location_id"]): str(z["borough"]) for z in zones}

    mlflow.set_tracking_uri(tracking.tracking_uri)
    mlflow.set_experiment(exp_name)

    candidate_model = mlflow.pyfunc.load_model(f"models:/{reg_name}/{candidate_ver}")
    metrics = tripmodel.evaluate(lambda df: candidate_model.predict(df), holdout, boroughs, latency_samples=200)

    # Compare against champion if exists, else v1 baseline
    champion_mae = None
    try:
        champ_mv = client.get_model_version_by_alias(reg_name, "champion")
        champ_model = mlflow.pyfunc.load_model(f"models:/{reg_name}@{champ_mv.alias}")
        champ_eval = tripmodel.evaluate(lambda df: champ_model.predict(df), holdout, boroughs, latency_samples=50)
        champion_mae = float(champ_eval["mae_min"])
    except Exception:
        train = artifacts.read_parquet(TRAIN_PREFIX)
        dist = artifacts.read_parquet(DIST_PREFIX)
        train[REQUIRED] = train[REQUIRED].astype("int64")
        train[LABEL] = train[LABEL].astype("float64")
        dist[["pickup_zone_id", "dropoff_zone_id"]] = dist[["pickup_zone_id", "dropoff_zone_id"]].astype("int64")
        dist["est_distance_miles"] = dist["est_distance_miles"].astype("float64")
        v1 = tripmodel.BaselineModel().fit(train, dist)
        v1_eval = tripmodel.evaluate(lambda df: v1.predict(None, df), holdout, boroughs, latency_samples=50)
        champion_mae = float(v1_eval["mae_min"])

    metrics["champion_mae_min"] = champion_mae

    # Log metrics to candidate's training run
    with mlflow.start_run(run_id=candidate_run_id):
        for k, v in metrics.items():
            mlflow.log_metric(k, float(v))

    # Set version tags required by contracts/mlflow.yaml
    tags = {
        "training_window": WINDOW_STR,
        "holdout_month": HOLDOUT_MONTH,
        "features_version": "1",
        "git_sha": _git_sha(),
        "mae_min": f"{metrics['mae_min']:.4f}",
        "p95_latency_ms": f"{metrics['p95_latency_ms']:.2f}",
        "champion_mae_min": f"{champion_mae:.4f}",
    }
    for tag_name, tag_val in tags.items():
        client.set_model_version_tag(reg_name, candidate_ver, tag_name, str(tag_val))

    return dg.MaterializeResult(
        metadata={
            "version": dg.MetadataValue.text(str(candidate_ver)),
            "mae_min": dg.MetadataValue.float(metrics["mae_min"]),
            "champion_mae_min": dg.MetadataValue.float(champion_mae),
            "p95_latency_ms": dg.MetadataValue.float(metrics["p95_latency_ms"]),
        }
    )


@dg.asset_check(
    asset=eval_report,
    blocking=True,
    description="Check that candidate beats champion (or v1 baseline) MAE and meets p95 latency budget (< 10 ms).",
)
def beats_champion(tracking: MlflowTracking) -> dg.AssetCheckResult:
    client = tracking.client()
    contract = mlflow_contract()
    reg_name = contract["registered_model"]

    vs = client.search_model_versions(f"name = '{reg_name}'", order_by=["version_number DESC"])
    if not vs:
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            description="No model versions found to evaluate",
        )
    ver = vs[0]
    mae = float(ver.tags.get("mae_min", 999.0))
    champ_mae = float(ver.tags.get("champion_mae_min", 0.0))
    p95 = float(ver.tags.get("p95_latency_ms", 999.0))

    passed = (mae < champ_mae) and (p95 < 10.0)
    desc = (
        f"Passed: MAE {mae:.3f} < {champ_mae:.3f}, p95 {p95:.1f}ms < 10.0ms"
        if passed
        else f"Failed gate: MAE {mae:.3f} (champ {champ_mae:.3f}), p95 {p95:.1f}ms (budget 10.0ms)"
    )

    return dg.AssetCheckResult(
        passed=passed,
        severity=dg.AssetCheckSeverity.ERROR,
        description=desc,
        metadata={
            "mae_min": dg.MetadataValue.float(mae),
            "champion_mae_min": dg.MetadataValue.float(champ_mae),
            "p95_latency_ms": dg.MetadataValue.float(p95),
        },
    )


@dg.asset(
    deps=[eval_report],
    group_name="model",
    kinds={"mlflow"},
    description="Sets the challenger alias in MLflow to the candidate model version.",
)
def challenger(tracking: MlflowTracking) -> dg.MaterializeResult:
    client = tracking.client()
    contract = mlflow_contract()
    reg_name = contract["registered_model"]

    vs = client.search_model_versions(f"name = '{reg_name}'", order_by=["version_number DESC"])
    if not vs:
        raise RuntimeError(f"No model versions found in {reg_name}")
    candidate_ver = vs[0].version
    client.set_registered_model_alias(reg_name, "challenger", str(candidate_ver))

    return dg.MaterializeResult(
        metadata={
            "challenger_version": dg.MetadataValue.text(str(candidate_ver)),
            "alias": dg.MetadataValue.text("challenger"),
        }
    )


train_model = dg.define_asset_job(
    "train_model",
    selection=dg.AssetSelection.assets(
        "training_set", "trained_model", "eval_report", "challenger"
    ),
    description="Train LightGBM on 2024-01..03, evaluate on 2024-04 holdout, gate on beating champion and latency, and set challenger alias.",
)
