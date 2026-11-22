# 012: What to automate and what to leave as a documented step

Stage: S4 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Automate idempotent infrastructure wake-up (resuming Redshift and starting RDS), readiness synchronization, and serving quote verification in `scripts/restore.sh`. Leave session credential export, laptop IP ingress modifications, SageMaker notebook startup, and overnight shutdown as documented manual steps in `runbooks/restore.md`.

## Rejected alternative

Attempting to fully automate all startup steps into an unattended background loop, or leaving all restoration steps purely manual in a checklist.

## Why

1. **Idempotence & Toil Reduction:** Starting stopped RDS instances and resuming paused Redshift clusters are standard idempotent AWS API calls with predictable long recovery times (~7 min for RDS, ~3 min for Redshift). Automating the trigger and wait commands saves human waiting time (eliminating operational toil) and guarantees that dependent services (Dagster, MLflow, serving) reconnect in the proper sequence.
2. **Hard Human Boundaries:**
   - *AWS Session Credentials:* AWS Academy Learner Lab only issues temporary STS tokens to an authenticated human user via its portal. A script cannot autonomously bypass this human-in-the-loop auth barrier.
   - *Ingress Scope (ADR 003):* Changing network locations (home, campus, coffee shop) changes public IP addresses. Modifying security group ingress must remain a deliberate security action by the engineer, never an automated wildcard open to `0.0.0.0/0`.
   - *Cost Guardrails:* The SageMaker notebook instance bills continuously while in service (~$0.05/hr) and is not required for Day 2 pipeline or serving operations. It should only be started on demand by an engineer.
   - *Safe Teardown:* Shutting down services at the end of the day must remain deliberate to avoid killing running training batches or evaluation checks.

## What would show this was wrong

If a production cloud environment with permanent IAM roles and fixed corporate VPCs is used, where scheduled cron triggers or infrastructure-as-code state management should automate 100% of the environment lifecycle without any manual human intervention.
