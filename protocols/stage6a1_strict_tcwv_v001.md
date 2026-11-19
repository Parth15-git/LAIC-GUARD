# LAIC-GUARD Stage 6A.1 — Strict TCWV Sensitivity Protocol

**Protocol ID:** LAIC-GUARD-STAGE6A1-STRICT-TCWV-v001  
**Date:** 2026-11-18  
**Status:** Post-audit sensitivity protocol, frozen before new implementation  
**Parent benchmark:** Stage 6A v004 repaired distancefix  
**Purpose:** Re-evaluate tropospheric and joint features without dew-point-derived TCWV substitution and with explicitly requested ERA5 data.

---

## 1. Scientific scope and interpretation

Stage 6A compares two pre-event windows:

- W0: earlier pre-event window.
- W1: later pre-event window.

The task is temporal discrimination between W0 and W1. It is NOT earthquake prediction, prospective forecasting, or earthquake-versus-non-earthquake classification.

Stage 6A.1 is a post-audit sensitivity analysis. Its cohort and data-handling rules were developed after inspecting Stage 6A v004 and its source data. It must not be described as a pre-registered confirmatory experiment.

The original v004 result remains a historical benchmark and must remain reproducible. Stage 6A.1 is a separate analysis, not an overwrite or repair-in-place.

## 2. Immutable source and output protection

The following must remain unchanged:

- All Stage 6A v003/v004 scripts.
- All Stage 6A v004 source variants, including regionfix, cachefix and distancefix.
- Existing reports/stage6a outputs.
- Existing data/external/meteorology/era5_openmeteo_v002 caches.
- Original Stage 5E source and outputs.

Do not use git clean, git reset --hard, or destructive cleanup commands.

New files must use separate paths:

- Script: scripts/stage6a1_strict_tcwv_v001.py
- ERA5 cache: data/external/meteorology/era5_explicit_era5_station_elevation_v001/
- Output: reports/stage6a1/strict_tcwv_v001/
- Manifest: stored inside the new ERA5 cache directory.
- Protocol: protocols/stage6a1_strict_tcwv_v001.md

No output from Stage 6A.1 may be written into reports/stage6a/.

## 3. ERA5 data-source specification

Use the Open-Meteo Historical Weather Archive endpoint:

https://archive-api.open-meteo.com/v1/archive

Explicit request parameters:

- models=era5
- cell_selection=land
- latitude and longitude from metadata/station_registry.csv
- Coordinates formatted to four decimal places, matching the pilot request.
- elevation equal to the station registry elevation in metres.
- timezone=UTC
- start_date = calendar date of event origin minus 45 days.
- end_date = calendar date of event origin plus 5 days.

Requested hourly fields:

- surface_pressure
- temperature_2m
- dew_point_2m
- total_column_integrated_water_vapour

Expected units:

- surface_pressure: hPa
- temperature_2m: degrees Celsius
- dew_point_2m: degrees Celsius
- total_column_integrated_water_vapour: kg/m²

Expected timestamp count: 1,224 hourly timestamps per event-station cache, covering 51 inclusive calendar days.

Record for every response:

- Event ID and station ID.
- Exact request parameters.
- Requested station coordinates and station elevation.
- Returned grid-cell latitude and longitude.
- Returned grid-cell elevation.
- Timezone and hourly units.
- Timestamp coverage and missing-value counts.
- HTTP/request outcome and retry count.
- API response generation time if present.
- Raw response SHA256.
- Retrieval timestamp in UTC.
- Response model metadata, explicitly recording NOT_RETURNED when absent.

Important provenance limitation: the pilot returned no model identifier in the response metadata. The manifest may establish that models=era5 was explicitly requested, but must not claim that the response itself independently confirmed the selected model.

Do not reuse an old Best Match cache as a substitute for a failed new request.

Do not overwrite old caches. Write new cache files to the new versioned directory. Validate a response before marking its cache complete.

## 4. Station and grid-cell handling

The station registry is the authoritative source for:

- GNSS station latitude.
- GNSS station longitude.
- GNSS station elevation.

The Open-Meteo returned coordinates identify the selected model grid cell, not the exact GNSS monument. Record the station-to-grid distance for every event.

Use the supplied station elevation in the API request and in the zenith hydrostatic delay calculation.

The pilot showed that supplying station elevation changes surface pressure by several hPa in the tested cases, while TCWV did not change in those five cases. This must not be assumed for every event until the complete 111-cache comparison is complete.

