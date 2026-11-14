# LAIC-GUARD Stage 1C.2.6 — Regional adjudication framework v001

**Status: adjudication framework only. No final region or exclusive event assignment is approved.**

## 1. What passed

The local GIS package verification reported **36 manifest entries and 0 failed checks**. The GIS package report records 1,186 source events and 1,186 event-level GIS rows. The event-level priority review table contains 351 unique events across 478 high/medium-priority flag records; the long-form edge-case ledger has 1,447 flag rows across 976 unique flagged events. Flags overlap and must not be summed as unique events.

This framework was derived from the Stage 1C.2.5 event-level GIS review, priority edge-case register, pilot-box family composition and published tectonic references listed in `REFERENCES.md`.

## 2. Main methodological rule

A nearest boundary, a tectonic plate/subplate label, or a geological province label is **not**, by itself, proof of the earthquake's causative fault, slab, or mechanism. The target catalogue has epicentral coordinates, depth and preferred magnitude/type, but this review does not yet have a consistently verified focal mechanism, rupture plane, slab-relative hypocentre classification, or a validated source-specific polygon for every event.

Therefore:

- Keep original catalogue fields and original pilot assignments unchanged.
- Keep candidate-domain tags as hypotheses, not exclusive assignments.
- Do not infer mechanism from nearest-boundary class alone.
- Do not use outside-pilot or untagged events as a tectonically inactive/control population.
- Do not freeze a region from a broad rectangle or a plate polygon alone.
- Do not download supporting event records or label sequences until the region protocol and Stage 1C.0 document-control issue have been resolved.

## 3. Adjudication decisions supported by current evidence

The companion `regional_adjudication_matrix_v001.csv` states the recommended interim treatment, evidence and required validation for each candidate domain. The central outcomes are:

1. **Himalaya–Tibet/Pamir and Burma–Shan-Thai must not be treated as one simple rectangle.** Published Myanmar work distinguishes Indo-Burman subduction/collision, the dextral Sagaing system, and left-lateral faulting around the Shan Plateau and adjacent regions. The seven Myanmar overlap events stay in a review group while the 13 additional Persia–Tibet–Burma-orogen events outside the old boxes are inspected.
2. **Kuril–Kamchatka must be separated from Bering/Aleutian and from Ryukyu/IBM arcs.** USGS describes the Kuril–Kamchatka arc as extending from Hokkaido to the Aleutian junction; the Aleutian arc itself has distinct segments, and the Bering Sea margin is not automatically the arc.
3. **Sumatra and Java should be tested as separate Sunda-arc segments.** Published work distinguishes oblique, strike-slip-partitioned subduction beneath Sumatra from near-normal subduction beneath Java. The eastern Indonesian/Banda and Molucca systems are tectonically more complex and should not be pooled automatically with either.
4. **The Philippine Mobile Belt is a complex boundary zone**, bounded by subduction systems of opposing polarity and containing collision and strike-slip structures. PB2002 orogen membership and Hasterok subplate-family tags are different source classifications (37 vs 46 catalogue events in this audit) and should not be substituted for one another.
5. **The Andes rectangle should be replaced with a documented along-strike segmentation.** Published syntheses describe strong along-strike variation in Nazca slab dip, including flat-slab and steeply dipping segments. A South American plate polygon is not an Andes study-region polygon.
6. **Outside-pilot and untagged events are retained.** The 584 events without a candidate family and the 81 outside-pilot events with a candidate-domain tag show that the pilot rectangle union is not a complete tectonic inventory.

## 4. Required event-level evidence before region freeze

For each proposed study region, the researcher must document:

- authoritative polygon/line source, version, reference date, and exact geometry;
- tectonic process and source type included (e.g., interplate thrust, intraslab, crustal collision, transform, extensional);
- source-specific evidence for event inclusion (focal mechanism / moment tensor, slab model and depth, mapped active fault, or documented seismotectonic polygon);
- explicit boundary and junction treatment;
- event counts by time period, magnitude type and depth band;
- catalog completeness assessment at the proposed regional scale;
- minimum sample-size/power rationale for the planned sequence analysis;
- sensitivity analysis to alternative plausible boundaries;
- control-population definition separate from the target regions.

If source type cannot be independently identified, retain a regional umbrella label and do not claim a specific fault/slab population.

## 5. Reviewer workflow

Use `analysis/event_adjudication_queue_v001.csv` for event-level review. The blank reviewer columns are intentionally left for human decisions. Permitted interim dispositions are:

- `KEEP_IN_CANDIDATE_DOMAIN` — direct source-backed membership;
- `KEEP_IN_COMPLEX_UMBRELLA` — membership only at the broader complex-system level;
- `MOVE_TO_SEPARATE_CANDIDATE` — evidence supports a different domain;
- `BOUNDARY_OR_JUNCTION_HOLD` — event is near a domain junction or competing polygons;
- `UNRESOLVED_RETAIN` — insufficient evidence; retain without exclusive assignment;
- `NOT_IN_THIS_CANDIDATE` — evidence supports non-membership in the candidate under review (not catalogue deletion).

Each nonblank disposition must have a rationale and a source reference. A reviewer must not decide only from the nearest boundary distance or a geographic place-name string.

## 6. Stop/go gate

**Current decision: NO-GO for region freeze, supporting-event acquisition, completeness estimation on any frozen regional set, and sequence assignment.**

GO only after:

1. the research estimand is declared (tectonic-system study vs source-mechanism-specific study);
2. domain polygons and boundary/junction rules are source-backed and versioned;
3. event review dispositions are complete for priority cases;
4. event-level assignments are reproducible and mutually exclusive or explicitly multi-label by design;
5. the Stage 1C.0 protocol approval-state inconsistency has a versioned correction/addendum;
6. completeness and sampling adequacy are assessed before nearest-neighbour sequence reconstruction.

## 7. Included files

- `analysis/regional_adjudication_matrix_v001.csv`: evidence and provisional treatment by tectonic domain.
- `analysis/event_adjudication_queue_v001.csv`: 351 unique priority-flagged events, one row per event, with blank human-review fields.
- `analysis/domain_freeze_checklist_v001.csv`: per-domain freeze criteria for later sign-off.
- `REFERENCES.md`: sources and URLs supporting source-derived tectonic distinctions.
- `SHA256SUMS.csv`: integrity manifest for package contents (excluding the manifest itself).
