# 007: What stays in the notebook vs. what moves into the pipeline

Stage: S2 · Date: 2026-11-21 · Author: Akshith · Drafted by agent: yes

## Choice

Use the SageMaker Jupyter notebook (`notebooks/explore.ipynb`) exclusively for interactive data exploration, visualization, initial model prototyping, and slice analysis. Move all production data extraction (`UNLOAD`), feature transformation, model training with fixed hyperparameters, holdout evaluation, and MLflow model registration into the automated Dagster pipeline (`training.py`). No human and no notebook ever registers a production model or sets an MLflow alias by hand.

## Rejected alternative

Training production models directly from Jupyter notebooks and setting MLflow registered model aliases (`challenger` / `champion`) manually from notebook cells.

## Why

1. **Reproducibility & State Integrity:** Jupyter notebooks suffer from hidden state dependencies, non-linear cell execution order, and uncommitted local file paths. An automated orchestrator (Dagster) guarantees deterministic, repeatable execution from version-controlled git code.
2. **Auditability & Traceability:** Models registered via the pipeline carry reproducible lineage: the exact git commit SHA, the frozen dataset partitions, training window metadata, and evaluation metrics logged automatically as immutable MLflow tags.
3. **Operational Independence:** Automated retraining triggered by new landing data (via Dagster sensors) must execute unattended without requiring an engineer to log into a notebook server, start an instance, and run cells manually.

## What would show this was wrong

If pipeline execution overhead or deployment friction becomes so high that data scientists cannot rapidly iterate on new model architectures without writing full Dagster asset definitions for throwaway experiments.