Report the distribution of station-to-grid offsets and station-to-grid elevation differences. Do not describe gridded weather values as point measurements at the GNSS monument.

## 5. Direct-TCWV rule — no imputation

Only directly returned, non-null total-column integrated water vapour may enter the strict Stage 6A.1 ZTD calculation.

Prohibited:

- Dew-point-to-TCWV fallback.
- Forward filling.
- Backward filling.
- Interpolation of missing TCWV in time.
- Replacing missing TCWV with climatological values.
- Using values from the old Best Match cache when the new cache is missing.
- Silently substituting a different model.

Dew point may be retained as an auxiliary diagnostic variable, but it must never replace TCWV.

If a required meteorological variable is missing at a timestamp, that timestamp is unavailable for strict ERA5 ZTD and GNSS-ERA5 calibration.

All missingness masks must be preserved and reported.

## 6. ERA5 ZTD calculation

Calculate ZTD independently from the raw meteorological variables. Do not import or reuse the Stage 5E forward calculation, which contains a wet-delay unit-conversion error.

Use the validated Stage 6A physical conversion:

Let:

- Ps = surface pressure in hPa.
- T2 = 2 m temperature in degrees Celsius.
- TCWV = total-column water vapour in kg/m².
- phi = station latitude in radians.
- h = station elevation in metres.

Hydrostatic delay:

ZHD = (2.2768 x Ps) / [1 - 0.00266 cos(2 phi) - 0.00028 (h/1000)]

Mean atmospheric temperature:

Tmean = 70.2 + 0.72 (T2 + 273.15)

Wet-delay conversion factor:

Pi_inverse = 1e-5 x 461.5 x (3.739e5 / Tmean + 22.1)

Wet delay:

ZWD = Pi_inverse x TCWV

Total delay:

ZTD = ZHD + ZWD

Expected order of magnitude for Pi_inverse is approximately 6–7 mm per kg/m² under ordinary atmospheric conditions.

Before processing the cohort, implement independent numerical unit tests for ZHD, ZWD and ZTD, including unit checks and finite-value assertions.

Use station latitude and station elevation in the hydrostatic calculation. Do not substitute the returned model-cell elevation for the registered station elevation.

## 7. GNSS troposphere observations

Use the existing UNR GNSS troposphere archive inputs and the strict Stage 5C parser, after verifying the parser has not changed.

Preserve its timestamp conversion and TROTOT quality limits:

- TROTOT range: 1,000–3,500 mm.
- UTC timestamp handling.
- Duplicate timestamp handling.
- Hourly aggregation.

For every event, record:

- Number of archive files listed.
- Number found.
- Number successfully parsed.
- Number of rejected measurements.
- Number of duplicate timestamps.
- Number of unique hourly ZTD values.

Do not count an hour as a calibration pair unless both GNSS ZTD and direct-TCWV ERA5 ZTD exist at the same UTC hour.

## 8. Analysis windows

Anchor offsets to the event origin rounded down to the UTC hour.

All windows are half-open intervals:

| Window | Relative hours | Duration |
|---|---|---:|
| B0 | [-1080, -792) | 288 hours / 12 days |
| W0 | [-792, -552) | 240 hours / 10 days |
| B1 | [-552, -264) | 288 hours / 12 days |
| W1 | [-264, -24) | 240 hours / 10 days |
| Guard | [-24, 0) | 24 hours / 1 day |

B0 calibrates W0. B1 calibrates W1.

No overlap between baseline and target windows is permitted.

## 9. Strict calibration and feature eligibility

For each event, fit separate OLS transfer calibrations:

- B0: GNSS ZTD as a function of direct ERA5 ZTD.
- B1: GNSS ZTD as a function of direct ERA5 ZTD.

Minimum calibration requirements:

- At least 24 matched hourly GNSS-ERA5 pairs in B0.
- At least 24 matched hourly GNSS-ERA5 pairs in B1.
- Non-degenerate predictor variance.

If fewer than 24 pairs exist, or the predictor variance is degenerate, calibration must be marked FAILED. Do not silently return intercept=0 and slope=1, and do not silently substitute an uncalibrated residual.

Strict target-window requirements:

- At least 12 matched direct-TCWV/GNSS hours in W0.
- At least 12 matched direct-TCWV/GNSS hours in W1.

