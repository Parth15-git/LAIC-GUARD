# LAIC-GUARD Stage 1B.2 — Associate/Disassociate Product Review

## Scope

Reviewed 355 ComCat detail GeoJSON records and 1186 rows from `event_catalogue_v002.csv`. Extracted every `associate` and `disassociate` product directly from each raw detail response. This is a metadata/identity review only; no earthquake event was merged, split, removed, or assigned a sequence.

## Findings

- Disassociate product objects: **25**
- Distinct ComCat detail events containing them: **18**
- Unique undirected source/code endpoint pairs: **23**
- Both endpoint tokens present in the flattened detail `properties.ids` field: **22 / 25**
- Exact same-pair `associate` product also present in the retrieved detail set: **1 product record(s)**
- Disassociate products with inline comment: **0**
- Associate products in these 18 events: **60**, with **5** inline comments
- Disassociate products carrying `original-signature`: **2**
- Status counts: `{"UPDATE": 25}`

## Key interpretation

USGS PDL documents `disassociate` as a directive to prevent automatic association between two events. Its indexer-processing documentation splits grouped events into Sub-Events by Event ID, then evaluates their pairwise relationship. In that evaluation, a disassociate product is checked before an associate product; when either Sub-Event has a disassociate product for the other, the pair is considered **not associated**. The documentation also notes that the associate/disassociate checks currently use the other Sub-Event's preferred Event ID. Therefore an exact-pair conflict must be evaluated against the preferred Event IDs, not resolved by simply choosing the later timestamp.

For one pair, `us7000lfxx` ↔ `at00s53wgj`, both an `associate` and a `disassociate` product are present. The associate product is later and carries the inline comment `outside automatic association window`; the disassociate product is also `UPDATE`, carries no inline comment, and the counterpart token is not in the current `us7000lfxx` detail ID list. USGS PDL's disassociate product documentation explicitly states that when both product types exist for the same pair, **disassociate takes precedence**. The indexer guide gives the same ordering. We therefore have a documented PDL rule, but must still retrieve the counterpart detail to confirm that `at00s53wgj` is the preferred Event ID used by the indexer check.

For 22 disassociate product records, both endpoint tokens also occur in the corresponding detail response's `properties.ids` string. This co-presence in the flattened `ids` field is not conclusive because the indexer can split a grouped event into separate Sub-Events by Event ID. Do not interpret the comma-delimited `ids` field alone as proof that the pair should be merged.

Three disassociate records have a counterpart endpoint absent from the current detail ID list and absent as a direct `event_id` in the scoped candidate catalogue. This does **not** prove the counterpart event does not exist: the project catalogue is filtered to magnitude >= 6.5 and uses preferred event IDs. Retrieve or document the counterpart record before closing those cases.

## Additional review notes

- Four disassociate-bearing events contain no `associate` product in their own detail response: `usp000ba6g`, `usp000ba6m`, `usp000ccg3`, and `usp000d06s`.
- Two endpoint pairs have two separate disassociate product objects, one in each endpoint order: `duputel200509090726a` ↔ `iscgem7519857` and `duputel200604301917a` ↔ `iscgem10698202`. They count as four product records but two unique undirected pairs.
- Five inline comments were found across the 60 associate products in these 18 event details. The complete associate counterevidence is preserved in `associate_counterevidence_v001.csv`. The only exact-pair associate/disassociate match is `us7000lfxx` ↔ `at00s53wgj`.
- `original-signature` is present in two disassociate products; this audit records presence only and does not cryptographically verify the signatures.

## Recommended decisions

All rows remain `PENDING_MANUAL_ADJUDICATION`. In particular:

1. Review the exact-pair associate/disassociate conflict for `us7000lfxx` ↔ `at00s53wgj`. The disassociate rule is evaluated first by the documented associator; the counterpart's preferred Event ID still needs confirmation.
2. Review the 22 flattened-`ids` co-presence cases against the ComCat Event Timeline and each endpoint's preferred Event ID.
3. Retrieve or document counterpart details for the three endpoints not represented in this detail set: `ci10169070`, `at00s53wgj`, and `usc0007dax`.
4. Review the two reversed-direction duplicate pair groups: `duputel200509090726a` ↔ `iscgem7519857` and `duputel200604301917a` ↔ `iscgem10698202`.
5. Keep original event IDs and catalogue rows unchanged until source-level decisions are documented.

## Reproducibility

Run from the repository root:

```powershell
python .\scripts\07_audit_disassociate_adjudication.py
```

Outputs are written to `reports/stage1b/adjudication/`.

## Official documentation consulted

- Product types: https://earthquake.usgs.gov/data/products/
- Disassociate product (explicit precedence note): https://ghsc.code-pages.usgs.gov/users/zcloutet/pdl/userguide/products/known-types/disassociate.html
- Associate product: https://ghsc.code-pages.usgs.gov/hazdev/pdl/userguide-3.5.5/products/known-types/associate.html
- Indexer processing: https://usgs.github.io/pdl/indexer.html

