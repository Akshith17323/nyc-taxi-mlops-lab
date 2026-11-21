# 006: Dist and sort keys for trip tables

Stage: S1 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Configure the dimension lookup table `ingest.taxi_zones` with `DISTSTYLE ALL`. Configure fact tables `ingest.raw_trips` and `staging.stg_trips` with `DISTSTYLE EVEN` and `SORTKEY (pickup_at)` (or `tpep_pickup_datetime`).

## Rejected alternative

Using `DISTSTYLE KEY (pickup_zone_id)` on trip fact tables, or using a compound sort key `SORTKEY (pickup_zone_id, pickup_at)`.

## Why

1. **Broadcast Join Co-location:** Replicating the 263-row `taxi_zones` table across every slice with `DISTSTYLE ALL` allows `zone_hour_stats` to perform `LEFT JOIN ingest.taxi_zones` entirely locally in memory on each slice, with zero network broadcast shuffle.
2. **Skew Prevention:** Distributing trip tables with `EVEN` ensures balanced data volume across all slices. In contrast, `DISTKEY (pickup_zone_id)` would create severe data skew because high-density NYC zones (such as JFK Airport and Midtown) concentrate millions of trips while outer borough zones have very few, bottlenecking the cluster on the slowest slice.
3. **Zone Map Pruning on Chronological Windows:** Queries across our pipeline filter primarily by time (monthly Dagster runs and Stage 2 chronological train/validation splits). A single sort key on `pickup_at` allows Redshift's 1 MB zone maps to skip irrelevant disk blocks effectively. A compound key starting with `pickup_zone_id` would degrade block pruning for date-only queries that span all zones.

## What would show this was wrong

If the query pattern shifts such that analytical queries almost exclusively filter on specific individual zones and join with multi-million row zone-partitioned tables rather than filtering across city-wide time windows.