For robust baseline scoring, retain the existing minimum pool requirement of 20 valid baseline values.

For each UTC hour of day, use the hour-specific median and MAD when at least two valid baseline observations exist. Otherwise use the pooled baseline median and MAD, matching the v004 scoring convention.

Record the exact sample counts used for every calibration and every feature score.

An event that fails a required check must be flagged and excluded from the strict M2c feature cohort. No silent fallback is allowed.

## 10. Candidate cohorts from the read-only audit

The existing-cache strict-TCWV audit produced these candidate counts:

| Cohort | Events passing current numerical rules |
|---|---:|
| Primary shallow targets | 88 / 90 |
| Physical null controls | 19 / 21 |

Target failures:

- us7000lsze / KMTR: B1 = 30 pairs; W1 = 0.
- us7000m9g4 / SHUL: all four windows = 0.

Control failures:

- us6000m52p / CRUZ: W1 = 0.
- us7000n05d / CJNT: B0 = 0 and W0 = 0.

The pinned ERA5 five-event pilot showed the same TCWV missingness masks in those five cases. Nevertheless, the final eligible cohort must be recalculated from all new pinned caches. The 88/19 counts remain provisional until that full-cache audit passes.

Candidate exact evaluation-specific dependence counts from the existing feature file:

- Original primary targets: 90 events / 38 components.
- Direct-TCWV complete-case targets: 88 events / 36 components.
- Conservative target sensitivity: 87 events / 35 components.
- Direct-TCWV physical controls: 19 events / 15 components.

G088 / us6000nith passes the numerical minimums with 127 B0, 240 W0, 288 B1 and 240 W1 pairs. However, its B0 coverage is concentrated in the last six calendar days of the 12-day baseline, with seven consecutive days of zero direct-TCWV coverage.

Keep G088 in the primary strict complete-case candidate cohort but mark it with a temporal-coverage warning. Also run a conservative target sensitivity excluding G088. Do not conceal the sensitivity or select whichever version gives the more favourable result.

Any change in candidate eligibility after full pinned-cache retrieval must be documented in a versioned addendum before feature extraction or model evaluation.

## 11. Dependence grouping

Rebuild dependence components separately for each exact evaluation cohort.

Do not reuse the full 111-event component labels as the evaluation group count.

Preserve the existing primary dependence definition:

- Analysis interval: [origin - 45 days, origin - 1 day).
- Connect events with overlapping analysis intervals.
- Also connect events sharing the same nonblank station within 50 days.
- Use transitive connected components.

The original 90-target evaluation rebuilds to 38 components, although the 90 target rows carry 37 distinct labels inherited from the full 111-event cohort. This was traced to a physical-control bridge in the original graph.

For all Stage 6A.1 analyses, rebuild the graph from the exact target or control evaluation subset and report component membership and size distribution.

## 12. Models and fair comparisons

Preserve the scientific definitions of the existing model families:

- M2a: raw GNSS ZTD.
- M2b: uncalibrated GNSS-minus-weather residual.
- M2c: baseline-calibrated GNSS-minus-ERA5 residual.
- M3: quiet-adjusted GIM VTEC.
- M4: joint calibrated ERA5 residual plus quiet-adjusted VTEC.

The primary strict target population for ERA5-dependent analysis is the final direct-TCWV eligible shallow-target cohort.

For paired model comparisons, all compared models must use exactly the same event order, labels, target windows and rebuilt dependence groups.

M3 can be reported separately on its original VTEC-eligible population, but comparisons between M3 and M2c/M4 must restrict M3 to the same event population as the ERA5-dependent models.

Keep physical null-control analyses separate from primary shallow-target classifier evaluation. These controls are earthquakes, not non-earthquake placebo windows.

For the VTEC F10.7 adjustment, retain the existing quiet criteria and fitting approach, but record the number of valid quiet fitting pairs and every fallback or missing-F10.7 case. Do not hide when a correction is not estimated.

## 13. Statistical inference

Primary AUC tests:

- Four primary model evaluations: M2a, M2c, M3 and M4.
- Component-level paired label swaps.
- Full grouped leave-one-component-out refit for every permutation.
- 9,999 permutations per primary model.
- Fixed recorded seeds.
- Two-sided statistic: absolute departure of AUC from 0.5.
- Report the observed AUC, null-distribution median, 5th and 95th percentiles, permutation count and Monte Carlo p-value.

