"""retrain_on_drift (decision 022) against a real (ephemeral) Dagster instance."""

import dagster as dg

from labpipes.definitions import defs
from labpipes.defs.training import retrain_on_drift


def test_retrains_only_past_the_threshold():
    with dg.instance_for_test() as instance:
        instance.report_runless_asset_event(dg.AssetMaterialization("drift_report", partition="2024-04", metadata={"max_psi": 0.05}))
        quiet = retrain_on_drift.evaluate_tick(dg.build_sensor_context(instance=instance, definitions=defs))
        assert not quiet.run_requests and "within" in quiet.skip_message
        instance.report_runless_asset_event(dg.AssetMaterialization("drift_report", partition="2025-01", metadata={"max_psi": 0.31}))
        drifted = retrain_on_drift.evaluate_tick(dg.build_sensor_context(instance=instance, definitions=defs, cursor=quiet.cursor))
        assert len(drifted.run_requests) == 1 and "2025-01" in drifted.run_requests[0].tags["lab/reason"]
