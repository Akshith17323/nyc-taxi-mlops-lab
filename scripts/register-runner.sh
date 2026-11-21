#!/usr/bin/env bash
# Register a lab host as a self-hosted GitHub Actions runner for this repo.
#
#   scripts/register-runner.sh [app|platform|llm]      (default: app)
#
# Needs: gh logged in with admin on this repo, AWS credentials in the environment, and
# `terraform apply` done in infra/live. The registration token is fetched from GitHub, valid for
# one hour, and handed to the host through SSM Run Command: no SSH, nothing stored in the repo.
# The runner then authenticates to AWS with the instance profile (LabRole), not static keys.
# Safe to re-run: a host that is already registered just reports its status.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

role=${1:-app}
version=2.337.0
root="$(cd "$(dirname "$0")/.." && pwd)"
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
iid=$(terraform -chdir="$root/infra/live" output -raw "${role}_instance_id")
# The repo is public and this runner executes its workflows: fork-PR workflows always wait for
# the owner's approval. Idempotent.
gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" -f approval_policy=all_external_contributors
token=$(gh api -X POST "repos/$repo/actions/runners/registration-token" -q .token)

remote=$(cat <<EOF
set -euo pipefail
test -f /var/lib/lab-setup-done || { echo "host still bootstrapping (see /var/log/lab-setup.log)"; exit 3; }
cd /opt/actions-runner
if [ -f .runner ]; then
  echo "already registered"; ./svc.sh status | head -5; exit 0
fi
case \$(uname -m) in aarch64) arch=arm64 ;; x86_64) arch=x64 ;; *) echo "unsupported arch"; exit 1 ;; esac
curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/v$version/actions-runner-linux-\$arch-$version.tar.gz"
tar xzf runner.tgz && rm runner.tgz && chown -R runner:runner .
sudo -u runner ./config.sh --unattended --replace --url "https://github.com/$repo" --token "$token" \
  --name "lab-$role" --labels "lab-$role" --work _work
./svc.sh install runner
./svc.sh start
EOF
)

params=$(jq -n --arg c "$remote" '{commands: [$c]}')
cmd=$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
  --comment "register lab-$role runner" --parameters "$params" --query Command.CommandId --output text)
echo "registering lab-$role runner on $iid (ssm command $cmd)"
status=Pending
while [[ "$status" =~ ^(Pending|InProgress|Delayed)$ ]]; do
  sleep 5
  status=$(aws ssm get-command-invocation --command-id "$cmd" --instance-id "$iid" --query Status --output text 2>/dev/null || echo Pending)
done
aws ssm get-command-invocation --command-id "$cmd" --instance-id "$iid" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text
[[ "$status" == Success ]] || { echo "registration $status" >&2; exit 1; }
gh api "repos/$repo/actions/runners" -q '.runners[] | "\(.name)\t\(.status)\t\([.labels[].name] | join(","))"'