Report uncertainty intervals using component-level bootstrap resampling. Clearly label intervals conditional on fixed OOF predictions if the model is not refitted inside each bootstrap replicate.

Physical endpoint tests:

- Use q95 paired W1-minus-W0 differences.
- Perform component-level sign flips.
- 9,999 permutations.
- Equal weighting per dependence component.
- Report event count, component count, effect estimate, null distribution and p-value.

Paired model comparisons:

- Use identical strict event populations and exact OOF ordering.
- Use component-level swaps with 9,999 permutations.
- Treat the result as a relative model comparison conditional on the specified procedure, not evidence that either model predicts earthquakes.

Multiplicity:

- Holm family of four primary AUC tests.
- Holm family of three distinct physical endpoints: raw GNSS ZTD, calibrated ERA5 residual and quiet-adjusted VTEC.
- Holm family of two paired model comparisons.

Do not count duplicate physical endpoints from M4 twice.

All component-exchangeability assumptions must be stated. Do not equate a significant difference between two models with useful discrimination against chance.

## 14. Sensitivity populations

Run and report separately:

1. Main direct-TCWV complete-case target cohort, after recalculation from the pinned caches.
2. Conservative target cohort excluding G088 and its target dependence component.
3. Direct-TCWV complete-case physical-control cohort.
4. Separate M3 VTEC-only cohort where appropriate.

Do not combine the target and physical-control groups into a single classifier cohort unless a separately specified analysis justifies it.

Report the exact event IDs, component membership, exclusion reasons and feature availability for every population.

## 15. Provenance and quality assurance

The new pipeline must create:

- New pinned ERA5 cache JSON files.
- Cache manifest with request parameters and response hashes.
- Cache quality report.
- GNSS archive coverage report.
- Direct-TCWV missingness report.
- Station-to-grid offset report.
- Calibration coefficients and calibration diagnostics.
- Event-level feature table with provenance and eligibility flags.
- Evaluation summary.
- OOF prediction tables.
- Permutation null-distribution summaries.
- Unit-test results.
- SHA256 package manifest.
- Human-readable audit report.

Independent validation must verify file hashes, row counts, cohort membership, UTC alignment, missingness masks, calibration pair counts, model inputs, dependence grouping, permutation settings and multiple-testing corrections.

A successful checksum or package verifier establishes package integrity, not scientific validity.

## 16. Explicit limitations and exclusions

The following limitations must remain visible:

- The old Open-Meteo caches used an unpinned model selection and cannot be called verified ERA5.
- The new request explicitly asks for ERA5, but the API response did not return a model identifier in the pilot.
- Weather values represent a selected model grid cell, not the exact GNSS monument.
- Station-height handling changes surface pressure and other meteorological values.
- Direct TCWV is unavailable for some event-window periods.
- G088 has concentrated B0 missingness and must receive a sensitivity flag.
- The Stage 5E wet-delay calculation contains a factor-of-100 conversion discrepancy; do not use its calculated ZTD outputs in Stage 6A.1.
- Stage 6A.1 remains a temporal discrimination sensitivity analysis, not prospective earthquake prediction.
- No matched non-earthquake placebo windows are included in this protocol.
- No claim of earthquake precursor detection or causal LAIC mechanism is permitted from these analyses alone.

## 17. Implementation gates

Do not begin full extraction until the new script and manifest logic are ready.

Gate A — protocol and paths:
- This protocol exists.
- New script and cache/output paths are separate.
- Original v004 files are protected.

Gate B — five-event API pilot:
- Explicit ERA5 model request works.
- Station elevation is applied.
- Units, timestamps, returned grid and missingness are recorded.

Gate C — full 111-cache extraction:
- All requested caches are either validated or explicitly failed.
- No old-cache substitution or imputation.
- SHA256 and request manifest complete.

Gate D — independent data audit:
- Recalculate all target and control eligibility.
- Rebuild exact evaluation-specific dependence graphs.
- Issue a versioned addendum if candidate populations change.

Gate E — feature and model audit:
- Physical unit tests pass.
- Calibration failures are explicit.
- Feature generation and all evaluation inputs are verified.

Gate F — inference and package verification:
- Run the strict and conservative analyses.
- Report null distributions and multiple-testing results.
- Independently verify all outputs.

Only after these gates may Stage 6A.1 results be used in the manuscript.

---

**End of protocol v001.**
