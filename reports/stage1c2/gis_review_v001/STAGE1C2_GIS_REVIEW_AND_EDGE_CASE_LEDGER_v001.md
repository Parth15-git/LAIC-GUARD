# LAIC-GUARD Stage 1C.2.5 — GIS review and edge-case ledger v001

**Status: review package only. No region has been frozen or approved.**

## 1. Integrity

- Frozen catalogue: **1186 rows / 1186 unique IDs**.
- Frozen catalogue SHA-256: `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`.
- Candidate crosswalk: **1186 rows / 1186 unique IDs**.
- Catalogue-to-crosswalk shared source fields checked: **no mismatches**.
- Event-level GIS review rows: **1186**.
- Events carrying one or more review flags: **976** (flags may be low-priority source qualifiers; this is not a rejection count).
- Long-form event-flag ledger rows: **1447**.
- Hasterok source features: **280 plate/subplate polygons, 914 geological provinces, 571 boundary records**.
- PB2002 plate features: **54**.
- PB2002 orogen features: **13**.

## 2. Priority case counts

| Review topic | Events |
|---|---:|
| Original geometric Himalaya/Sunda overlap | 7 |
| Persia–Tibet–Burma orogen outside all four boxes | 13 |
| Persia–Tibet–Burma orogen inside Sunda box | 1 |
| Bering Sea Hasterok subplate | 37 |
| PB2002 western Aleutians orogen | 8 |
| Ryukyu Hasterok subplate | 11 |
| PB2002 Philippines orogen | 37 |
| Philippine Mobile Belt candidate family | 46 |
| New Guinea/eastern Indonesia candidate family | 27 |
| Mariana arc candidate family | 16 |
| Sunda box events not tagged as Sunda-arc candidates | 171 |
| Japan–Kuril box events not tagged as Kuril–Kamchatka candidates | 59 |
| Andes box events in non-Andes/adjacent review families | 46 |
| Himalaya–Tibet box events outside the primary collision-belt family | 2 |
| Outside-pilot events with a candidate-domain tag | 81 |
| Events without a pre-registered candidate family | 584 |

Counts are per flag and categories overlap. Do not sum them to obtain a unique-event total.

## 3. Interpretation

### Myanmar / Persia–Tibet–Burma
The seven geometric overlap events remain in `OVERLAP_REVIEW_HIMALAYA_SUNDA`. The PB2002 Persia–Tibet–Burma orogen contains 13 target events outside all original rectangles and 1 event inside the Sunda rectangle. The old rectangle edges therefore do not delimit the PB2002 orogen.

### Japan–Kuril / Bering / Ryukyu
The Bering Sea subplate has 37 events split across the old Japan–Kuril box and outside-pilot area; PB2002 western-Aleutians members are separately flagged. Ryukyu events are split across Japan–Kuril, Sunda and outside-pilot assignments. These units should not be pooled solely by the old boxes.

### Sunda / Philippines / Molucca / New Guinea
The Sunda rectangle contains 171 events not tagged as the provisional Sunda-arc candidate family. PB2002's Philippines orogen has 37 catalogue events in the Sunda rectangle; the Hasterok-based Philippine Mobile Belt family contains 46 events across the full catalogue. New Guinea/eastern Indonesia and Mariana candidates are separately flagged.

### Andes and adjacent domains
The Andes rectangle contains 46 events tagged to broad South American, Central America/Caribbean, Nazca, Cocos or Scotia review families. These should be reviewed before the Andes region is frozen.

### Unassigned/outside pilot
There are 584 events without a pre-registered candidate family, while 81 outside-pilot events have candidate-domain tags. The outside-pilot set is not a control group or tectonically inactive population.

## 4. Map layers and symbols

- Event marker colour: original pilot assignment v001.
- Black-ring marker: event has one or more priority edge-case flags.
- Thin gray outlines: Hasterok tectonic plate/subplate polygon outlines.
- Pale dotted outlines: Hasterok geological-province outlines.
- Blue dash-dot outlines: PB2002 plate polygons.
- Red dashed outlines: PB2002 orogens.
- Boundary line colours: Hasterok `type` field (see legend).
- Black dashed rectangles: original exploratory pilot windows.

The global view skips line segments that would spuriously connect across the antimeridian. The Bering/Aleutian panel uses 0–360° longitude.

## 5. Decisions not made

This package does not assign exclusive final region membership, infer causative faults, define control regions, or choose distance thresholds. The input source units are evidence layers, not validated LAIC study populations. No supporting earthquake records were downloaded; no sequence labels were assigned. Before freezing regions, the research objective must clarify whether the regional analysis concerns collision, subduction-interface, intraslab, strike-slip, or mixed tectonic settings.

## 6. Files

- `analysis/event_level_gis_review_v001.csv`: all 1,186 events, one row per event, plus review flags.
- `analysis/edge_case_ledger_v001.csv`: long-form event-by-flag ledger.
- `analysis/edge_case_flag_summary_v001.csv`: counts per flag; categories overlap.
- `analysis/priority_edge_case_register_v001.csv`: event details for the named review topics.
- `analysis/pilot_box_candidate_family_composition_v001.csv`: provisional family mixture for each original rectangle.
- `maps/global_catalogue_overview_v001.png/.pdf`: global point/line overview.
- `maps/regional_gis_review_v001.png/.pdf`: six detailed regional GIS panels.
- `inputs/`: frozen analysis inputs and source geospatial files needed to reproduce the review.
- `scripts/`: reproducible builder.

**Decision:** retain Stage 1C.2.4 proposal v001 unchanged. Use this package for human review. It does not authorize a final region freeze or supporting-event acquisition.

## References

- Bird, P. (2003). An updated digital model of plate boundaries. *Geochemistry, Geophysics, Geosystems*, 4, 1027. https://doi.org/10.1029/2001GC000252.
- Hasterok, D., Halpin, J. A., Collins, A. S., Hand, M., Kreemer, C., Gard, M. G., & Glorie, S. (2022). New maps of global geologic provinces and tectonic plates. *Earth-Science Reviews*, 231, 104069. https://doi.org/10.1016/j.earscirev.2022.104069. Data record: https://zenodo.org/records/5093930.
