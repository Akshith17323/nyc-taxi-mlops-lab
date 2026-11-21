# 001: Runner credentials

Stage: S0 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Use the EC2 instance profile (`LabRole` / `LabInstanceProfile`) for the self-hosted GitHub Actions runner on the app host.

## Rejected alternative

Storing temporary AWS session credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) as GitHub Actions repository secrets.

## Why

In AWS Academy Learner Lab, temporary session credentials expire every 4 hours, which would cause continuous deployment breakage and require manual re-synchronization (`scripts/gh-secrets.sh`) multiple times a day.

Beyond the lab environment, using the instance profile represents enterprise best practice through centralized identity and access management:
1. **Centralized governance:** Permission changes and policy updates are executed once in AWS IAM, and the host runner inherits them instantly without needing to modify GitHub repository secrets or coordinate across repos.
2. **Zero secret sprawl:** No static AWS credentials ever leave AWS, sit in GitHub secret stores, or risk being leaked in CI/CD execution logs.
3. **Automatic rotation:** AWS handles token generation and hourly rotation transparently via IMDSv2.

## What would show this was wrong

If deployment steps must be executed from GitHub-hosted runners outside the AWS VPC requiring direct AWS API access, or if an institutional SCP blocks instance metadata service credential retrieval.
