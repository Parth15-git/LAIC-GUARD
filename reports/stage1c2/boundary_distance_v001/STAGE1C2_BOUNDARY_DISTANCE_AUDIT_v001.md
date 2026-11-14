# LAIC-GUARD Stage 1C.2.3 — Tectonic Boundary Distance Audit v001

## Scope
Computed nearest distances from all 1,186 frozen target catalogue epicentres to the mapped line records in Hasterok `plate_boundaries.shp`.
The source catalogue and Stage 1C.2 pilot assignment v001 were read-only. No supporting earthquake records were downloaded and no sequence labels were assigned.

## Methods
- Boundary layer: 571 source rows; EPSG:4326; {'LineString': 567, 'MultiLineString': 4} geometry types.
- Each source segment was densified along WGS84 geodesics to a maximum vertex spacing of 10 km.
- For each event, linework was transformed into an event-centred WGS84 azimuthal-equidistant projection. Minimum point-to-line distance was measured from the projected origin.
- The nearest point was transformed back to WGS84 and checked with `pyproj.Geod.inv`.
- No distance threshold was applied. All source boundary classes, including `inferred`, are included in the primary nearest-boundary result.
- A second result reports the nearest non-`inferred` source record. Boundary `level` is retained but not interpreted.
- `feature_id` is not unique in the supplied shapefile; source row IDs `HAST_ROW_0001`... are used to preserve separate records.

## Validation
- Catalogue rows / unique event IDs: 1186 / 1186.
- Boundary source rows: 571; invalid geometries: 0; empty geometries: 0.
- Projection-to-geodesic recheck maximum absolute difference: 0.000000 m.
- Candidate prefilter versus exhaustive 571-record search: 17 events; max absolute distance difference: 0.0 m; same nearest row: 17 / 17.
- Densification convergence sample: 64 events; maximum absolute difference between 10 km and 2 km steps: 0.03418985500047711 m.
- Same nearest source record in convergence sample: 64 / 64.

## Nearest boundary distance by pilot assignment
| pilot_assignment_v001         |   event_count |   min_km |   median_km |   mean_km |   max_km |   q1_km |   q3_km |
|:------------------------------|--------------:|---------:|------------:|----------:|---------:|--------:|--------:|
| ANDES                         |           127 |    1.251 |      88.285 |    95.956 |  304.523 |  51.942 | 123.818 |
| HIMALAYA_TIBET_CORE           |            35 |    1.890 |     100.765 |   136.062 |  528.165 |  59.660 | 166.808 |
| JAPAN_KURIL                   |           138 |    1.508 |      96.050 |   109.845 |  611.596 |  51.504 | 146.569 |
| OUTSIDE_PILOT                 |           640 |    0.063 |      43.278 |    77.584 | 3549.896 |  14.190 |  84.665 |
| OVERLAP_REVIEW_HIMALAYA_SUNDA |             7 |    1.869 |      64.764 |    63.090 |  142.744 |   3.876 | 112.251 |
| SUNDA_INDONESIA_CORE          |           239 |    0.469 |      50.423 |    70.897 |  772.153 |  25.569 |  92.670 |

