# LAIC-GUARD Stage 1B.2B — ComCat Relationship Evidence Ledger

## Scope and input integrity

This is a review-only, reproducible audit of the 358 retrieved ComCat event-detail GeoJSON records and the v002 candidate catalogue (1186 rows). Each detail file was matched to exactly one manifest row and its SHA-256 and byte size were verified before the audit ran.

- Detail GeoJSON records reviewed: **358**
- Candidate catalogue rows: **1186**
- Associate product occurrences: **583**
- Disassociate product occurrences: **25**
- Unique undirected endpoint pairs containing a disassociate product: **23**
- Pair scope classifications: `{"CROSS_DETAIL_PAIR": 3, "WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR": 20}`

## Key finding

The 23 disassociate endpoint pairs are not 23 independent pairs of catalogue earthquakes. The endpoint-token alias graph maps **20** pairs to the same retrieved detail feature and **3** pairs across distinct retrieved detail features. A same-feature mapping is a scope/alias finding; it is not a physical-earthquake interpretation. Of the three cross-detail pairs, one matches both preferred IDs; the other two require alias-graph review.

## Cross-detail relationship cases

- `at00s53wgj <-> us7000lfxx`: endpoint detail mappings `['at00s53wgj']` / `['us7000lfxx']`; mapped preferred pair(s): `[['at00s53wgj', 'us7000lfxx']]`; PDL assessment: **NOT_ASSOCIATED_DISASSOCIATE_PRECEDENCE**. Active associate/alias path: `[{'node': 'at00s53wgj'}, {'from': 'at00s53wgj', 'to': 'us7000lfxx', 'edge_type': 'ACTIVE_ASSOCIATE_PRODUCT', 'source_detail_event_id': 'us7000lfxx', 'product_id': 'urn:usgs-product:admin:associate:us7000lfxx_at00s53wgj:1701793192870', 'update_time_utc': '2023-12-05T16:19:52.870Z', 'inline_comment': 'outside automatic association window'}]`. Manual review priority: HIGH_MANUAL_REVIEW_PRIORITY.
- `atlas20111227152156 <-> usc0007dax`: endpoint detail mappings `['usp000jcq2']` / `['usc0007dax']`; mapped preferred pair(s): `[['usc0007dax', 'usp000jcq2']]`; PDL assessment: **ASSOCIATED_BY_EXPLICIT_ASSOCIATE**. Active associate/alias path: `[{'node': 'atlas20111227152156'}, {'from': 'atlas20111227152156', 'to': 'usp000jcq2', 'edge_type': 'ACTIVE_ASSOCIATE_PRODUCT', 'source_detail_event_id': 'usp000jcq2', 'product_id': 'urn:usgs-product:admin:associate:atlas20111227152156_usp000jcq2:1508192984388', 'update_time_utc': '2017-10-16T22:29:44.388Z', 'inline_comment': 'multiple event ids from same source'}, {'from': 'usp000jcq2', 'to': 'usc0007dax', 'edge_type': 'ACTIVE_ASSOCIATE_PRODUCT', 'source_detail_event_id': 'usc0007dax', 'product_id': 'urn:usgs-product:admin:associate:usc0007dax_usp000jcq2:1508192984415', 'update_time_utc': '2017-10-16T22:29:44.415Z', 'inline_comment': 'multiple event ids from same source'}]`. Manual review priority: HIGH_MANUAL_REVIEW_PRIORITY.
- `ci10169070 <-> duputel201004042240a`: endpoint detail mappings `['ci10169070']` / `['ci14607652']`; mapped preferred pair(s): `[['ci10169070', 'ci14607652']]`; PDL assessment: **NO_EXPLICIT_PREFERRED_ID_PAIR_PRODUCT_FOUND**. Active associate/alias path: `[{'node': 'ci10169070'}, {'from': 'ci10169070', 'to': 'atlas20100404224000', 'edge_type': 'DETAIL_IDS_MEMBERSHIP', 'source_detail_event_id': 'ci10169070', 'product_id': '', 'update_time_utc': '', 'inline_comment': ''}, {'from': 'atlas20100404224000', 'to': 'duputel201004042240a', 'edge_type': 'ACTIVE_ASSOCIATE_PRODUCT', 'source_detail_event_id': 'ci10169070', 'product_id': 'urn:usgs-product:admin:associate:atlas20100404224000_duputel201004042240a:1615334992905', 'update_time_utc': '2021-03-10T00:09:52.905Z', 'inline_comment': ''}]`. Manual review priority: HIGH_MANUAL_REVIEW_PRIORITY.

