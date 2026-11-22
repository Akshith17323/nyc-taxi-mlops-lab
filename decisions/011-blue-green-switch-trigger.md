# 011: What triggers the blue-green switch

Stage: S3 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Automate the blue-green traffic switch in the Continuous Delivery pipeline (`cd.yaml`) on every push to `main`, triggered strictly after the newly deployed idle container passes synthetic smoke verification (`deploy/web.sh smoke <idle_color> <git_sha>`). The switch is performed atomically by updating Traefik's dynamic service weights (`deploy/web.sh switch <idle_color>`) while keeping the outgoing container running in the background for instant rollback.

## Rejected alternative

Requiring manual human approval before flipping app traffic on routine pushes, or triggering the switch based solely on a shallow TCP or `/healthz` HTTP ping without functional validation.

## Why

1. **Separation of Concerns between Application CD and Model Promotion:** Promoting a new ML model to `champion` represents a high-stakes business risk, which is already gated behind human approval via GitHub Actions Environment reviews (`promote.yaml`). In contrast, routine application code updates (bug fixes, middleware, UI enhancements) require fast, frictionless delivery. Gating every commit behind manual human intervention slows iteration velocity and increases deployment batch sizes.
2. **Strict Pre-Switch Verification via Smoke Tests:** A basic `/healthz` check only confirms that the web process is listening on the port. It cannot catch:
   - *Image provenance failure:* Checking that `GET /version` returns `git_sha == $GITHUB_SHA` guarantees that the running container actually contains the target commit and did not fail an image pull.
   - *Broken integrations:* Sending a synthetic `POST /predict` request through Traefik with the `X-Lab-Color` header validates request routing, payload deserialization, internal communication with serving on port 8001, and response serialization before any real rider encounters the container.
3. **Instant, Zero-Downtime Rollback:** The switch updates `app-live.yaml` in the shared `lab-traefik` volume. Because the previous container remains running, rolling back requires only re-executing `deploy/web.sh switch <previous_color>`, which executes in under one second without container restarts or rebuilding.

## What would show this was wrong

If synthetic smoke tests succeed against single requests but production issues emerge only under aggregate load (e.g. database connection exhaustion or concurrency bottlenecks), indicating the need for phased canary percentage rollouts (introduced in S8) rather than an immediate 100% binary traffic flip.
