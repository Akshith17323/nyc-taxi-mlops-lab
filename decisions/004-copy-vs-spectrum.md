# 004: COPY vs. Redshift Spectrum

Stage: S1 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Use Redshift's native SQL `COPY` command to ingest monthly Parquet trip files directly from S3 into internal Redshift tables (`ingest.raw_trips`).

## Rejected alternative

Redshift Spectrum querying external tables directly in S3 via AWS Glue Data Catalog without physical ingestion.

## Why

1. **Analytical and Training Performance:** Downstream processes (`staging.stg_trips`, `marts.zone_hour_stats`, and S2 feature engineering) query the data repeatedly. Internal Redshift tables leverage columnar compression, local block storage, sort keys, and 1 MB zone maps, delivering significantly faster query throughput than scanning Parquet files over the S3 network repeatedly.
2. **Catalog & IAM Boundaries:** Spectrum relies on AWS Glue Data Catalog permissions and cross-service role delegation, which frequently encounter SCP or IAM restrictions in AWS Academy Learner Lab. Redshift `COPY` using the pre-assigned `LabRole` is self-contained and guaranteed to work natively.
3. **Clean Partition Idempotency:** Monthly reloads can be made strictly idempotent with a simple transactional pair: `DELETE FROM ingest.raw_trips WHERE source_file = '{file}'; COPY ...`.

## What would show this was wrong

If data volume scales to dozens of terabytes exceeding the local managed storage capacity of our Redshift cluster, or if raw trip data is accessed so infrequently that paying for cluster storage outweighs the latency overhead of querying S3 directly.
