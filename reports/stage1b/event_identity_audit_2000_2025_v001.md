# LAIC-GUARD Stage 1B — Preliminary ComCat Event-Identity Audit (v001)

**Generated (UTC):** 2026-11-08T10:25:12Z
**Inputs:** Stage 1A v002 catalogue, 26 annual USGS ComCat GeoJSON summary chunks, 26 query sidecars, and `metadata/data_manifest.csv`.
**Scope:** Event-identity and data-field audit only. No sequence assignment, record exclusion, or final duplicate decision is made here.

**v002 catalogue SHA-256:** `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`
**Data manifest SHA-256:** `5a6dfefba404b93cf3b36e2ced53b17263c7534e81f9b4031f6dbc05307b5241`

## 1. Integrity and catalogue-to-raw alignment

| Check | Result |
|---|---:|
| Annual candidate GeoJSON chunks | 26 |
| Query sidecars | 26 |
| Raw GeoJSON and sidecar SHA-256 / sizes | 52/52 matched manifest |
| Total raw features | 1186 |
| v002 catalogue rows | 1186 |
| Unique raw preferred event IDs | 1186 |
| Catalogue/raw event-ID set | Exact match |
| Key catalogue fields vs raw summary features | 11860 comparisons; 0 mismatches |
| Annual sidecar counts / GeoJSON feature counts | All matched |
| Annual query `minmagnitude` / `eventtype` | All `6.5` / `earthquake` |

The archive contains exactly the 26 annual candidate GeoJSON summary files and their 26 query sidecars. Every one of those 52 files matched its `data_manifest.csv` size and SHA-256 entry. All annual counts matched both the query sidecar count metadata and the number of GeoJSON features.

The v002 event IDs matched the raw GeoJSON preferred IDs one-to-one. Origin times, coordinates, depth, magnitude, magnitude type, place, network, source code, and USGS review status matched the raw feature values.

## 2. ComCat event-ID association audit

USGS ComCat defines `id` as the current preferred event ID; it may change. The GeoJSON `ids` field is a comma-separated list of event IDs associated with that event. In this sample:

| Check | Result |
|---|---:|
| Preferred IDs | 1186 |
| Primary ID also present in its `ids` list | 1186/1186 |
| Associated-ID occurrences (including primary ID) | 6286 |
| Unique associated IDs | 6286 |
| Associated IDs appearing under multiple catalogue features | 0 |
| Events with only one associated ID | 9 |
| Mean / median / maximum associated IDs per event | 5.30 / 5.0 / 10 |

**Result:** No cross-feature overlap was found in the `ids` association lists. That means the supplied current ComCat summary records do not expose a shared associated ID between two different candidate rows.

**Limit:** This does not prove that no two records describe the same physical rupture. It only means ComCat's supplied `ids` association lists did not link two rows in this snapshot. A spatial/time-near pair without a shared associated ID still needs source/product-level adjudication.

## 3. Proximity screen — triage only

A diagnostic screen found **58 pairs** within an explicitly broad search envelope of **1 hour and 100 km epicentral distance**. This envelope is only used to surface pairs for inspection. It is not an accepted duplicate rule, aftershock window, or sequence threshold.

| Diagnostic screen | Pair count |
|---|---:|
| <=60 seconds and <=5 km | 1 |
| <=60 seconds and <=25 km | 2 |
| <=5 minutes and <=100 km | 9 |
| <=1 hour and <=100 km | 58 |

### Two sub-minute pairs requiring detail review

| Event IDs | Origin times (UTC) | Time separation | Epicentral separation | Raw catalogue values |
|---|---|---:|---:|---|
| `usp000d3mb` / `iscgem7398408` | 2004-09-05T14:57:18.610Z / 2004-09-05T14:57:32.270Z | 13.660 s | 3.435 km | M 7.4 (mwb) / M 6.51 (mw) |
| `us7000l9h2` / `us7000l9h4` | 2023-11-08T04:52:51.393Z / 2023-11-08T04:53:49.631Z | 58.238 s | 22.889 km | M 6.7 (mwb) / M 7.1 (mww) |

Neither sub-minute pair shares an associated ID in the supplied ComCat `ids` lists. Do not merge or classify either pair as an aftershock solely from this screen. In particular, the 2004 Japan pair and the 2023 Banda Sea pair must remain separate candidate records pending detail-product review.

All 58 proximity pairs are retained in `close_pair_screen_1h_100km_v001.csv`. Counts under other diagnostic window combinations are in `proximity_threshold_sensitivity_v001.csv`.

## 4. Product-type inventory

The `types` summary property advertises product types associated with each event. Counts below are numbers of candidate event records that advertise each product type; they are not proof that every product payload is accessible or current.

| Product type | Events |
|---|---:|
| `origin` | 1186 |
| `phase-data` | 1185 |
| `moment-tensor` | 1173 |
| `shakemap` | 966 |
| `focal-mechanism` | 615 |
| `finite-fault` | 232 |
| `associate` | 341 |
| `disassociate` | 18 |
| `event-sequence` | 7 |
| `oaf` | 7 |

