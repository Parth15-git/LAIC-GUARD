# LAIC-GUARD — USGS Candidate Catalogue Review (v001)

**Reviewed from user-supplied files:** `event_catalogue.csv`, `usgs_catalogue_retrieval_metadata_2000_2025_v001.json`, and `data_manifest.csv`.
**Catalogue period:** 2000-01-01 to 2025-12-31 UTC.
**Query:** `minmagnitude=6.5`, `eventtype=earthquake`.
**Interpretation:** broad candidate catalogue; not strict Mw-only and not final study eligibility.

## 1. Integrity checks completed on supplied files

| Check | Result |
|---|---:|
| Rows in catalogue CSV | 1,186 |
| USGS count endpoint total | 1,186 |
| Unique event IDs | 1,186 |
| Duplicate event IDs | 0 |
| Yearly counts represented by CSV | All 26 match retrieval metadata |
| Expected vs returned features by annual chunk | All 26 match in retrieval metadata |
| Catalogue SHA-256 vs retrieval metadata | Match |
| Catalogue SHA-256 vs manifest | Match |
| Raw-chunk SHA values in retrieval metadata vs manifest | All 26 match |
| Event type | 1,186 `earthquake` |
| USGS event status | 1,186 `reviewed` |
| Required core fields | No missing values in event ID, time, coordinates, depth, magnitude or magType |
| Coordinates and times | All present and within valid geographic/time ranges |

**Verification boundary:** raw GeoJSON files were not among the three uploaded files reviewed in this chat. The metadata's raw hashes match the manifest hashes, but the raw-file bytes themselves have not been rehashed here. The supplied patch script performs that byte-level verification on Parth's local project before producing v002.

## 2. Magnitude-type distribution

| Preferred `magType` | Count | Review interpretation |
|---|---:|---|
| `mww` | 647 | Explicit moment-magnitude subtype |
| `mwc` | 390 | Explicit moment-magnitude subtype |
| `mwb` | 116 | Explicit moment-magnitude subtype |
| `mw` | 20 | Generic Mw label; keep separately flagged for review |
| `mb` | 8 | Non-Mw preferred magnitude |
| `md` | 2 | Non-Mw preferred magnitude |
| `ms` | 2 | Non-Mw preferred magnitude |
| `ml` | 1 | Non-Mw preferred magnitude |
| **Total** | **1,186** | |

- Explicit Mw subtypes (`mww`, `mwc`, `mwb`): **1,153 (97.22%)**.
- Generic `mw` labels: **20 (1.69%)**.
- Other preferred magnitude types (`mb`, `md`, `ms`, `ml`): **13 (1.10%)**.

Do not silently discard the 20 `mw` rows or merge them into a single specific subtype. Do not automatically exclude the 13 non-Mw preferred-magnitude rows without checking whether event-detail products contain alternative magnitudes. USGS event-specific queries can return associated magnitude information; this should be a separate, auditable enrichment step.

The USGS magnitude-type reference distinguishes Mww, Mwc and Mwb and describes their waveform/moment-tensor bases and preferred-authority relationships. Official reference: https://www.usgs.gov/programs/earthquake-hazards/magnitude-types

The current USGS Event Catalog API documentation lists `minmagnitude` but does not list a `magnitudetype` filter in its implemented parameter table. Thus the present threshold is not an Mw-only query. API reference: https://earthquake.usgs.gov/fdsnws/event/1/swagger.json

## 3. Depth distribution

| Depth class | Count | Percentage |
|---|---:|---:|
| Shallow: 0 to <70 km | 912 | 76.90% |
| Intermediate: 70 to <300 km | 151 | 12.73% |
| Deep: >=300 km | 123 | 10.37% |
| **Total** | **1,186** | **100%** |

Depth range: **2.7–676.4 km**. There are **274 events at 70 km or deeper**. There are **171 events with reported depth exactly 10.0 km**.

USGS uses the broad classification shallow 0–70 km, intermediate 70–300 km and deep 300–700 km. The v002 script makes the boundaries non-overlapping as `<70`, `70 to <300`, and `>=300`. Reference: https://www.usgs.gov/programs/earthquake-hazards/determining-depth-earthquake

The 171 events at exactly 10 km should be flagged for depth-quality review, not automatically rejected. USGS notes that 10 km can be assigned as a fixed depth when data are insufficient to determine a reliable depth. This does not prove that every 10 km event is fixed. Reference: https://www.usgs.gov/faqs/why-do-so-many-earthquakes-occur-a-depth-10km

## 4. Additional observations

- Magnitude range: **6.5–9.1**.
- Events exactly at the query floor 6.5: **222**.
- Events with magnitude >=7.0: **387**.
- Events with magnitude >=8.0: **28**.
- All 1,186 USGS `event_status` values are `reviewed`. This is the USGS status, not LAIC-GUARD's scientific eligibility review.
- `sequence_id` and `tectonic_region` are blank by design. No sequence grouping or tectonic-region source has yet been applied.
- The count audit and full download cover all 26 years with one annual chunk per year; the supplied metadata shows expected and returned counts agree for every chunk.

## 5. Defects in v001 to correct in v002

1. **Incorrect inclusion-reason text:** the original builder used each row's preferred magnitude in the sentence describing the query threshold. For example, an event with magnitude 7.2 was described as having been returned by a `minmagnitude>=7.2` query. The actual API query was `minmagnitude=6.5`. This does not alter the fetched event set, but it makes the row-level provenance explanation incorrect.
2. **Absolute local paths:** every `raw_geojson_path` stores `C:/Users/parth/.../LAIC-GUARD/...`, tying the catalogue to one machine and OneDrive path. Convert to `data/raw/usgs/...` project-relative paths.
3. **Ambiguous screening status:** `candidate_unreviewed` can be confused with `event_status=reviewed`. The v002 script sets the project status to `pending_project_screening` while preserving USGS status.
4. **Generic `mw` classification:** v001 classifies `mw` as `other_or_non_moment_type`. v002 should mark it separately as `generic_mw_label_review` pending a declared magnitude policy.

## 6. Recommended scientific decisions — not yet applied

- Preserve all 1,186 rows in the broad candidate catalogue.
- Decide in advance whether the main study is restricted to shallow events or uses separate shallow/intermediate/deep strata. Do not silently remove deep events.
- Keep `mww`, `mwc`, `mwb`, generic `mw` and non-Mw magnitude types explicitly distinguishable until a magnitude eligibility policy is frozen.
- Review depth provenance for the 171 events with reported depth exactly 10 km.
- Add event sequence grouping before any machine-learning split; an earthquake sequence must not leak across training and test sets.
- Proceed to station/product availability coverage only after the catalogue has passed local raw-file hash validation.

**Conclusion:** v001 is a successful broad candidate-catalogue download with matching counts and unique IDs, but it needs a documented v002 metadata correction and local raw-byte verification before being labelled fully verified.
