# LAIC-GUARD Stage 1B.2C — ComCat sub-event-pair adjudication

## Scope and integrity

Review-only interpretation of Stage 1B.2B product ledgers; not physical-earthquake identity, sequence assignment, or a catalogue edit.

- Pair rows / unique keys: 23 / 23
- Product rows / unique product IDs: 608 / 608
- Raw product-property endpoint checks: 608/608 matched
- Associate occurrences: 583 (573 latest; 10 superseded)
- Disassociate occurrences: 25; all latest active UPDATE versions
- Same-detail / cross-detail pairs: 20 / 3
- Exact endpoint pairs with active associate: 1
- Pairs with active associate edges in alias paths: 17
- Pairs with multiple disassociate product occurrences: 2

## Pair-level summary

| Endpoint pair | Scope | Active disassociate | Exact-pair active associate | Alias-path associate edges |
|---|---|---:|---:|---:|
| `ak007g7y8wbv <-> choy20071219093027` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `at00s53wgj <-> us7000lfxx` | `CROSS_DETAIL_PAIR` | 1 | 1 | 1 |
| `atlas20111227152156 <-> usc0007dax` | `CROSS_DETAIL_PAIR` | 1 | 0 | 2 |
| `choy20020819110824 <-> iscgem3466220` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `choy20040715042714 <-> duputel071504c` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `choy20050119061136 <-> duputel200501190611a` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `choy20050119061136 <-> iscgem7462568` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `choy20060717081928 <-> duputel200607170819a` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `choy20060717081928 <-> iscgem10699442` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `choy20070928133859 <-> iscgem13204251` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `choy20071219093027 <-> iscgem13292574` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `choy20080303141114 <-> duputel200803031411a` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `choy20080303141114 <-> iscgem13479981` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `ci10169070 <-> duputel201004042240a` | `CROSS_DETAIL_PAIR` | 1 | 0 | 1 |
| `duputel081902a <-> iscgem4009018` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `duputel110204f <-> iscgem7429390` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `duputel110903f <-> gcmtc110903f` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 0 |
| `duputel200507020216a <-> iscgem7362817` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `duputel200509090726a <-> iscgem7519857` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 2 | 0 | 1 |
| `duputel200604301917a <-> iscgem10698202` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 2 | 0 | 1 |
| `duputel200605031527a <-> iscgem10698255` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `duputel200607170819a <-> iscgem10699442` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |
| `duputel200807050212a <-> iscgem12951048` | `WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR` | 1 | 0 | 1 |

## Interpretation and boundaries

Each of the 23 exact endpoint/sub-event pairs has a current active disassociate UPDATE. The direct instruction is not to associate that exact pair. Where an exact pair also has an active associate UPDATE, disassociate takes precedence. An associate edge elsewhere in an alias path does not cancel a direct disassociate for a different pair.

The 20 same-detail pairs are alias/sub-event pairs within one retrieved detail feature. This does not determine physical earthquake identity. The three cross-detail relationships are documented separately in the adjudication CSV. Aggregate preferred-event identity is not uniformly determined by these pairwise products. Physical identity and tectonic relationship are NOT ADJUDICATED. Sequence assignment is NOT PERFORMED. Catalogue v002 and raw data are NOT MODIFIED; no merge, split, removal, re-ID, or event addition is authorized.

## Cross-detail cases

- `at00s53wgj <-> us7000lfxx`: both endpoints are preferred IDs; exact pair has active associate and disassociate; disassociate takes precedence.
- `atlas20111227152156 <-> usc0007dax`: alias endpoint pair has active disassociate, while mapped preferred pair `usp000jcq2 <-> usc0007dax` has active associate. Retain both sub-event relationships.
- `ci10169070 <-> duputel201004042240a`: exact alias pair has active disassociate; indirect associate path through `atlas20100404224000`; no direct product found for preferred pair `ci10169070 <-> ci14607652`.

## Input SHA-256

- Pair ledger: `6a90edbf0e16bb495e6059c1037aa58def7c340218a37581184fc7ef478b6232`
- Product ledger: `e305a2734a42b0813628fe54773b6f869cfbf1f12c7784bc9a4e5ad507df6e6a`

Reproduce from repository root with `python .\scripts\11_adjudicate_comcat_subevent_pairs.py`.
