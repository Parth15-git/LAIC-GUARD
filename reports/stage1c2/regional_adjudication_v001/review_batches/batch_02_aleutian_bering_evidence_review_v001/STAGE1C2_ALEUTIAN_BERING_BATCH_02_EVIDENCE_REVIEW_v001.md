# Stage 1C.2.6 — Aleutian–Bering Evidence Review, Batch 02 (v001)

**Status:** Provisional evidence review; not a regional freeze or approved crosswalk.  
**Target candidate family:** `BERING_SEA_ALEUTIAN_REVIEW` / `BERING_SEA`  
**Review universe:** 37 catalogue events, 2001–2025  
**Prepared:** 2026-11-14  

## 1. Purpose and scope

This package reviews the 37 events historically assigned to the Hasterok `Bering Sea` subplate candidate family. It preserves the frozen target-catalogue values and separates (a) catalogue facts, (b) original GIS/source-layer evidence, (c) published event-specific evidence, (d) inference, and (e) proposed—not approved—regional decisions.

It does **not** modify the 1,186-event catalogue, the Stage 1C.2.1–2.5 outputs, or the original v001 candidate family. It does not acquire supporting-earthquake records, assign foreshock/mainshock/aftershock roles for sequence reconstruction, freeze polygons, or approve final regional boundaries.

## 2. Verified historical candidate-family provenance

The user-provided local `candidate_domain_register_v001.csv` output gives:

| Field | Value |
|---|---:|
| Hasterok subplate | Bering Sea |
| Candidate family/subdomain | `BERING_SEA_ALEUTIAN_REVIEW` / `BERING_SEA` |
| Candidate events | 37 |
| Inside original four-box union | 12 |
| Outside original four-box union | 25 |
| Overlap review | 0 |
| Status | `PROVISIONAL_REVIEW_ONLY` |

Original rationale: “Bering Sea subplate; many events lie outside the old Japan-Kuril rectangle, so do not merge by bounding box.” The original decision required map and literature review before freezing any polygon or combining child units.

**Interpretation:** this was a Hasterok-subplate-driven candidate retrieval/retention family, not an independently validated homogeneous earthquake-source population. The v001 family is retained for traceability only.

## 3. Local GIS and boundary evidence

### 3.1 Candidate summary

The local Hasterok subplate inventory reports 37 events. Its nearest-boundary distribution is:

| Nearest mapped boundary type | Events | Share |
|---|---:|---:|
| Subduction zone | 31 | 83.8% |
| Sinistral transform | 3 | 8.1% |
| Collision zone | 2 | 5.4% |
| Dextral transform | 1 | 2.7% |
| **Total** | **37** | **100%** |

Median nearest mapped-boundary distance: **92.19 km**. This is a spatial summary only. It is not a causal-fault label, a source-mechanism classification, or a threshold for inclusion/exclusion.

### 3.2 Geological province counts

| Hasterok province | Events |
|---|---:|
| East Aleutian Forearc | 15 |
| Western Aleutian Forearc | 9 |
| East Aleutian Arc | 4 |
| West Aleutian Arc | 3 |
| Kamchatka Volcanic Arc | 2 |
| Chugach | 2 |
| Peninsular Terrane | 1 |
| Bering Sea Margin | 1 |
| **Total** | **37** |

Province types in the local export: 26 accretionary-complex, 10 volcanic-arc, and 1 passive-margin event. PB2002 plate labels: 35 North America and 2 Okhotsk.

These are source-layer overlay attributes, not direct evidence of the event's causative fault.

### 3.3 Original nearest-boundary source records

| Record | Original feature | Type | Plate pair | Level | Length (km) |
|---|---|---|---|---:|---:|
| `HAST_ROW_0096` | Aleutian Trench | Subduction | Bering Sea–Pacific | 1 | 1,571.514 |
| `HAST_ROW_0283` | Aleutian Trench | Subduction | Bering Sea–Pacific | 1 | 1,256.839 |
| `HAST_ROW_0438` | Unnamed | Collision | Okhotsk–Bering Sea | 2 | 684.881 |
| `HAST_ROW_0255` | Unnamed | Sinistral transform | Bering Sea–Wrangell-Talkeetna | 2 | 439.243 |
| `HAST_ROW_0554` | Unnamed | Dextral transform | Bering Sea–North Alaskan | 2 | 1,250.408 |
| `HAST_ROW_0310` | Unnamed | Sinistral transform | Bering Sea–Alaskan Peninsular | 2 | 316.499 |

