# LAIC-GUARD Stage 1C.2.4 — Provisional Regional Segmentation Proposal v001

**Status: PROVISIONAL. No study region is frozen or approved.** This work package proposes source-derived candidate subdomains for the next GIS review. It does not create new polygon boundaries, reassign earthquake sequences, or download additional earthquakes.

## 1. Scope and integrity

This proposal combines the frozen target catalogue, the Stage 1C.2 polygon overlay v001 and the Stage 1C.2.3 nearest-boundary distance audit v001. It covers all 1,186 events, retaining all 640 `OUTSIDE_PILOT` records and all seven original overlap-review records.

| Input / check | Result |
|---|---:|
| Frozen target catalogue | 1,186 rows / 1,186 unique IDs |
| Target catalogue SHA-256 | `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315` |
| Polygon overlay rows | 1,186 |
| Boundary-distance rows | 1,186 |
| Event-level proposal rows | 1,186 / 1,186 unique IDs |
| Events with a proposed Hasterok subplate review tag | 602 |
| Events without a pre-registered subplate tag | 584 |
| Original overlap-review records preserved | 7 |
| Outside-pilot records preserved | 640 |
| PB2002 orogen matches | 303 |

No network calls were made in this stage. No supporting event records were downloaded. No sequence labels were assigned.

## 2. Decision principle

Hasterok subplate labels, PB2002 plate names, PB2002 orogens, Hasterok geological provinces and nearest mapped-boundary records are **separate evidence layers**. The event-level output does not collapse these into one `tectonic_region` field. It creates only provisional review tags from exact Hasterok subplate labels, while PB2002 orogen membership remains an independent overlay.

This separation is essential. Bird (2003) states that the PB2002 plate model does not attempt to divide the Alps–Persia–Tibet mountain belt, the Philippine Islands, the Peruvian Andes and other complex zones into rigid plates; these are marked as orogens where the rigid-plate model is not expected to be accurate. Hasterok et al. (2022) adds a complementary set of plate, microplate, deformation-zone and geological-province polygons, but these too are source units—not pre-defined LAIC study populations.

## 3. Candidate segmentation recommendations

### A. Himalaya–Tibet, Pamir and Burma/Shan-Thai

The original Himalaya–Tibet rectangle contains 35 events: Tibet 18, Pamir 11, Afghan 4, Indian 1 and Tien Shan 1. The first three should be reviewed as distinct India–Eurasia collision-belt children, not merged simply because they occur in the same rectangle. The Tibet group has 12 collision-zone, 5 sinistral-transform and 1 dextral-transform nearest-boundary classifications. The Pamir group has 10 collision-zone nearest boundaries, and `Main Pamir Thrust` is the nearest named boundary for 8 events. Seven catalogue events carry the Hasterok geological-province label `Himalayan Orogenic Belt`; seven have `Himalayan Main Boundary Thrust` as the nearest named mapped boundary. Those two signals should be evaluated together, but neither makes every event a Himalayan Main Thrust earthquake.

Burma (19 events) and Shan-Thai (3) should form a separate review complex. All seven geometric overlap events are in this two-subplate set (Burma 4, Shan-Thai 3). The source layers are not exclusive: PB2002 `Persia-Tibet-Burma` contains 55 events in the frozen catalogue: 34 in the Himalaya–Tibet rectangle, 7 in overlap review, 1 in the Sunda rectangle and 13 outside all four original boxes. Therefore, the entire PB2002 orogen should not be used as a single exclusive event-selection polygon.

### B. Japan–Kuril and the northwest Pacific

The Japan–Kuril rectangle contains 79 Kuril-Kamchatka events, 13 Okhotsk, 12 Bering Sea, 10 Pacific, 6 Southwest Japan Inner, 5 Amur, 4 Izu Bonin, 4 Kinki Outer, 3 Ryukyu and 2 Philippine. These should not be pooled into one study population.

The Kuril-Kamchatka subplate has 79 events: 60 have subduction-zone and 19 collision-zone nearest-boundary classes; the most common nearest plate pair is Kuril-Kamchatka | Pacific (69 events). The USGS regional map describes the arc from Hokkaido along the Kurils to Kamchatka, where the Pacific plate subducts beneath the Okhotsk microplate. Bering Sea is a distinct adjacent candidate: 37 events occur in the full catalogue, but only 12 fall inside the old Japan–Kuril rectangle; 25 are outside. Keep separate review tags for Kuril-Kamchatka, Okhotsk, Amur, Bering Sea/Aleutian, Southwest Japan/Kinki, Izu-Bonin and Ryukyu.

### C. Sunda–Indonesia is not one homogeneous system

The original Sunda–Indonesia rectangle contains West Sumatra 39, Sunda 29, Banda Sea 20, Molucca Sea 19, Timor 16, Burma 15, Bicol 11, Mindanao 10, Mamberamo 8, Cenderawasih 7 and Birds Head 6, among other units. The boundary evidence varies by subplate:

| Hasterok subplate | Events | Nearest-boundary mix |
|---|---:|---|
| West Sumatra | 39 | 19 subduction, 15 dextral transform, 5 extension |
| Sunda | 29 | 18 subduction, 6 dextral transform, 3 collision, 1 spreading, 1 extension |
| Banda Sea | 20 | 15 collision |
| Timor | 16 | 15 collision |
| Molucca Sea | 19 | 18 subduction |
| Burma | 19 | 9 subduction, 4 extension, 4 dextral transform, 1 spreading, 1 collision |

