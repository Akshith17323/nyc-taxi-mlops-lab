# 002: Image tag scheme

Stage: S0 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Tag deployable container images with the short Git commit SHA (`sha-${GITHUB_SHA::7}`).

## Rejected alternative

Monotonic semantic versioning (`vX.Y.Z`) or build sequence numbers (`run-${GITHUB_RUN_NUMBER}`).

## Why

In continuous deployment where every merge to `main` deploys immediately, the minor friction of looking up a commit SHA on GitHub to inspect a diff is vastly preferable to the heavy friction, confusion, and drift of maintaining a version-to-commit mapping table.

Using short Git SHA tags establishes a strictly deterministic, immutable 1:1 bidirectional mapping:
1. Every running container in production points directly to the exact Git commit that produced it, satisfying the `/version` contract (`git_sha` and `image_tag`).
2. Rollbacks are foolproof: rolling back to a previous stable state simply requires updating `IMAGE_TAG` to that commit's short SHA without rebuilding or diagnosing which commit corresponded to which version number.

## What would show this was wrong

If operational teams or external API consumers require formal semantic versioning milestones (e.g. SemVer `v1.2.0`) to coordinate breaking interface migrations, or if human operators struggle during high-stress incidents to reason about release chronology without Git tooling.
