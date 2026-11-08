# LAIC-GUARD Stage 1C.1 — Independent Request-Level Audit v001

- Audited run: `stage1c1_count_v003_20261108T154607Z`
- Audit scope: independent review of the six files in `LAIC-GUARD_Stage1C1_v003_full_evidence.zip`
- Audit result: **PASS WITH DOCUMENTATION CAVEATS**
- Acquisition cutoff (event-time bound): `2026-11-08T15:46:07.688Z`
- Run completed: `2026-11-08T15:54:53.605Z`
- Service version: `2.8.4`

## 1. Scope and limitations

This audit checks the uploaded count-only run evidence: count-results CSV, request/response JSONL, run metadata JSON, logical-cell summary CSV, run summary JSON and Markdown report. It does not independently re-contact USGS, retrieve event records, or re-hash the target catalogue file because that file was not part of the uploaded ZIP. The run metadata records the frozen target catalogue as 1,186 rows with SHA-256 `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`, matching the previously established Stage 1A catalogue hash.

The audit is not a magnitude-completeness analysis and does not establish that the preferred numerical magnitude field is equivalent to Mw.

## 2. Request-level integrity checks

| Check | Result |
|---|---:|
| Count-result CSV rows | 312 |
| Request-log JSONL records | 312 |
| Unique request IDs | 312 |
| CSV/JSONL request ID and order match | 312 / 312 |
| Request URL and logged parameter match | 312 / 312 |
| Endpoint path | `/fdsnws/event/1/count` for all rows |
| HTTP 200 responses | 312 / 312 |
| Failed response states | 0 |
| Attempts per request | 1 for all 312 |
| Response body equals CSV count | 312 / 312 |
| Recomputed response-body SHA-256 matches | 312 / 312 |
| Response byte lengths match | 312 / 312 |
| CSV server Date header equals JSONL header | 312 / 312 |
| Request rows with `eventtype=earthquake`, format `text`, expected threshold and bounds | 312 / 312 |

The service-version response is `2.8.4`, HTTP 200. Its recorded SHA-256 was independently recomputed from the response text and matches.

## 3. Logical-cell coverage and arithmetic

- Logical cells: **150 / 150**.
- Expected grid: 10 geographic strata × 5 time periods × 3 preferred numerical magnitude thresholds = 150.
- Unique logical-cell IDs: 150.
- Every expected region/period/threshold combination is present exactly once.
- All logical cells are marked `complete_sum_of_disjoint_leaf_counts`.
- Every logical-cell leaf count sum was recomputed from the 287 leaf request rows and matches the logical-cell summary.
- Leaf time intervals tile each logical cell's full interval without millisecond gaps or overlaps.
- Threshold ordering is monotonic in every region/period combination: count(≥4.0) ≥ count(≥4.5) ≥ count(≥5.0). No violations.

## 4. Subdivision and query-safety checks

| Check | Result |
|---|---:|
| Initial count windows | 192 |
| Total count requests | 312 |
| Requests linked as child rows | 120 |
| Parent nodes with direct children | 25 |
| Parent-child count sums matching | 25 / 25 |
| Parent child-interval tilings exact | 25 / 25 |
| Leaf partitions | 287 |
| Minimum / maximum leaf count | 152 / 17,939 |
| Leaf partitions above 18,000 | 0 |
| Parent rows above 18,000 (reconciled to children) | 25 |
| Maximum initial/root time-area product | 71,020,800 square-degree-days |
| Conservative time-area budget | 90,000,000 square-degree-days |
| Initial/root windows over budget | 0 |

The 25 request rows with counts above 18,000 are parent aggregates; each has linked children, an exact child-count sum and exact interval coverage. None is a leaf. All 287 leaves are at or below 18,000; the maximum leaf count is 17,939.

The count results contain 192 root requests and 120 linked child rows. The parent-child structure has 25 parent nodes; some child requests are themselves subdivided parents. All parent references resolve, with no orphan child references.

## 5. Global preferred numerical count totals

These figures are sums of the disjoint global time fragments, not confirmed Mw-only counts. The final period is partial and extends to the acquisition cutoff.

| Period | Preferred numerical ≥4.0 | ≥4.5 | ≥5.0 |
|---|---:|---:|---:|
| 1980–1989 | 53,326 | 39,476 | 15,800 |
| 1990–1999 | 76,809 | 43,102 | 14,627 |
| 2000–2009 | 118,917 | 60,558 | 17,234 |
| 2010–2019 | 144,059 | 75,210 | 18,411 |
| 2020–acquisition cutoff | 109,578 | 52,623 | 12,562 |
| **Total** | **502,689** | **270,969** | **78,634** |

