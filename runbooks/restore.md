# Runbook: bring the lab back after a session end

Owner: reference · Last run: 2026-10-10 (Learner Lab) · Time to restore last run: ~8 min with the wake service, ~12 min by hand

## When to use it

The first thing after Start Lab on a new day, or whenever the app quotes 12.25 minutes for every trip (the static-median fallback), Dagster's UI doesn't load, or `scripts/health.sh` prints a FAIL.

## Before you start

- Start Lab, then export the new session's credentials in your terminal. Yesterday's are dead (they outlive the 4-hour session by about 2 hours, no more).
- `gh auth status` works, and `terraform -chdir=infra/live init -backend-config=backend.hcl` has been run in this checkout.
- Nothing else: the runners and the hosts use the instance profile, so CI, CD and the platform need no new credentials.

## Steps

| # | Check (command) | Healthy looks like | If not: fix (command) | Took | Automated? |
| --- | --- | --- | --- | --- | --- |
| 1 | `scripts/health.sh` | every line OK | read the FAIL lines, go down this table | 10 s | given |
| 2 | `laptop-ip` line | your IP is in `ingress_cidrs` | home and venue IPs differ: update `infra/live/terraform.tfvars`, `terraform apply` (security group only) | 1 min | no: it's a decision about who may reach the app (003) |
| 3 | hosts and runners | `running`, runner `online` | Start Lab starts the EC2 hosts; runners come back with them in under a minute | 1 min | by Learner Lab |
| 4 | `rds` | `available` | `aws rds start-db-instance --db-instance-identifier lab` | ~7 min | yes: `wake` on the platform host |
| 5 | `redshift` | `available` | `aws redshift resume-cluster --cluster-identifier lab` | ~3 min | yes: `wake` |
| 6 | Dagster and MLflow | `status` line OK after `gh workflow run status.yaml` | nothing: they restart on their own, at most a minute apart, until RDS answers. If not: `docker ps` over SSM on the platform host, `docker compose ... up -d` from the platform workflow | ~1 min after RDS | Docker's restart policy |
| 7 | serving | `predict` line says `champion` | serving retries loading its alias every 30 s, so it follows MLflow back; `deploy/web.sh reload champion` on the app host to hurry it | ≤ 30 s after MLflow | serving's retry loop |
| 8 | `notebook` | `InService` (only if you'll use it) | `aws sagemaker start-notebook-instance --notebook-instance-name lab`, then `git pull` in its terminal | ~6 min | no: Day 2 doesn't need it, and it bills while up |

## Done when

1. A rider's quote comes from the champion: `curl -X POST http://<app_public_ip>/predict ...` shows `"alias": "champion"`.
2. `gh workflow run status.yaml` goes green, and the grader's `S4.restored` passes.
3. `scripts/health.sh` exits 0.

## What we automated, and what we left as a step

See `decisions/012-automate-vs-document.md`. The `wake` service on the platform host starts RDS and resumes Redshift whenever the host boots, so pressing Start Lab is the restore; `scripts/restore.sh` does the same from a laptop and waits until a rider would see the champion. Still a person's job: the session credentials (Learner Lab hands them only to a person), the ingress IP (a security decision), the notebook (not needed on Day 2), and stopping things at night (stopping must stay deliberate).
