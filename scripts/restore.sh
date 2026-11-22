#!/usr/bin/env bash
# Bring the lab back after a session end (runbooks/restore.md), from the laptop, and wait until a
# rider would see the champion again. Idempotent: anything already up is left alone, and the
# platform's `wake` service may already have done steps 1-2.
#
#   scripts/restore.sh [--notebook]
#
# Needs this session's credentials in the environment, gh, and infra/live initialised.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
root="$(cd "$(dirname "$0")/.." && pwd)"
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
t0=$(date +%s)
since() { echo "$(( $(date +%s) - t0 ))s"; }

aws sts get-caller-identity >/dev/null || { echo "export this session's credentials first" >&2; exit 1; }
ip=$(curl -fsS -m 5 https://checkip.amazonaws.com || true)
grep -q "\"$ip/32\"" "$root/infra/live/terraform.tfvars" ||
  echo "note: your IP $ip isn't in ingress_cidrs; update terraform.tfvars and apply to reach the app"

rds=$(aws rds describe-db-instances --db-instance-identifier lab --query 'DBInstances[0].DBInstanceStatus' --output text)
[[ $rds == stopped ]] && aws rds start-db-instance --db-instance-identifier lab --query DBInstance.DBInstanceStatus --output text
rs=$(aws redshift describe-clusters --cluster-identifier lab --query 'Clusters[0].ClusterStatus' --output text)
[[ $rs == paused ]] && aws redshift resume-cluster --cluster-identifier lab --query Cluster.ClusterStatus --output text
if [[ ${1:-} == --notebook ]]; then
  nb=$(aws sagemaker describe-notebook-instance --notebook-instance-name lab --query NotebookInstanceStatus --output text)
  [[ $nb == Stopped ]] && aws sagemaker start-notebook-instance --notebook-instance-name lab && echo "notebook starting"
fi

echo "waiting for Redshift and RDS (RDS takes about 7 minutes from stopped)"
aws redshift wait cluster-available --cluster-identifier lab && echo "redshift available ($(since))"
aws rds wait db-instance-available --db-instance-identifier lab && echo "rds available ($(since))"

app=$(terraform -chdir="$root/infra/live" output -raw app_public_ip)
echo "waiting for the app to answer with the champion (Dagster, MLflow and serving recover on their own)"
for _ in $(seq 60); do
  r=$(curl -fsS -m 10 "http://$app/predict" -H 'Content-Type: application/json' \
    -d '{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}' 2>/dev/null || true)
  jq -e '.model.alias == "champion"' <<<"$r" >/dev/null 2>&1 && { echo "champion answers ($(since)): $r"; break; }
  sleep 10
done

gh workflow run status.yaml --repo "$repo" --ref main
echo "status workflow started; scripts/health.sh in a minute should be all OK"