Do not compare the raw total for 2020–acquisition cutoff directly with the complete preceding decade totals as though their durations were equal. The nine regional boxes overlap and are exploratory operational strata, not tectonic polygons; do not add their counts to reproduce the global total.

## 6. Decision-boundary checks

- The 312 logged request URLs all use `/count`; no `/query` URL occurs.
- The separate `/version` endpoint returned HTTP 200 and version `2.8.4`.
- Run metadata records `event_records_downloaded = 0`.
- Run metadata records `query_endpoint_called = false`.
- Run metadata records `target_catalogue.modified_by_script = false`.
- The run uses `minmagnitude` against the ComCat preferred numerical magnitude field. These results are **not confirmed Mw-only counts**.
- Counts are reconnaissance coverage evidence only. They do not determine regional/time-dependent magnitude completeness, event detection probability, or sequence membership.

## 7. Documentation caveats (not count failures)

### 7.1 Request-start pacing is not independently verifiable

Run metadata records a configured request interval of 1.0 seconds. However, the request log records `retrieved_at_utc` but does not include request-start timestamps. Among consecutive request IDs, 42 adjacent retrieval-time gaps are below 1.0 second; the minimum is 0.659 seconds. Because these are retrieval timestamps rather than request-start timestamps, this does not prove that the configured start-to-start pacing was violated. It does mean that exact pacing cannot be independently verified from this package. Add `request_started_at_utc` and a monotonic elapsed-time field in a future script version.

### 7.2 Meaning of `subdivision_resolution` on six parent rows

Six parent requests (`R00231, R00242, R00253, R00273, R00284, R00295`) have `query_level=base`, `subdivision_required=true`, positive `direct_child_count` (7 or 10), and exact linked child intervals/count sums, while their `subdivision_resolution` field says `not_subdivided`. The parent-child graph proves that count-based subdivision did occur. This field therefore appears to describe the request's original/base partition level rather than whether that request ultimately generated children. Clarify or rename this field in a future script version; do not use it alone to identify leaf requests. Use `direct_child_count` and `parent_request_id` for the request tree.

### 7.3 Counts are not one atomic database snapshot

Requests were executed over approximately 8.76 minutes. Each response has its own server Date header and retrieval timestamp. The 25 parent-child sums match exactly, but ComCat is a maintained catalogue and the run is not an atomic snapshot across all 312 requests. Preserve per-request timestamps and avoid interpreting the entire table as though all cells were queried at one identical instant.

## 8. Source package member SHA-256 values

| File | SHA-256 |
|---|---|
| `reconnaissance_count_results_v003.csv` | `625a60b34feac97da79b21f2e9b9e69f62c1a873e658a1d3596dfa3c9d7863b8` |
| `reconnaissance_request_log_v003.jsonl` | `0547a264baa350fafcaf8cb7a2f94a92ec7274f5b082456c3ca82e6c34919fe8` |
| `run_metadata_v003.json` | `5dbc1ea6160c312348cdfe664f91ea8df44defd631a1e303403e20f6592a9940` |
| `reconnaissance_logical_cell_summary_v003.csv` | `c08aca1a64bdb13f658ba2b851751fde0e86b0cdba7274905035bbcf7ce525d7` |
| `reconnaissance_summary_v003.json` | `6a82d1fa3d4255a5d82e573d1fc7a159da4b5b6c1786194e7d55ba54635f702c` |
| `STAGE1C1_COUNT_RECONNAISSANCE_v003.md` | `486ff06eb6db67326fcc40a1c301bb916f3bb4ff4e73dafadf4e905ee3796583` |

## 9. Audit conclusion

**The count values, request/response provenance, URL/parameter correspondence, logical-cell aggregation, parent-child reconciliation and query-safety checks pass.** The two documentation caveats above (request-start pacing observability and six `subdivision_resolution` labels) should be carried into the project notes and corrected in a future script version. They do not invalidate the count totals or the exact interval/count reconciliations.

Stage 1C.1 v003 is suitable to retain as a completed count-only reconnaissance run with this independent audit addendum. It is not by itself authorization to download a supporting event catalogue. Before event retrieval, freeze a separate acquisition plan with exact query windows, fresh count checks, a request-start pacing log, raw-response/sidecar schema and manifest policy.

No event records were downloaded by this run. The frozen 1,186-row target catalogue was not modified. No sequence IDs or event roles were assigned.