Treat West Sumatra and Sunda/Java as different along-arc candidates. Published studies describe variation in subduction obliquity and strike-slip partitioning between Sumatra and Java. Keep Banda Sea and Timor as separate collision-dominated child domains. Keep Molucca Sea and Halmahera separate child units under a double-subduction review parent: published work describes opposing/double-vergent subduction in the Molucca Sea.

The Philippines should remain a complex-orogen review. PB2002 assigns 37 events to its `Philippines` orogen, and Bird explicitly cautions against a simple rigid-plate division there. Hasterok's exact subplate tags are retained alongside this PB2002 overlay; they do not have identical memberships. New Guinea/Birds Head, North Sulawesi, Mariana and Ryukyu should not be swept into a generic Sunda rectangle.

### D. Andes and non-Andes captured by the old box

The Andes rectangle contains Puna 46, South American 27, Altiplano 18, North Andes 8, Panama 8, Peruvian 6, Lesser Antilles 4, South Chile 3, Cocos 2, Nazca 2, Scotia 2 and Coiba 1. PB2002 marks 35 events in the `Puna-Sierras Pampeanas` orogen and 10 in the `Peru` orogen. The Hasterok labels support separate candidate children for Puna, Altiplano, North Andes, Peruvian and South Chile. Keep the 49 South American subplate events as a broad review group: 27 are in the original Andes rectangle and 22 are outside; they should not all automatically be treated as Andean-margin earthquakes. Panama, Lesser Antilles, Coiba and Cocos are outside the Andes core definition.

Published Andean tectonic work distinguishes Northern, Central and Southern Andes, and describes the Altiplano-Puna plateau within the Central Andes. This supports candidate subdomains, but not arbitrary latitude-only boundaries.

## 4. External/adjacent domains: not a control group

The outside-pilot set includes substantial mapped tectonic systems, including New Hebrides (57), South Bismarck (45), Bering Sea (25 outside the old box), Kermadec (37), San Christobal (33), Mariana (7 outside the Sunda box), and several others. The nearest-boundary report shows 261 outside-pilot events whose nearest mapped boundary is a subduction zone and 118 whose nearest is a spreading centre. Therefore, `OUTSIDE_PILOT` is a geographic inventory category only—not a control group, tectonically inactive sample, or automatically eligible non-event background.

## 5. What the new event-level file does

`event_level_candidate_segmentation_review_v001.csv` adds:
- `candidate_domain_family_v001` and `candidate_subdomain_v001`, based on exact Hasterok subplate labels only;
- `pb2002_orogen_review_tag_v001` and `pb2002_complex_orogen_flag_v001`, preserving PB2002 independently;
- `proposal_status_v001`, distinguishing tags inside/overlapping the old pilot, adjacent tagged domains outside it, and unmapped records;
- `original_overlap_review_retained_v001`, preserving the original seven-event review status.

No original assignment or source field is overwritten. The candidate summary tables give event counts, decade-period counts, nearest-boundary-type mixes, median distances and PB2002 orogen labels.

## 6. Required cautions

1. Nearest mapped boundary distance is not distance to a rupture plane, hypocentre, causative fault or slab surface. It does not itself define domain membership.
2. Hasterok geological provinces are lithospheric context; they are not earthquake sequence regions.
3. PB2002 orogens overlap plate polygons and are not exclusive replacements for plate labels.
4. The `Persia-Tibet-Burma` orogen and `Philippines` orogen should not be flattened into simple plate assignments.
5. Small candidate groups (e.g., Afghan 4, Izu-Bonin 5, South Chile 3, Tien Shan 3) are too small for standalone sequence statistics in this target catalogue; retain them as descriptive or combine only with a justified parent model.
6. The target catalogue uses ComCat preferred numerical magnitude with a `minmagnitude=6.5` query; it is not a strict Mw-only catalogue. Magnitude-type strata remain necessary.
7. The source boundary model is present-day and does not reconstruct tectonic boundaries at each earthquake origin time.

## 7. Next work package: Stage 1C.2.5

Create a GIS review map and edge-case ledger with all 1,186 events, old rectangle boxes, Hasterok subplates/provinces, PB2002 plates/orogens and boundary lines. Highlight: the seven Myanmar overlap events; 13 Persia-Tibet-Burma-orogen events outside the four rectangles; the one event inside Sunda core but in that orogen; Bering Sea/Aleutian events; Ryukyu events split across old boxes; New Guinea/Mariana events; and South American/Caribbean labels inside the Andes rectangle. Record source polygon version and review reason for every candidate edge case.

Before region freeze, the investigator must state whether the regional comparison is aimed at continental collision, subduction-interface earthquakes, intraslab earthquakes, strike-slip systems or a mixed tectonic population. These settings should not be pooled by rectangle alone. For subduction domains, Slab2 can be used as a depth-dependent consistency check, but its slab surfaces/clipping masks are not the entire seismic-region boundary.

**Decision:** Keep Stage 1C.2 pilot v001, polygon overlay v001 and boundary-distance audit v001 unchanged. Stage 1C.2.4 is a provisional proposal only. Proceed to GIS map/edge-case review, not supporting-event acquisition or sequence assignment.