Four records have no feature name in the source lookup. Their names remain blank in the event CSV. No geological name has been invented. Level is retained as a source attribute and is not interpreted as event confidence.

## 4. Independent tectonic evidence

### 4.1 Event-specific findings with strong support

| Event | Evidence-supported interpretation | Important qualification |
|---|---|---|
| `usp000bsvs` (2003 Rat Islands) | Shallow oblique thrust on or near Pacific–North America subduction interface | USGS event summary; source segment still not a regional polygon. |
| `usp000cd1n` (2003 Rat Islands) | Shallow thrust on or near the Aleutian plate interface | USGS event summary. |
| `usp000fuse` (2007 Andreanof) | Shallow interface thrust | USGS event summary uses a slightly different hypocentral coordinate from the frozen catalogue. |
| `usp000j3mq` (2011 Fox Islands) | Normal faulting inside downgoing Pacific slab | USGS text contains M7.3 in the event heading/table and M7.2 in body prose; frozen catalogue M7.3 retained. |
| `usb000jdt7` (2013 Atka) | Shallow thrust on or near Pacific–North America interface | USGS event summary. |
| `usc000rki5` (2014 Little Sitkin) | Intermediate-depth oblique normal faulting, likely within downgoing Pacific slab | USGS event summary; depth ~109–110 km. |
| `usp000ef1h` (2006 Koryakia/Olyutorskii) | Shallow reverse faulting; field/SAR literature supports a complex rupture with a major blind thrust and surface-reaching strike-slip/reverse segments | Causative fault and regional plate boundary remain debated; USGS says a Bering plate may be present but is poorly defined. |
| `us20009x42` (2017 Komandorsky) | Right-lateral strike-slip rupture along ~400 km of the Bering Fracture Zone | Lay et al. report Mw7.8 / Ms7.7; catalogue Mww7.7 retained. This is not the Aleutian megathrust. |
| `us7000kg30` (2023 Sand Point) | Thrust on or near Pacific–North America subduction interface | USGS event tectonic summary. |
| `us7000qd1y` (2025 Sand Point) | Strike-slip near the subduction interface, either upper North America plate or downgoing Pacific slab; not an interface thrust | USGS leaves host-plate/fault-plane alternative unresolved. |

### 4.2 Sequence relationships supported by official records

- `usp000j7dc` (2011-09-02) is identified by the Alaska Earthquake Center annual report as an aftershock of `usp000j3mq` (2011-06-24). The annual report magnitude is M6.8, while the frozen target catalogue retains Mww6.9.
- `us7000gavu` and `us7000gawk` are part of the 2022 Fox Islands sequence. The AEC monthly report lists the M6.8 event and a later M6.5 event about 64 minutes afterwards. The frozen target catalogue retains Mww6.8 and Mww6.6 respectively.
- `usp000efs5` corresponds provisionally to the April 29, 2006 M6.6 Olyutorskii aftershock discussed by Lander et al. (2010). The published source-model coordinates should be reconciled with the frozen catalogue event origin before mapping its rupture model to the event row.

These are sequence-context statements for regional review; they are not final sequence-role labels for later reconstruction.

### 4.3 Regional architecture from USGS synthesis

USGS Open-File Report 2016–1192 distinguishes eastern, central and western Aleutians. It describes east-to-west change from more trench-normal compression toward increasingly trench-parallel/transform motion; the central Aleutians retain active volcanism, interface thrusting and a well-defined Wadati–Benioff zone; and the western Aleutians are tectonically different, with greater transform motion and predominantly shallow strike-slip seismicity in the Commander Islands region. The same report describes the Okhotsk/Bering/North America interaction in northeastern Russia as complicated and says the putative Bering plate is poorly defined with uncertain boundaries.

This supports separating tectonic systems and source types. It does not itself define the study polygons for this project.

## 5. Proposed geographic components — not frozen

The current review proposes retaining the historical 37-event family and splitting its adjudication queue into these working components:

