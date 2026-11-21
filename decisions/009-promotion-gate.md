# 009: Promotion metric and gate margin

Stage: S2 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Use Mean Absolute Error in minutes (`mae_min`) on the holdout month as the primary promotion metric. To earn the `challenger` alias in MLflow, a candidate model version must strictly outperform the current serving champion (or the v1 median baseline if no champion exists) with `mae_min < champion_mae_min` (margin $> 0.0$ min), while satisfying a strict inference latency budget of `p95_latency_ms < 10.0` ms.

## Rejected alternative

Using Root Mean Squared Error (RMSE) as the promotion gate, or promoting models on accuracy gains without a latency constraint.

## Why

1. **Robustness to Long-Tail Duration Outliers:** NYC taxi ride durations exhibit a heavy right-skewed tail (accidents, parades, or driver meter forgetfulness causing rides to stretch past 120 minutes). RMSE squares errors, giving massive mathematical leverage to rare extreme outliers and pulling model predictions upward, resulting in bloated, inaccurate ETAs for normal commuters. Minimizing MAE predicts the conditional median, providing typical, robust trip estimates.
2. **Alignment with Contracts:** The frozen evaluation contract in `contracts/mlflow.yaml` specifies `mae_min` across all required slices (`mae_min.airport`, `mae_min.manhattan`, `mae_min.outer`, `mae_min.night`).
3. **Operational Latency Guardrail:** A model that marginally reduces MAE but requires complex feature lookups or deep tree ensembles that exceed 10 ms p95 latency degrades real-time user experience in the downstream serving API (S3).

## What would show this was wrong

If severe transit delays or extreme traffic bottlenecks carry asymmetric commercial penalties (e.g. missing an airline flight due to an underestimated airport trip), where penalizing large misses via RMSE or asymmetric quantile loss becomes business-critical.
