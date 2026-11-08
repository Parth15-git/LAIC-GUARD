# LAIC-GUARD — USGS Candidate Catalogue Quality Audit (v002)

**Audit time (UTC):** 2026-11-08T09:24:53.326Z
**Source:** USGS ComCat / FDSN Event Web Service
**Period:** 2000-01-01 through 2025-12-31
**Query:** `minmagnitude=6.5`, `eventtype=earthquake`
**Scope:** Candidate catalogue quality audit only; not the final event-selection decision.

## 1. Integrity results

| Check | Result |
|---|---:|
| USGS count endpoint total | 1186 |
| Catalogue rows | 1186 |
| Unique event IDs | 1186 |
| Duplicate event IDs | 0 |
| Annual chunks | 26 |
| Year/chunk row counts agree | Yes |
| v001 catalogue SHA matches retrieval metadata and manifest | Yes |
| Raw chunk SHA and feature counts verified locally | Yes |
| Event type | All rows are `earthquake` |
| USGS event status | {'reviewed': 1186} |

## 2. Magnitude-type distribution

| magType | Count |
|---|---:|
| `mww` | 647 |
| `mwc` | 390 |
| `mwb` | 116 |
| `mw` | 20 |
| `mb` | 8 |
| `md` | 2 |
| `ms` | 2 |
| `ml` | 1 |


- Explicit Mw subtypes (`mww`, `mwc`, `mwb`, and other named Mw families): **1153 (97.22%)**.
- Generic `mw` labels: **20 (1.69%)**; retain for separate review rather than silently dropping or merging.
- Other preferred magnitude types: **13 (1.10%)**.

The query's `minmagnitude` threshold is applied to the preferred magnitude returned by ComCat; the current USGS API documentation describes `minmagnitude` but does not expose a `magnitudetype` query parameter in its implementation parameter list. Therefore this is not a strict Mw-only catalogue. See the USGS API documentation and magnitude-type definitions in the literature register / project notes.

## 3. Depth distribution

| Class | Count | Percentage |
|---|---:|---:|
| Shallow (<70 km) | 912 | 76.90% |
| Intermediate (70 to <300 km) | 151 | 12.73% |
| Deep (>=300 km) | 123 | 10.37% |

Depth range: 2.7–676.4 km.
Events with reported depth exactly 10.0 km: **171**. These records are identified for review by their reported value (`depth_km == 10.0`); in v002, the per-record `depth_screening_status` remains `not_screened` for all 1,186 records. This is an audit finding, not a completed depth-quality determination. The records are not automatically excluded. USGS notes that 10 km can be used as a fixed default when depth cannot be reliably determined.

The depth bands follow the common USGS classification: shallow 0–70 km, intermediate 70–300 km, deep 300–700 km. Boundary handling in this report is `<70`, `70 to <300`, and `>=300` to avoid double-counting.

## 4. Other data-quality observations

- Magnitude range: 6.50 to 9.10.
- Events exactly at the query threshold (6.5): 222.
- All event IDs are unique.
- All origin times and coordinates are present and within valid geographic bounds.
- `sequence_id` is intentionally blank; no sequence algorithm has been approved.
- `tectonic_region` is intentionally blank; no source-backed tectonic classification has been applied.

## 5. v001 defects corrected in v002

1. v001 `inclusion_reason` mistakenly repeated each event's own magnitude as if it were the query threshold. v002 correctly states `minmagnitude>=6.5`.
2. v001 `raw_geojson_path` contained an absolute Windows path tied to one computer/user. v002 uses project-relative paths such as `data/raw/usgs/...`.
3. v001 `candidate_status=candidate_unreviewed` could be confused with USGS review status. v002 uses `pending_project_screening`; the separate USGS `event_status` remains unchanged.
4. v001 classified generic `mw` as non-moment. v002 labels it `generic_mw_label_review` so it remains visible for an explicit policy decision.

## 6. Recommended scientific treatment (not an exclusion decision)

- Keep all 1,186 records in the broad candidate catalogue.
- Create a primary shallow-event analysis stratum and separate intermediate/deep sensitivity strata; do not silently discard deeper events.
- Keep the three explicit Mw subtypes and generic `mw` labels distinguishable until the magnitude policy is frozen.
- Review all 10 km depth events and any other fixed/rounded depths using event detail products or source metadata where possible.
- Group dependent sequences before creating train/calibration/test splits.
- Only then intersect candidates with station and satellite coverage.

## 7. Outputs

- Corrected derivative: `metadata/event_catalogue_v002.csv`
- Magnitude summary: `reports/coverage_audit/usgs_magnitude_type_summary_2000_2025_v002.csv`
- Depth summary: `reports/coverage_audit/usgs_depth_distribution_2000_2025_v002.csv`
- Yearly summary: `reports/coverage_audit/usgs_yearly_catalogue_summary_2000_2025_v002.csv`
- Correction metadata: `reports/coverage_audit/usgs_catalogue_correction_metadata_2000_2025_v002.json`

**v001 remains preserved. v002 is a corrected derivative, not a new USGS download.**

## 8. References and provenance

### USGS source documentation

1. U.S. Geological Survey, **API Documentation — Earthquake Catalog (FDSN Event Web Service)**. https://earthquake.usgs.gov/fdsnws/event/1/swagger.json
   The documented query parameters include `minmagnitude` and `eventtype`; no `magnitudetype` query parameter is listed in the current USGS implementation documentation. The catalogue is therefore a preferred-magnitude-threshold candidate set, not a query-enforced Mw-only set.
2. U.S. Geological Survey, **Magnitude Types**. https://www.usgs.gov/programs/earthquake-hazards/magnitude-types
3. U.S. Geological Survey, **Determining the Depth of an Earthquake**. https://www.usgs.gov/programs/earthquake-hazards/determining-depth-earthquake
4. U.S. Geological Survey, **Why do so many earthquakes occur at a depth of 10 km?** https://www.usgs.gov/faqs/why-do-so-many-earthquakes-occur-a-depth-10km

### Provenance note

The file `usgs_catalogue_retrieval_metadata_2000_2025_v001.json` is a reconstructed provenance record, not a byte-for-byte recovery of the originally generated JSON. It was rebuilt from the preserved annual query sidecars, raw GeoJSON responses, v001 catalogue, and data manifest. The reconstruction utility and subsequent audit both completed their local verification checks. The original v001 catalogue remains unchanged.
