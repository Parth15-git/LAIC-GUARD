# Stage 1C.2.6 - Izu-Bonin Evidence Review, Batch 04 (v001)

**Status:** Provisional evidence review; not a regional freeze or approved crosswalk.  
**Target candidate family:** `IZU_BONIN_ARC_REVIEW` plus 8 deep-slab reassignments from `PHILIPPINE_MOBILE_BELT_REVIEW` and 1 Pacific outer-rise event (`usp000hr97`)  
**Review universe:** 14 catalogue events, 2000-2024  
**Prepared:** 2026-11-14  

## 1. Key Audit Findings Resolved in Batch 04

1. **Queue omission of `us20002ki3` (2015-05-30, M7.8, 664.0 km):** Tagged `IZU_BONIN_ARC_REVIEW` in `gis_review_v001` (accounting for the 5-event count in `regional_adjudication_matrix_v001.csv`) but omitted from the 351-row `event_adjudication_queue_v001.csv`.
2. **Surface-projection mis-tagging of 8 deep Izu-Bonin slab events (292-496 km):** Because the subducted Pacific slab dips steeply westward beneath the arc, epicenters at 137.9E-140.1E project inside the Hasterok `Philippine` subplate polygon and were routed to `PHILIPPINE_MOBILE_BELT_REVIEW`. All 8 are flagged `MOVE_TO_SEPARATE_CANDIDATE` into the Izu-Bonin deep-slab stratum.
3. **Outer-rise Bonin M7.4 event (`usp000hr97`, 2010-12-21, 14.0 km):** Epicenter at 26.901N, 143.698E lies immediately east of the Bonin Trench on the Pacific plate (in_queue = False, blank candidate tag) and must be captured in the Izu-Bonin trench/outer-rise system rather than left unassigned.
