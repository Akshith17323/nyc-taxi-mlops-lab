#!/usr/bin/env bash
# S0: register a host as a self-hosted GitHub Actions runner over SSM.
#
# Usage:
#   scripts/register-runner.sh [app|platform|llm]
#
# Default role: app (label: lab-app).
# Constraints: no SSH (SSM Session Manager only), never commit or print tokens.
# The repo is public, so ensure fork-PR approval is set in GitHub repository settings.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

role="${1:-app}"
case "$role" in
  app|platform|llm) ;;
  *) echo "role must be app, platform or llm" >&2; exit 1 ;;
esac

root="$(cd "$(dirname "$0")/.." && pwd)"

# Verify prerequisites
command -v aws >/dev/null || { echo "aws CLI not found on PATH" >&2; exit 1; }
command -v gh >/dev/null || { echo "gh CLI not found on PATH" >&2; exit 1; }

aws sts get-caller-identity >/dev/null 2>&1 || {
  echo "AWS credentials missing or expired: export them from Learner Lab > AWS Details" >&2
  exit 1
}

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) || {
  echo "gh is not authenticated or cannot access repository" >&2
  exit 1
}

# Resolve instance ID
iid=""
if [[ -f "$root/infra/live/terraform.tfstate" || -f "$root/infra/live/.terraform/terraform.tfstate" ]]; then
  iid=$(terraform -chdir="$root/infra/live" output -raw "${role}_instance_id" 2>/dev/null || true)
fi

if [[ -z "$iid" || "$iid" == "None" ]]; then
  iid=$(aws ec2 describe-instances \
    --filters "Name=tag:project,Values=mlops-lab" "Name=tag:role,Values=$role" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)
fi

[[ -n "$iid" && "$iid" != "None" ]] || {
  echo "could not find running instance for role $role" >&2
  exit 1
}

echo "registering runner for lab-$role on instance $iid ($repo)..."

# Fetch registration token (token is passed via SSM parameter/command stdin, never committed or logged)
token=$(gh api --method POST "repos/$repo/actions/runners/registration-token" -q .token) || {
  echo "failed to generate runner registration token from GitHub API" >&2
  exit 1
}

# Execute registration on instance over SSM RunShellScript
cmd_id=$(aws ssm send-command \
  --instance-ids "$iid" \
  --document-name "AWS-RunShellScript" \
  --comment "Register lab-$role GitHub Actions runner" \
  --parameters "commands=[
    \"set -euo pipefail\",
    \"while [ ! -f /var/lib/lab-setup-done ]; do sleep 2; done\",
    \"cd /opt/actions-runner\",
    \"if [ ! -f ./config.sh ] || ! ./config.sh --version 2>/dev/null | grep -q '2.338.2'; then\",
    \"  if [ -f .runner ]; then ./svc.sh stop || true; ./svc.sh uninstall || true; fi\",
    \"  rm -rf /opt/actions-runner/* /opt/actions-runner/.* 2>/dev/null || true\",
    \"  curl -fsSL -o runner.tar.gz https://github.com/actions/runner/releases/download/v2.338.2/actions-runner-linux-arm64-2.338.2.tar.gz\",
    \"  tar xzf runner.tar.gz\",
    \"  rm -f runner.tar.gz\",
    \"  chown -R runner:runner /opt/actions-runner\",
    \"fi\",
    \"if [ -f .runner ]; then\",
    \"  ./svc.sh stop || true\",
    \"  ./svc.sh uninstall || true\",
    \"  sudo -u runner ./config.sh remove --token \\\"$token\\\" || true\",
    \"fi\",
    \"sudo -u runner ./config.sh --url \\\"https://github.com/$repo\\\" --token \\\"$token\\\" --name \\\"lab-$role\\\" --labels \\\"lab-$role\\\" --unattended --replace\",
    \"./svc.sh install runner\",
    \"./svc.sh start\"
  ]" \
  --query "Command.CommandId" --output text)

echo "SSM command sent ($cmd_id). Waiting for completion..."
aws ssm wait command-executed --command-id "$cmd_id" --instance-id "$iid"

status=$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$iid" --query "Status" --output text)
if [[ "$status" == "Success" ]]; then
  echo "runner lab-$role registered and started successfully"
else
  echo "SSM command ended with status $status" >&2
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$iid" --query "StandardErrorContent" --output text >&2 || true
  exit 1
fi