1. `ALEUTIAN_ARC_SYSTEM_REVIEW` — the eastern/central/western Aleutian arc and forearc candidates, with along-arc subdivision still to be defined using independent regional literature and geometry.
2. `WESTERN_ALEUTIAN_BERING_FRACTURE_ZONE_JUNCTION` — Komandorsky/Bering Fracture Zone event(s), keeping transform source type separate from megathrust.
3. `ALEUTIAN_KAMCHATKA_JUNCTION_REVIEW` — events whose geography/provenance points toward the western arc–Kamchatka transition.
4. `KORYAKIA_NORTHEAST_RUSSIA_REVIEW` — April 2006 Olyutorskii mainshock/aftershock population; do not automatically label as Aleutian megathrust or as a confirmed Bering Plate region.
5. `BERING_SEA_INTERIOR_MARGIN_REVIEW` — the Bering Sea Margin event with unnamed dextral-transform nearest-boundary record; source mechanism unresolved.
6. `ALASKA_PENINSULA_ADJACENT_REVIEW` / `ALASKA_PENINSULA_CHUGACH_TRANSITION_REVIEW` — Kokhanok/Peninsular Terrane and Sand Point/Chugach events, kept distinct from the Aleutian core until regional boundaries are defended.
7. `WESTERN_ALEUTIAN_COMMANDER_TRANSITION_REVIEW` — shallow westernmost Aleutian event requiring review; do not automatically merge with the July 2017 Komandorsky 12-hour foreshock sequence.

Every value in `proposed_geographic_component_v001` and `proposed_source_type_v001` is a proposal, not a frozen label. `reviewer_disposition_v001` intentionally retains holds where the event-specific evidence does not support a decision.

## 6. Explicit unresolved items

1. **27 events do not yet have independently verified event-specific mechanism classifications in this review.** Their source-type field remains unresolved or explicitly depth/sequence-only.
2. The 2006 Koryakia event's source coordinates differ between the frozen catalogue and USGS tectonic summary; retain both and check source origin/centroid solution lineage.
3. The 2006 April 29 aftershock source model needs exact identity/origin reconciliation with `usp000efs5` through the existing Stage 1B identity records.
4. The Bering Plate's boundary geometry remains uncertain in the cited USGS regional synthesis. No Bering microplate polygon is frozen here.
5. The 2017 Komandorsky paper magnitude (Mw7.8 / Ms7.7) differs in notation/value from the frozen catalogue Mww7.7.
6. The 2011 September and 2022 second-event AEC magnitude values differ from the frozen catalogue values; preserve both in the evidence register.
7. Hasterok nearest-boundary source type and distance must not be used as causal fault or source-mechanism evidence.
8. The 2003 June 15 and June 23 events and other temporally close pairs must not be merged into sequences without event-specific sequence evidence.

## 7. Source register

See `analysis/source_evidence_register_v001.csv`. It includes DOI/URLs for published and official sources and local relative paths for source-layer evidence from the user's repository. The CSV includes the source's supported claim and explicit limitations.

Primary external sources:

- Hayes et al. (2017), USGS Open-File Report 2016–1192, DOI: https://doi.org/10.3133/ofr20161192
- Lay et al. (2017), *Geophysical Research Letters*, DOI: https://doi.org/10.1002/2017GL076148
- Lander et al. (2010), *Journal of Volcanology and Seismology*, DOI: https://doi.org/10.1134/S074204631002003X
- Alaska Earthquake Center January 2022 monthly report: https://earthquake.alaska.edu/earthquakes/reports/monthly/january-2022
- Alaska Earthquake Center 2012 annual report: https://seismic.alaska.gov/download/ashsc_meetings_minutes/ASHSC_2012_annual_report.pdf
- USGS event tectonic summaries for 2023 and 2025 Sand Point events: https://earthquake.usgs.gov/earthquakes/eventpage/us7000kg30 and https://earthquake.usgs.gov/earthquakes/eventpage/us7000qd1y/executive

## 8. Decision requested before regional freeze

This package is a **review batch**, not a decision to approve any proposed component. After the remaining regional batches are completed, the team should decide:

- region polygons/criteria based on published tectonic segmentation and the local source layers;
- one primary geographic disposition per catalogue event, with documented secondary tags;
- boundary/junction rules and how unresolved source types/depths are represented;
- source-type strata without forcing all events in a geographic system into one population;
- all 1,186 event crosswalk rows and checksums.

No supporting-earthquake downloads should begin until regional definitions are frozen and the Stage 1C.0 approval-state contradiction is resolved through a versioned addendum.

## 9. Provenance note

All 37 event facts and local GIS attributes in the event-level CSV were transcribed from the user-provided PowerShell outputs in this conversation. They were not independently re-read from the user's Windows repository in this session. The SHA-256 manifest below protects this generated package only; it does not attest to the hashes of the user's local inputs.
