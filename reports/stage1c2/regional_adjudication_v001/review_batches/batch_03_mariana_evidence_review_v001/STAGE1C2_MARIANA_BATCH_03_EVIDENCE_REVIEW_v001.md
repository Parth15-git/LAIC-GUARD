# Stage 1C.2.6 - Mariana Evidence Review, Batch 03 (v001)

**Status:** Provisional evidence review; not a regional freeze or approved crosswalk.  
**Target candidate family:** `MARIANA_ARC_REVIEW` / `MARIANA`  
**Review universe:** 16 catalogue events, 2000-2024  
**Prepared:** 2026-11-14  

## 1. Purpose and Scope

This package formalizes the provisional evidence review for the 16 target-catalogue events assigned to the `MARIANA_ARC_REVIEW` candidate family. It preserves all frozen values in `metadata/event_catalogue_v002.csv` and separates (a) catalogue facts, (b) local GIS and boundary overlays, (c) event-specific USGS tectonic interpretations, and (d) unresolved items requiring targeted mechanism inspection prior to regional freeze.

It does **not** modify the 1,186-event catalogue, historical v001 pilot assignments, or raw ComCat archives, and it does **not** initiate supporting-catalogue acquisition or assign sequence roles.

## 2. Candidate Provenance & Local Catalogue Reconciliation

* **Frozen catalogue match:** 16/16 IDs verified against `metadata/event_catalogue_v002.csv` (SHA-256 `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`) and the 26 annual USGS ComCat `.geojson` files in `data/raw/usgs/`.
* **Pilot v001 distribution:** 9 events fell inside the broad `SUNDA_INDONESIA_CORE` exploratory rectangle and 7 fell in `OUTSIDE_PILOT` (0 in `OVERLAP_REVIEW_HIMALAYA_SUNDA`). Broad Sunda rectangle membership does not indicate Sunda megathrust affinity.
* **Depth span:** 13.0 km to 602.2 km (shallow crustal/forearc, intermediate slab, and deep-focus populations are mixed and must not be pooled as a single shallow interface source class).

## 3. Spatial Overlay & Model Comparison Summary

* **Hasterok plates (`plates.shp`):** 10 events in `East Mariana Ridge` (subplate `Mariana`); 6 events in `Mariana Trough (east)` (subplate `Mariana`).
* **Hasterok geological provinces (`global_gprv.shp`):** 8 in `Mariana Forearc`, 6 in `Mariana Trough`, and 2 in `Mariana Volcanic Arc`.
* **PB2002 plates (`PB2002_plates.geojson`):** 12 events in `Mariana` (`MA`); 4 events (`usp000ahx8`, `usp000ddgf`, `usp000fpca`, `usp000hj6r`) in `Philippine Sea` (`PS`); 0 inside PB2002 orogens.

## 4. Provisional Disposition Breakdown (16 Events)

| Provisional Disposition | Event Count | Event IDs |
|---|---:|---|
| `PROVISIONAL_SOURCE_CLASSIFICATION_SUPPORTED` | 5 | `usp0009qb4`, `usp000aqsu`, `usp000b37m`, `usp000fpca`, `usp000frnh` |
| `HOLD_DEPTH_ONLY_NO_MECHANISM` | 1 | `usc000gw27` (602.2 km deep-focus; mechanism uninspected) |
| `BOUNDARY_JUNCTION_HOLD` | 1 | `usp000hj6r` (13.0 km, 2.72 km from Guam Transform) |
| `UNRESOLVED_NEEDS_EVENT_SPECIFIC_SOURCE_REVIEW` | 9 | `usp000ahx8`, `usp000b9w7`, `usp000ddgf`, `usp000dfhb`, `usp000f3za`, `usb000sdcr`, `us100068jg`, `us6000lqf9`, `us7000ma2w` |
| **Total** | **16** | |

## 5. Key Junction & Unresolved Caveats

1. **Southern Mariana / Guam Transform junction (`usp000hj6r` & `usp000ddgf`):** Both events lie near the southern Mariana boundary where PB2002 assigns `Philippine Sea` (`PS`) and Hasterok assigns `Mariana`. `usp000hj6r` (2010-08-14 23:01:04.090 UTC, M6.6) occurred ~25 h 41 min 30 s after M6.9 `usp000hj2j` (assigned to `PHILIPPINE_MOBILE_BELT_REVIEW`); preserve both IDs without inferring a sequence or mechanism from proximity alone.
2. **Uninspected ComCat detail products:** Summary metadata confirms `moment-tensor` flags for 16/16 events and `focal-mechanism` flags for 11/16 events, but full ComCat detail product payloads have not yet been retrieved or verified.