The `associate` / `disassociate` product types are administrative ComCat product categories. Their presence is a reason to inspect the detailed product payloads, not a standalone identity verdict. There are **345** unique events with either product type; **14** events advertise both types.

The `event-sequence` product is advertised for **7** candidate events. The current USGS Sequence Product describes groups of earthquakes clustered in space and time; USGS notes that its sequence coverage is selective, with international products posted only occasionally. Treat these records as useful auxiliary labels for comparison, not a complete or independent ground truth.

Event IDs advertising `event-sequence`:
`ci38457511`, `nc75095651`, `us6000qw60`, `us6000rsy1`, `us7000nzf3`, `us7000pn9s`, `us7000qd1y`

## 5. Summary-field availability and limitations

The supplied raw GeoJSON files are **summary format**, not event-detail format. They contain preferred event summary fields and a `detail` URL for each event.

Selected non-null summary-field coverage:

| Field | Non-null records |
|---|---:|
| `nst` | 784/1186 |
| `dmin` | 533/1186 |
| `rms` | 1177/1186 |
| `gap` | 1043/1186 |

The summary files do not carry `horizontalError`, `depthError`, `magError`, `locationSource`, or `magSource` as feature properties. Their absence here must not be interpreted as proof that no underlying product or alternative source provides such information. USGS GeoJSON Detail adds associated product objects from contributors; every summary feature in this dataset supplies a `detail` URL. Detail records are therefore the next source to inspect for origins, magnitudes, administrative associations, and product content.

All events have `status=reviewed` in this dataset. USGS documentation notes that reviewed status can range from a quick validity check to careful reanalysis; it is not a guarantee that all event parameters meet this study's quality criteria.

## 6. Detail-review priority list

The next retrieval should prioritize **355** unique events flagged by at least one of these reasons:
- ComCat `associate` product present (341 events before overlap removal).
- ComCat `disassociate` product present (18 events before overlap removal).
- `event-sequence` product present (7 events).
- Either member of a sub-minute proximity pair (4 event IDs before overlap removal).

The complete list, including reasons, IDs and `detail` URLs, is in `detail_review_priority_v001.csv`.

## 7. Stage 1B conclusions — what is and is not established

**Established from supplied files**
1. The 26 annual raw summary chunks and 26 query sidecars are byte-for-byte consistent with the supplied manifest.
2. The 1,186 v002 records map one-to-one to the 1,186 raw GeoJSON preferred event IDs and key summary values.
3. No ComCat associated ID is shared across two candidate rows in this snapshot.
4. The raw summary records expose administrative and event-sequence product flags that identify a smaller priority subset for detail retrieval.
5. Two pairs occur within one minute and 100 km; neither pair is linked by a shared ComCat associated ID.

**Not established**
1. That all 1,186 rows are 1,186 unique physical ruptures.
2. That the 58 proximity pairs found within 1 hour / 100 km are duplicates or belong to one sequence.
3. Mainshock, foreshock, aftershock, or swarm membership.
4. The final count of independent sequences.
5. Complete uncertainty fields or alternative origin/magnitude information for every event.
6. Control-region eligibility.

**No catalogue rows are removed, no sequence IDs are assigned, and no eligibility thresholds are frozen by this audit.**

## 8. Recommended next operation

Retrieve and cache detailed ComCat GeoJSON for the 355 priority events first. Inspect:
- product objects and versions;
- `associate` / `disassociate` product contents;
- `event-sequence` product payloads and membership links;
- alternative origins, magnitudes and source networks;
- any available uncertainty or review metadata.

After adjudicating this priority set, decide whether a full 1,186-event detail cache is warranted. Then retrieve a lower-magnitude context catalogue with a completeness-aware magnitude policy before running sequence algorithms.

## 9. References

1. U.S. Geological Survey, **ComCat Event Terms** — preferred `id` and associated `ids` semantics: https://earthquake.usgs.gov/data/comcat/index.php
2. U.S. Geological Survey, **GeoJSON Detail Format** — detailed event payloads include associated product objects: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson_detail.php
3. U.S. Geological Survey, **How Products Work in ComCat** — event association, product versions and preference: https://earthquake.usgs.gov/data/catalog/products.php
4. U.S. Geological Survey, **Earthquake Sequence Product** — purpose, scope and limitations of the sequence product: https://www.usgs.gov/programs/earthquake-hazards/science/earthquake-sequence-product
5. U.S. Geological Survey, **Data Products** — definitions of `associate`, `disassociate`, `event-sequence`, `origin`, `phase-data` and other product types: https://earthquake.usgs.gov/data/products/

## 10. Generated outputs

- `reports/stage1b/event_identity_audit_2000_2025_v001.md`
- `reports/stage1b/close_pair_screen_1h_100km_v001.csv`
- `reports/stage1b/proximity_threshold_sensitivity_v001.csv`
- `reports/stage1b/comcat_product_presence_v001.csv`
- `reports/stage1b/detail_review_priority_v001.csv`
- `reports/stage1b/summary_property_completeness_v001.csv`
- `reports/stage1b/annual_chunk_verification_v001.csv`

This audit is derived from the provided Stage 1A raw summary files and catalogue. It is a preliminary identity audit, not a final sequence analysis.
