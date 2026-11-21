# 008: Training window and holdout selection

Stage: S2 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Use a strictly chronological temporal split: train the model on a historical window of the first three available months (`2024-01` through `2024-03`, representing ~9.5 million rides), and evaluate model performance on the subsequent unseen holdout month (`2024-04`, representing ~3.5 million rides).

## Rejected alternative

Using a random or stratified split across all four months combined (e.g. random 80/20 train/test split of pooled Jan–Apr data).

## Why

1. **Elimination of Temporal Data Leakage:** In physical transit networks, rides occurring within the same time window share unobserved correlated shocks (such as localized traffic jams, severe weather, bridge lane closures, or holiday parades). A random split contaminates the test set with rides occurring minutes apart from training rides, allowing the model to "memorize" temporal anomalies rather than learning generalizable patterns.
2. **Realistic Production Simulation:** In live deployment, models must predict future rides using only historical observations. A chronological holdout rigorously evaluates whether the model can generalize forward across seasonal drift (e.g., transitioning from winter blizzards to spring road construction).
3. **Statistical Significance:** With over 3.5 million rides in April 2024, the single-month holdout provides overwhelming statistical power across all geographic sub-slices (airports, Manhattan, outer boroughs) without needing artificial sampling.

## What would show this was wrong

If seasonal drift between quarters is so extreme that a 3-month rolling training window fails to capture annual seasonality, requiring a multi-year training window or an expanding horizon once older historical data becomes available.
