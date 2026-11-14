# Stage 1C.3 - Frozen Regional & Tectonic-Depth Crosswalk (v001)

**Status:** Frozen Stage 1C.3 baseline crosswalk for downstream LAIC-GUARD regional stratification.  
**Baseline Catalogue:** `metadata/event_catalogue_v002.csv` (1,186 unique events, SHA-256 `0e20c3ef...315`)  
**Source Evidence:** Stage 1C.2.6 Batches 01-13 and `consolidated_evidence_review_v001` (641 adjudicated events including 351/351 queue events + 545 reconciled outside-pilot events)  
**Prepared:** 2026-11-14  

## 1. Structural Design Principles

1. **Strict Separation of Physical Regimes:** Shallow margin/interface events (<70 km), intermediate intraslab events (70-299 km), deep-focus slab events (>=300 km), outer-rise/trench-slope events, oceanic ridge/transform events, and crustal strike-slip faults are isolated into distinct strata so deep slab projections never contaminate shallow overriding-plate regions.
2. **Correction of 2D Polygon Artifacts:** Preserves all Stage 1C.2 reassignments—including the 13 Moro Gulf deep-slab events (523-641 km) transferred from `SUNDA_JAVA` to `EASTERN_INDONESIA`, the 8 deep Izu-Bonin slab events transferred out of `MARIANA`, the 2 Ryukyu outer-rise events transferred out of `PHILIPPINE_MOBILE_BELT`, and the 2012 Wharton Basin M8.6/M8.2 doublet unified under `SUNDA_SUMATRA_JAVA` outer-rise.
3. **Explicit Caveat Retention:** Downstream statistical analyses must filter on `stage1c2_disposition_v001` and `stage1c2_confidence_v001` when restricting to moment-tensor-verified megathrust interface ruptures versus provisional depth/polygon strata.
