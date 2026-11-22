# 010: Load at start-up or reload on alias change

Stage: S3 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Use in-memory hot reload via `POST /reload` on loopback (triggered by `deploy/web.sh reload <alias>`) for serving containers to pick up updated MLflow model aliases. The serving container downloads, instantiates, and warms up the new model in RAM while the outgoing model continues serving incoming predictions, swapping the internal model pointer atomically only after the new version is verified ready.

## Rejected alternative

Restarting the serving container (`docker compose restart serving-<alias>`) upon model alias promotion or retraining.

## Why

1. **Zero-Downtime Serving and Uninterrupted SLA:** When a new `champion` is promoted, restarting the serving container incurs a 15–25 second gap while the container shuts down, boots up, initializes Python/MLflow runtimes, downloads the model artifact from S3, and compiles/warms the predictor. During this downtime, Traefik marks serving unhealthy, forcing the rider-facing application to fall back to quoting the static median duration (12.25 min). Planned, routine model updates should be transparent to riders and must not degrade prediction quality.
2. **Blast-Radius Containment on Load Failure:** If a newly promoted model artifact is corrupted, has missing dependencies, or fails warmup, `POST /reload` catches the exception inside the handler and returns HTTP 500 to the promotion workflow. Crucially, the previously loaded model remains in memory and continues serving live traffic. A container restart under the same conditions results in a crash-loop or permanent 503 unready state, stranding riders on fallback quotes until manual intervention.
3. **Acceptable Resource Overhead:** The LightGBM model artifact is compact (~5–15 MB), meaning the temporary memory overhead of holding both the incoming and outgoing models in RAM during warmup is negligible on our EC2 instance (`t4g.small` / `t4g.medium`).

## What would show this was wrong

If future models grow into multi-gigabyte deep neural networks where keeping two concurrent versions in memory causes container Out-Of-Memory (OOM) termination, or if the Python process accumulates state or uncollected memory leaks across repeated reloads, necessitating a clean process restart boundary.
