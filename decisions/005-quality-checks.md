# 005: Quality checks on staging trips

Stage: S1 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Treat staging tables (`staging.stg_trips`) as raw, uncleaned data by designating row-level data quality checks (negative durations, unknown zones, negative fares) as **Warnings (`blocking=False`)**, while enforcing **Blocking (`blocking=True`)** only for pre-ingestion schema contract violations on `trip_files` and catastrophic file-truncation failures (monthly row count `< 1,000`). Row-level filtering is deferred to the downstream feature engineering layer (`staging.trip_features`).

## Rejected alternative

Setting row-level quality checks (such as zero tolerance for negative duration or unknown zones) to `blocking=True` on `stg_trips`.

## Why

1. **Uncleaned Staging Principle:** In ELT architectures, staging tables reflect raw physical operational data. Real NYC TLC yellow taxi records routinely exhibit sensor or meter glitches (such as ~0.05% negative durations from clock sync shifts or passenger dispute refunds).
2. **Pipeline Resilience:** If row-level checks blocked on uncleaned staging tables, the ingestion pipeline would abort every single month over a handful of noisy rows out of 3 million, needlessly halting downstream reporting marts (`marts.zone_hour_stats`).
3. **Separation of Concerns:** Staging checks serve as observational health monitors (surfacing metadata and error counts in Dagster UI). The proper place for blocking row-level constraints is downstream in Stage 2 (`trip_features`), where filtering and imputation occur before feeding the ML model.

## What would show this was wrong

If downstream analytics marts or reporting tools begin ingesting and publishing invalid metrics because downstream filtering logic was omitted or misconfigured, requiring earlier hard gates at the staging boundary.
