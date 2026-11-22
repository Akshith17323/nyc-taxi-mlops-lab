# 013: SLO targets for the ride prediction service

Stage: S5 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Set two Service Level Objectives for the `/predict` route:
1. **Availability:** 99.5% of requests answered successfully by the ML model (HTTP 200 without static fallback) over rolling windows, alerted via multi-window multi-burn-rate rules (14.4x fast burn over 1h/5m, 6x slow burn over 1h/15m).
2. **Latency:** 95.0% of requests completed in $\le$ 200 ms inside the application container.

## Rejected alternative

- Availability: 99.0% (too forgiving, allowing up to 7.2 hours of downtime or fallback degradation per month before exhausting budget) or 99.9% (unrealistic for a single-AZ, single-instance burstable EC2 deployment without automated failover).
- Latency: 99.0% $\le$ 100 ms (too brittle under burstable CPU scheduling and container warm-ups) or 90.0% $\le$ 500 ms (noticeably sluggish for riders requesting instant fare quotes).

## Why

1. **User Experience & Degradation Semantics:** When the serving container (`serving-champion`) is unreachable or misconfigured, the application catches the error and serves a static median fallback (12.25 min) with HTTP 200. While resilient, fallback quotes represent an ML system failure. Defining availability around successful model-served quotes (`lab_predictions_total{source="model"}`) ensures operators are alerted when riders stop receiving dynamic ML quotes.
2. **Realistic Operational Budget:** 99.5% provides a 0.5% error budget (~3.6 hours/month). This gives enough margin for planned blue-green deployments, container restarts, and MLflow model reloads without triggering spurious pages, while multi-window burn rate alerting catches sustained outages within 2–3 minutes.
3. **Headroom for Proxy & Burstable CPU:** LightGBM tree inference takes 5–15 ms on Graviton CPU. Adding Traefik proxy hops, network latency, and OS scheduling jitter, 200 ms p95 delivers snappy interactivity while remaining robust to transient CPU credit throttling.

## What would show this was wrong

If burstable instance CPU exhaustion or Docker network jitter triggers false latency alerts during normal serving workloads (requiring relaxing to 250 ms), or conversely, if the infrastructure scales to a multi-AZ load-balanced fleet capable of supporting 99.9% availability.
