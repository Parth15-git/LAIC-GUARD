# LAIC-GUARD Stage 1B — Preliminary Event-Identity Audit Package

This package is based on the user-supplied Stage 1B raw-audit ZIP and the previously supplied
`metadata/event_catalogue_v002.csv`.

## Package contents

- `scripts/05_audit_comcat_event_identity.py` — reproducible, standard-library-only local audit.
- `reports/stage1b/event_identity_audit_2000_2025_v001.md` — narrative audit report.
- `reports/stage1b/close_pair_screen_1h_100km_v001.csv` — 58 provisional proximity pairs.
- `reports/stage1b/proximity_threshold_sensitivity_v001.csv` — screening counts across time/distance windows.
- `reports/stage1b/comcat_product_presence_v001.csv` — ComCat product-type presence counts.
- `reports/stage1b/detail_review_priority_v001.csv` — 355 records prioritized for detailed-product inspection.
- `reports/stage1b/summary_property_completeness_v001.csv` — summary field availability.
- `reports/stage1b/annual_chunk_verification_v001.csv` — per-year input verification.

## Install into the existing project

From the LAIC-GUARD project root, extract this ZIP with `-DestinationPath . -Force`, or copy:
- `scripts/05_audit_comcat_event_identity.py` into the project's `scripts/` directory;
- the included `reports/stage1b/` folder into the project's `reports/` directory.

Do not replace any existing project files; these are new paths.

## Run locally

From the LAIC-GUARD project root:

```powershell
python -m py_compile .\scripts\05_audit_comcat_event_identity.py
python .\scripts\05_audit_comcat_event_identity.py
```

Required existing inputs:
- `metadata/event_catalogue_v002.csv`
- `metadata/data_manifest.csv`
- 26 `usgs_comcat_candidate_events_*.geojson` files under `data/raw/usgs/`
- matching `.query.json` sidecars under `data/raw/usgs/`

The script rehashes the 52 raw inputs against `data_manifest.csv`, checks counts and query metadata,
compares the v002 records with the raw GeoJSON summary features, checks cross-feature ComCat
associated-ID overlaps, audits summary product types and fields, and generates the outputs under
`reports/stage1b/`.

The script performs no web requests. It does not modify the catalogues, manifest, raw data,
sidecars, or Git state. If any required integrity check fails, it stops with an error.

## Scientific limits

- The 1-hour / 100-km pair screen is a triage envelope only, not a deduplication or sequence rule.
- A lack of overlap in ComCat `ids` does not prove that two entries represent distinct physical ruptures.
- The ComCat summary `types` property indicates product-type presence; product payloads must be retrieved and inspected.
- The USGS `event-sequence` product is selective and should be treated as auxiliary information, not a complete gold-standard sequence catalogue.
- No event is excluded, merged, or assigned a sequence ID by this package.

Do not commit the results until the report and generated outputs have been reviewed.
