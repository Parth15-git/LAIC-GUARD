# Stage 1C.2.6 — Myanmar overlap review batch 01

**Status:** reviewer worksheet only. No event disposition, mechanism, fault attribution, or sequence role is approved by this file.

## Scope

This batch isolates the seven target-catalogue events in the geometric intersection of the old Himalaya–Tibet and Sunda–Indonesia pilot rectangles. All seven are tagged to the provisional `BURMA_SHAN_THAI_COMPLEX_REVIEW` candidate family, with Hasterok subplate labels `Burma` or `Shan-Thai` and PB2002 orogen label `Persia-Tibet-Burma`. These are geographic overlays, not proof of a specific causative fault or source mechanism.

## Recommended interim handling

Use `UNRESOLVED_RETAIN` pending event-specific review. Retain the complex-system candidate as a hypothesis, but do not force any of the seven into a Himalayan collision source, Sunda megathrust source, Sagaing fault source, or intraslab category solely from nearest-boundary labels or depth.

## Event-specific cautions

- Three records have depths greater than 50 km (55.0, 82.0 and 136.0 km). Their source type needs comparison with an authoritative slab geometry and event mechanism; depth alone is insufficient.
- `us7000pn9s` and `us7000pn9z` are on 2025-03-28, 11 minutes 12.062 seconds apart, and approximately 35 km apart by epicentral coordinates. Keep both catalogue records. This worksheet does not assign a mainshock/aftershock or sequence relationship.
- `nearest_boundary_type` and `nearest_boundary_distance_km` are contextual measurements only. They are not causative-fault determinations.

## Allowed reviewer dispositions

Use the disposition vocabulary already defined in `STAGE1C2_REGIONAL_ADJUDICATION_FRAMEWORK_v001.md`: `KEEP_IN_CANDIDATE_DOMAIN`, `KEEP_IN_COMPLEX_UMBRELLA`, `MOVE_TO_SEPARATE_CANDIDATE`, `BOUNDARY_OR_JUNCTION_HOLD`, `UNRESOLVED_RETAIN`, `NOT_IN_THIS_CANDIDATE`. A disposition must have a rationale and a specific source reference. Do not use `NOT_IN_THIS_CANDIDATE` to delete an event from the frozen target catalogue.

## Required review evidence

1. Event-specific moment tensor or focal mechanism product, if available.
2. Hypocentre depth relative to a published Indo-Burman / Burma slab or collision geometry.
3. Regional active-fault, trench, or orogen map that establishes the proposed structural setting.
4. Exact source title, version/date, URL/DOI, and the event attribute that the source supports.

If any evidence is absent, leave the disposition `UNRESOLVED_RETAIN`. Do not infer source type from the place-name string.

## Files

- `analysis/batch_01_myanmar_overlap_review_v001.csv`: full source fields plus blank reviewer fields and review notes.
- `analysis/batch_01_depth_and_pair_review_notes_v001.csv`: compact depth and 2025 close-pair review table.
- `REFERENCES.md`: references inherited from the regional adjudication framework.
- `SHA256SUMS.csv`: hashes of package files, excluding this manifest.
