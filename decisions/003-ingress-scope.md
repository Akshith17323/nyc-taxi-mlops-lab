# 003: Ingress scope

Stage: S0 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Restrict inbound HTTP traffic (port 80) on the app host security group to the Rishihood University learner network subnet (`115.244.141.0/24`) and explicit host IP (`115.244.141.202/32`).

## Rejected alternative

Opening port 80 to the entire internet (`0.0.0.0/0`) or restricting to a single `/32` IP address.

## Why

Operating on Rishihood University's learner Wi-Fi (distinct from guest and staff networks) means client IP addresses are dynamically assigned across campus access points within the institutional `/24` pool.
1. A single `/32` rule fails operationally: moving between classrooms, library, or dorms changes the local IP, instantly dropping connections and necessitating repetitive, disruptive `terraform apply` runs throughout the workday.
2. A completely open `0.0.0.0/0` rule needlessly exposes an unauthenticated `/predict` endpoint and Traefik router to automated global internet port scanners, vulnerability bots, and scrapers, risking credit exhaustion on a strict \$100 Learner Lab budget.

Scoping ingress to the `/24` learner network subnet strikes the optimal balance: it allows seamless campus mobility without state churn while keeping the entire external internet blocked.

## What would show this was wrong

If regular development shifts to off-campus networks (e.g. home or cellular hotspot) where updating `terraform.tfvars` creates excessive friction, or if malicious automated traffic is observed originating from within the campus learner subnet itself.