## Focused interpretation of the three cross-detail cases

- **`us7000lfxx` ↔ `at00s53wgj`:** both endpoint tokens are preferred detail IDs. The exact preferred-ID pair has active associate and disassociate `UPDATE` products; the PDL indexer rule therefore returns NOT ASSOCIATED for this pair. This is an indexer relationship instruction only; it does not prove physical independence.
- **`atlas20111227152156` ↔ `usc0007dax`:** the first endpoint resolves as an alias inside `usp000jcq2`; the second is the preferred ID of `usc0007dax`. The mapped preferred-ID pair `usp000jcq2` ↔ `usc0007dax` has active associate products, while the disassociate is for the alias pair. Keep the alias-graph/physical-identity interpretation open; do not count the counterpart as a second catalogue event based on this ledger alone.
- **`ci10169070` ↔ `duputel201004042240a`:** the endpoints map to separate retrieved detail records, but `duputel201004042240a` is an alias within `ci14607652`; an active associate/alias-membership path connects the endpoint tokens through the retrieved records. No direct preferred-ID-pair override is found for the mapped pair. This remains a manual alias-graph review, not an automatic separate-identity decision.

## Product-state method

1. Every `associate` and `disassociate` product occurrence is retained in `comcat_relationship_product_records_v001.csv`.
2. Product versions are grouped by `(product type, source, code)`; the greatest `updateTime` is treated as the current version. `DELETE` supersedes earlier versions; `UPDATE` is active.
3. Endpoint pairs are normalized as undirected `(source + sourcecode)` tokens.
4. Each endpoint token is mapped against every retrieved detail feature's `properties.ids` plus the feature's top-level `id`.
5. For distinct mapped detail features, the ledger separately tests whether a relationship product exists between the two **preferred detail IDs**. Alias-token products are not silently treated as preferred-ID pair products.
6. An additional graph path is computed using detail-ID membership edges and latest active associate-product edges. This path is evidence of alias/association connectivity, not an identity decision.
7. The PDL indexer processing documentation states that if either event has a disassociate product for the other, the events are not associated; the associate check is considered after disassociate. The documentation also says these product checks currently inspect the other event's preferred Event ID. Thus a product on an alias edge cannot automatically be promoted to a preferred-ID pair decision.

## Decision boundaries

- This ledger distinguishes **ComCat product instruction**, **preferred-ID mapping**, **alias-graph interpretation**, and **physical earthquake identity**.
- A disassociate instruction does not establish that two origins are physically unrelated or tectonically independent.
- A product-level associate does not, by itself, establish the scientific sequence membership of two events.
- No earthquake was merged, split, removed, re-IDed, or assigned a `sequence_id`.
- The candidate catalogue and raw ComCat downloads were not modified.
- Any previously supplied three-row `CONFIRMED_SEPARATE_COMCAT_EVENT_IDENTITIES` CSV is imported only as a legacy comparison. Its decision labels are not adopted as ground truth; see `legacy_decision_scope_warning` in the pair ledger.

## Files produced

- `comcat_relationship_product_records_v001.csv` — all extracted product records and version flags.
- `comcat_relationship_pair_ledger_v001.csv` — one row per each of the 23 unique undirected disassociate endpoint pairs.
- `comcat_relationship_input_integrity_v001.csv` — input file hashes and manifest matches.
- `comcat_relationship_summary_v001.json` — machine-readable counts and policy.

## Official USGS/PDL references

- Indexer processing and pairwise association logic: https://usgs.github.io/pdl/indexer.html
- Disassociate product semantics and status: https://ghsc.code-pages.usgs.gov/users/bhawthorne/pdl/userguide-2.9.1/products/disassociate.html
- Associate product semantics and status: https://ghsc.code-pages.usgs.gov/hazdev/pdl/userguide-3.5.5/products/known-types/associate.html

## Reproduce

Run from the repository root:

```powershell
python .\scripts\10_build_comcat_relationship_ledger.py
```

Expected baseline: 358 detail GeoJSON files, 1,186 catalogue rows, 23 unique disassociate endpoint pairs, and all 358 detail hashes verified against `metadata/data_manifest.csv`.
