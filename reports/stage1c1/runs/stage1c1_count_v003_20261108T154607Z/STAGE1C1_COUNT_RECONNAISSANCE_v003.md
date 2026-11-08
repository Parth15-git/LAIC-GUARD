# LAIC-GUARD Stage 1C.1 — Count-only supporting-catalogue reconnaissance v003

- Run ID: `stage1c1_count_v003_20261108T154607Z`
- Acquisition cutoff (UTC): `2026-11-08T15:46:07.688Z`
- Status: **complete**
- Logical region/threshold/period cells: **150**
- Initial count windows after area-time partitioning: **192**
- Total count requests including count-based subdivision: **312**
- Logical cells with complete leaf counts: **150 / 150**
- Successful responses: **312**
- Failed requests: **0**
- Parent-child count sums matching: **25**
- Parent-child count mismatches: **0**
- Leaf partitions over safe-query ceiling: **0**
- Safe future-query ceiling: **18000 events**
- Supporting event records downloaded: **0**

## Scope

Counts use the USGS ComCat preferred numerical magnitude field with `minmagnitude` values 4.0, 4.5 and 5.0. They are **not confirmed Mw-only counts**. Event type is `earthquake`. The intervals begin on 1980-01-01 UTC to support the approved 20-year pre-context sensitivity design and end at the recorded acquisition cutoff.

## Geographic strata

The regional strata are coarse operational bounding boxes for reconnaissance, not tectonic-region polygons. Some overlap; do not sum regional counts to reproduce the global count. See the CSV for exact bounds and every request URL.

## Query-limit handling

Base counts above 18000 were subdivided using calendar years, then months, then days. Any daily interval remaining above the ceiling is unresolved for future event retrieval and requires a finer or additional partitioning plan before data acquisition. Every subdivided parent count is reconciled against the sum of its direct children; mismatches are retained and flagged, never silently corrected.

## Count partition reconciliation

For every subdivided parent interval, the reported parent count is compared with the exact sum of its direct child interval counts. The request timestamps are preserved because ComCat is a maintained catalogue and counts can change while the reconnaissance is running. A mismatch is a flagged discrepancy, not something to correct silently. Failed child requests make that partition reconciliation incomplete.

## Decision boundary

This run calls only `/count` and `/version`. It does not call `/query`, download event records, modify the frozen 1,186-row target catalogue, or assign sequence labels. A count is reconnaissance evidence, not a catalogue-completeness determination or an Mw threshold count.

## Outputs

- `reconnaissance_count_results_v003.csv`
- `reconnaissance_logical_cell_summary_v003.csv`
- `reconnaissance_request_log_v003.jsonl`
- `run_metadata_v003.json`
- `reconnaissance_summary_v003.json`
