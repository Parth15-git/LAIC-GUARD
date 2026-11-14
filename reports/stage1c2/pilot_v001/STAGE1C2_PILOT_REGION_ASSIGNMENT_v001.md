# LAIC-GUARD Stage 1C.2 — Pilot Region Assignment v001

**Status:** DRAFT FOR REVIEW  
**Input rows:** 1186  
**Input SHA-256:** `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`  
**Network calls:** none  
**Supporting event records downloaded:** 0

## Purpose and scope

This artifact assigns the frozen Stage 1A v002 target events to mutually exclusive bookkeeping strata for a candidate four-domain pilot. It does not define tectonic regions, estimate magnitude completeness, change the source catalogue, or assign sequence labels.

The four candidate boxes are retained exactly as used in Stage 1C.1. They are exploratory operational rectangles, not tectonic polygons. The Himalaya-Tibet and Sunda-Indonesia rectangles intersect; the exact intersection is preserved as a separate review stratum.

## Exclusive target assignment

| Assignment | Target events |
|---|---:|
| HIMALAYA_TIBET_CORE | 35 |
| JAPAN_KURIL | 138 |
| SUNDA_INDONESIA_CORE | 239 |
| ANDES | 127 |
| OVERLAP_REVIEW_HIMALAYA_SUNDA | 7 |
| OUTSIDE_PILOT | 640 |
| **Total** | **1186** |

## Original candidate-box memberships

| Box | Memberships |
|---|---:|
| HIMALAYA_TIBET | 42 |
| JAPAN_KURIL | 138 |
| SUNDA_INDONESIA | 246 |
| ANDES | 127 |

The four box-membership totals are not additive. The seven events in the Himalaya-Tibet/Sunda-Indonesia intersection are counted in both original boxes but assigned once to the overlap-review stratum.

## Period distribution

| Assignment | 2000–2009 | 2010–2019 | 2020–2025 |
|---|---:|---:|---:|
| HIMALAYA_TIBET_CORE | 11 | 17 | 7 |
| JAPAN_KURIL | 62 | 48 | 28 |
| SUNDA_INDONESIA_CORE | 110 | 84 | 45 |
| ANDES | 38 | 68 | 21 |
| OVERLAP_REVIEW_HIMALAYA_SUNDA | 0 | 5 | 2 |
| OUTSIDE_PILOT | 234 | 267 | 139 |

The 2020–2025 interval is six calendar years and is not comparable to a complete ten-year period without exposure-time normalization. These are target-event counts, not supporting-catalogue completeness estimates.

## Assignment rule

1. Assign an event to `OVERLAP_REVIEW_HIMALAYA_SUNDA` when it falls inside both candidate boxes.
2. Assign Himalaya-only and Sunda-only events to their respective core strata.
3. Assign Japan-Kuril and Andes events to their respective strata.
4. Assign all remaining target events to `OUTSIDE_PILOT`.

This rule is deterministic and mutually exclusive. It is a geographic bookkeeping rule only; it does not adjudicate tectonic setting or event identity.

## Next gate

Review this assignment and approve or amend the pilot-window specification. Only after that should a separate Stage 1C.2 count-only acquisition plan be frozen. Proposed lower preferred-magnitude thresholds are exploratory planning values, not Mw thresholds or chosen analytical cutoffs. No event retrieval is authorized by this artifact.

## Reproducibility

Run `13_build_stage1c2_pilot_crosswalk_v001.py` from the repository root with the frozen input path. The script verifies the SHA-256 and expected row count before producing outputs. It performs no network access.
