# LAIC-GUARD

**Working title:** Lithosphere–Atmosphere–Ionosphere Confounder-Aware Research and Detection System

This repository is a clean research workspace for testing whether independent lithospheric, atmospheric, ionospheric and electromagnetic observations contain reproducible information about future earthquakes **beyond conventional seismicity and environmental baselines**.

> This is a research hypothesis, not an established earthquake-prediction system. No precursor or forecast skill is assumed.

## Start here

1. Read `docs/00_PROJECT_CHARTER.md`.
2. Read `docs/01_RESEARCH_PROTOCOL_DRAFT.md`. The event criteria in it are provisional and must be frozen before examining event-aligned anomalies.
3. Fill in `metadata/source_registry.csv` before downloading any dataset.
4. Download original data only into `data/raw/`.
5. Record every downloaded file in `metadata/data_manifest.csv`, including its SHA-256 checksum and source URL.
6. Keep original files unchanged. Put transformations in `data/interim/`, curated analysis-ready data in `data/processed/`, and model-ready features in `data/features/`.
7. Run scripts only after their input/output contracts and tests are defined.
8. Commit code, documentation, metadata and small reproducibility assets to GitHub. Do **not** push large raw scientific datasets, credentials, or restricted data.

## First milestone

**Do not train a machine-learning model yet.** The first milestone is a reproducible data-availability audit:

- Generate a complete candidate earthquake catalogue from a declared rule.
- Build a station/product inventory.
- Calculate event-by-event coverage for each intended domain and parameter.
- Record exclusions and reasons.
- Produce a coverage report showing what can actually be tested.

The output of this milestone determines the realistic study scope.

## Data layers

- `data/raw/`: untouched downloads; ignored by Git.
- `data/interim/`: intermediate transformations; ignored by Git.
- `data/processed/`: quality-controlled analysis-ready data; ignored by Git unless a small, redistributable sample is explicitly approved.
- `data/features/`: derived features; ignored by Git by default.
- `metadata/`: source registry, manifests, catalogues, coverage and exclusion logs. Small metadata files are version-controlled.
- `reports/`: human-readable reports and selected figures. Only approved, reproducible summaries should be committed.

## File naming convention

Use lowercase `snake_case`, UTC timestamps, and explicit versions. Examples:

- `usgs_comcat_candidate_events_2000_2025_v001.csv`
- `giro_station_inventory_1987_2025_v001.csv`
- `era5_daily_weather_2000_2025_v001.parquet`
- `coverage_matrix_v001.csv`
- `coverage_audit_2026-11-08_v001.md`

Never use names such as `final_final2.csv`. Never overwrite raw data.

## Status vocabulary

Use `planned`, `downloaded`, `hashed`, `qc_pending`, `qc_pass`, `qc_fail`, `analysed`, `verified`, `commit_ready`, `committed`, or `excluded`.

Record status changes and reasons in `metadata/artifact_register.csv` and `docs/03_DECISIONS_LOG.md`.

## GitHub

Git should track the research code and audit trail, not act as a bulk scientific-data warehouse. Keep data local initially. Consider DVC or an approved institutional/object-storage solution later, after data volume, licensing and storage are understood.

Suggested first Git commits:

1. `chore: create LAIC-GUARD research structure`
2. `docs: define provisional research protocol`
3. `data: add source registry and manifest templates`
4. `audit: add reproducible candidate catalogue and coverage audit`

## Reproducibility rules

- Preserve source files exactly as downloaded.
- Store source URL, product/version, download time in UTC, date coverage, file size, SHA-256 and licence/access notes.
- Store software environment and configuration used for every run.
- Do not silently interpolate, forward-fill or back-fill missing observations.
- Do not use future information in a historical forecast.
- Keep event selection, feature selection, thresholds and exclusion rules independent of test outcomes.
- Split by earthquake sequence and time, not randomly by rows.
- Compare multimodal models with seismicity-only baselines.