## Primary nearest boundary type by pilot assignment
| pilot_assignment_v001         | nearest_boundary_type   |   event_count |
|:------------------------------|:------------------------|--------------:|
| ANDES                         | subduction zone         |            67 |
| ANDES                         | collision zone          |            37 |
| ANDES                         | inferred                |            16 |
| ANDES                         | dextral transform       |             3 |
| ANDES                         | extension zone          |             2 |
| ANDES                         | sinistral transform     |             1 |
| ANDES                         | spreading center        |             1 |
| HIMALAYA_TIBET_CORE           | collision zone          |            24 |
| HIMALAYA_TIBET_CORE           | sinistral transform     |             8 |
| HIMALAYA_TIBET_CORE           | dextral transform       |             3 |
| JAPAN_KURIL                   | subduction zone         |            87 |
| JAPAN_KURIL                   | collision zone          |            41 |
| JAPAN_KURIL                   | extension zone          |             7 |
| JAPAN_KURIL                   | dextral transform       |             2 |
| JAPAN_KURIL                   | spreading center        |             1 |
| OUTSIDE_PILOT                 | subduction zone         |           261 |
| OUTSIDE_PILOT                 | spreading center        |           118 |
| OUTSIDE_PILOT                 | dextral transform       |            84 |
| OUTSIDE_PILOT                 | extension zone          |            81 |
| OUTSIDE_PILOT                 | sinistral transform     |            50 |
| OUTSIDE_PILOT                 | collision zone          |            37 |
| OUTSIDE_PILOT                 | inferred                |             9 |
| OVERLAP_REVIEW_HIMALAYA_SUNDA | dextral transform       |             5 |
| OVERLAP_REVIEW_HIMALAYA_SUNDA | collision zone          |             2 |
| SUNDA_INDONESIA_CORE          | subduction zone         |           101 |
| SUNDA_INDONESIA_CORE          | collision zone          |            43 |
| SUNDA_INDONESIA_CORE          | dextral transform       |            42 |
| SUNDA_INDONESIA_CORE          | extension zone          |            19 |
| SUNDA_INDONESIA_CORE          | sinistral transform     |            19 |
| SUNDA_INDONESIA_CORE          | spreading center        |            13 |
| SUNDA_INDONESIA_CORE          | inferred                |             2 |

## Nearest boundary type overall
| nearest_boundary_type   |   event_count |   median_distance_km |   mean_distance_km |
|:------------------------|--------------:|---------------------:|-------------------:|
| subduction zone         |           516 |               70.594 |             76.437 |
| collision zone          |           184 |               73.954 |             92.520 |
| dextral transform       |           139 |               29.960 |             61.299 |
| spreading center        |           133 |               16.560 |            113.479 |
| extension zone          |           109 |               52.014 |            102.816 |
| sinistral transform     |            78 |               39.750 |             54.829 |
| inferred                |            27 |               71.341 |            132.780 |

## Additional audit findings
- Median nearest mapped-boundary distance across all events: 57.290 km.
- The primary nearest line record is classified as `inferred` for 27 events; these are retained in the primary result and accompanied by a nearest non-inferred alternative.
- The source boundary `feature` name is blank for 267 primary matches; boundary type and both plate-pair fields are populated for all events.
- Largest-distance events (not exclusions):
| event_id   | place                                |   nearest_boundary_distance_km | nearest_boundary_type   | nearest_boundary_name                  |
|:-----------|:-------------------------------------|-------------------------------:|:------------------------|:---------------------------------------|
| hv5532127  | 14 km SW of Puako, Hawaii            |                       3549.896 | spreading center        | Juan de Fuca Ridge                     |
| hv70116556 | 18 km SSW of Leilani Estates, Hawaii |                       3529.190 | spreading center        | Juan de Fuca Ridge                     |
| usc000rfh2 | South Indian Ocean                   |                        772.153 | inferred                | Southern Capricorn Boundary (proposed) |
| us70004jxe | 198 km W of Cable Beach, Australia   |                        719.876 | subduction zone         | Sumatra-Java Trench                    |
| usp000aufx | south of Australia                   |                        660.587 | spreading center        | Australia-Antarctica Ridge             |

## Interpretation limits
- These are distances to the nearest mapped boundary line in the Hasterok source model, not distances to a rupture plane, hypocentre, slab surface, or necessarily the causative fault.
- The minimum may be to a boundary class such as transform, collision, spreading centre, extension, or inferred; do not interpret every nearest boundary as a subduction interface.
- Distances do not establish tectonic-region membership or justify a geographic cutoff. They are evidence for the later regional-domain review.
- The source geometry is a present-day model and the calculation does not reconstruct boundary positions at each earthquake origin time.

## Reproducibility
- Catalogue SHA-256: `0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315`
- Crosswalk SHA-256: `e3c7d36c9580491acfcb77a4ba501b7496692230dde5015ba964c5b903c2122c`
- Boundary shapefile SHA-256: `d417f783bf86fe2980f7b117631b17c1d3020364032f6579a8c35be73eff3966`
- Full machine-readable metadata: `boundary_distance_run_metadata_v001.json`.
