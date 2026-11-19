# LAIC-GUARD Stage 6A.1 Protocol Addendum 002
## Full pinned-ERA5 audit and strict-cohort freeze

Protocol: stage6a1_strict_tcwv_v001.md
Previous addendum: stage6a1_strict_tcwv_v001_addendum001.md
Date: 2026-11-18
Status: Cohort-definition addendum; feature generation has not yet begun.

---

## 1. Full acquisition and independent verification

The full pinned ERA5 acquisition requested 111 event-station records.

Results:

- New downloads: 106.
- Previously validated pilot caches: 5.
- Failed requests: 0.
- Manifest records: 111.
- JSON cache files: 111.
- Missing manifest records: 0.
- Orphan cache files: 0.
- Independent verification failures: 0.

The full independent cache audit passed.

Manifest SHA256:

776A619820785457A8B2A9DD2918E16866A99E446876BE3264140DEBF8088107

Frozen protocol SHA256:

6088588F5CBD1DD29CFBA2B1AF04A1261B25AA91E48FECD08E793A8F8F272538

Addendum 001 SHA256:

3BD5E4A4EACD157E90C9C4E5FDE3B8B3F3019F51E17CD2E4AB7281AE863C2368

All 111 requests explicitly specified:

- models=era5
- cell_selection=land
- registered station latitude and longitude
- registered station elevation
- UTC
- 51 inclusive calendar days and 1,224 hourly timestamps.

No old-cache fallback was used.

The API response did not independently return a model identifier in any of the 111 caches. The scientific provenance statement is therefore: "ERA5 explicitly requested through Open-Meteo Historical Weather API." Do not claim independent model confirmation from response metadata.

## 2. Full meteorological variable audit

Across 111 caches:

Total hourly records: 135,864.

- Surface pressure: 135,864 valid; 0 missing.
- 2 m temperature: 135,864 valid; 0 missing.
- 2 m dew point: 135,864 valid; 0 missing.
- Total-column water vapour: 132,576 valid; 3,288 missing.
- Invalid/non-finite numeric values: 0.

TCWV missingness:

- Missing fraction: 2.42%.
- Five affected event-station caches.
- 106 caches have complete TCWV.
- No dew-point-derived fallback is permitted.

Affected caches:

- us6000m52p / CRUZ: 600 missing TCWV hours.
- us6000nith / G088: 168 missing TCWV hours.
- us7000lsze / KMTR: 648 missing TCWV hours.
- us7000m9g4 / SHUL: 1,224 missing TCWV hours.
- us7000n05d / CJNT: 648 missing TCWV hours.

## 3. Spatial representativeness

Across 111 stations:

- Median station-to-grid offset: 11.576 km.
- 95th percentile: 21.189 km.
- Maximum: 26.360 km.
- More than 5 km: 95 stations.
- More than 10 km: 70 stations.
- More than 15 km: 20 stations.
- More than 20 km: 9 stations.

The returned coordinates identify the selected ERA5 grid cell, not the GNSS monument.

Station-to-grid distance must be reported in event-level provenance and the final audit.

The primary extraction selection remains cell_selection=land. The five-event nearest-selection diagnostic is exploratory; it showed a material TCWV change for G088, and does not replace the primary land-cell configuration.

## 4. Strict numerical eligibility rules

The following original protocol thresholds remain unchanged:

- At least 24 directly observed TCWV / GNSS ZTD matched hours in B0.
- At least 24 directly observed TCWV / GNSS ZTD matched hours in B1.
- At least 12 matched target-window hours in W0.
- At least 12 matched target-window hours in W1.
- No TCWV imputation.
- No silent calibration fallback.
- Calibration predictor variance must be non-degenerate.

All counts below were recalculated from the new pinned ERA5 caches and the existing strict GNSS parser.

## 5. Frozen strict target populations

### Main direct-TCWV complete-case target population

Include all PRIMARY_SHALLOW_TARGET events except:

- us7000lsze / KMTR.
- us7000m9g4 / SHUL.

Result:

- 88 events.
- 36 exact evaluation-specific primary dependence components.
- Largest component: 11 events.

### Conservative target sensitivity

Exclude the two numerical failures above and additionally:

- us6000nith / G088.

Result:

- 87 events.
- 35 exact evaluation-specific primary dependence components.
- Largest component: 11 events.

G088 remains included in the main 88-event complete-case sensitivity, but must carry an explicit temporal-coverage warning. It is excluded in the conservative 87-event analysis.

### Standalone non-ERA5 models

M2a raw GNSS ZTD and M3 VTEC-only analyses do not directly require the strict ERA5 cohort.

They may be reported separately using their original scientifically eligible populations, subject to their own data-quality requirements.

Any M2a-versus-M2c or M3-versus-M2c/M4 paired comparison must use the exact same event IDs, event order, labels, and rebuilt validation components.

For fair M3-versus-M2c/M4 comparison, restrict M3 to the same 88-event strict target population, and repeat using the 87-event conservative population.

## 6. Frozen strict physical-control population

Include all PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE events except:

- us6000m52p / CRUZ.
- us7000n05d / CJNT.

Result:

- 19 physical null-control earthquake events.
- 15 exact evaluation-specific primary dependence components.
- Largest component: 2 events.

These controls are earthquakes and are not non-earthquake placebo windows.

ERA5-independent VTEC control analyses may retain controls subject to their own VTEC availability and quality requirements.

## 7. Temporal coverage warnings

A descriptive warning is assigned to an event-window when it contains at least three consecutive calendar days with zero matched GNSS/strict-ERA5 hours.

This is a descriptive flag only. It is not an additional exclusion rule and must not be tuned after looking at model results.

The full 111-event audit identified 13 affected event records:

### Primary shallow targets (9)

- usp000dujc / LHWA: B0, five consecutive zero-coverage days.
- usp000efv7 / COPO: B1, four days.
- usp000efw2 / COPO: B1, four days.
- usp000fmtk / BUEN: W0, five days.
- usp000fzv0 / SLBU: B0, four days.
- usp000fzx4 / SLBU: B0, three days.
- usp000h8s3 / BSAT: B0, three days.
- us6000lp12 / PGEN: W1, six days.
- us6000nith / G088: B0, seven days.

### Physical null controls (4)

- us6000m52p / CRUZ: B1, nine days; W1, eleven days.
- us7000lsze / KMTR: B1, eleven days; W1, eleven days.
- us7000m9g4 / SHUL: all four windows lack direct matched coverage.
- us7000n05d / CJNT: B0, thirteen days; W0, eleven days; B1, five days.

These gaps reflect matched-data availability. A gap may arise from GNSS missingness, ERA5 missingness, or both. Do not label every unmatched hour as an ERA5 failure.

## 8. Dependence structure

Rebuild dependence components separately for each exact evaluation subset.

Do not reuse the full 111-event component IDs.

Verified exact counts:

- Original target evaluation: 90 events / 38 groups.
- Strict target complete-case: 88 events / 36 groups.
- Conservative target sensitivity: 87 events / 35 groups.
- Strict physical controls: 19 events / 15 groups.

The target-only evaluation differs from the target labels inherited from the full 111-event graph because a physical-control bridge can connect target events in the full graph. Evaluation groups must be recalculated after applying the exact cohort filter.

## 9. Implementation requirements

The new feature-generation script must:

1. Load only the new explicit ERA5 cache directory.
2. Verify every cache against the acquisition manifest and SHA256.
3. Reject any missing/mismatched cache rather than fall back to an old cache.
4. Use direct observed TCWV only.
5. Preserve missingness and window-level coverage counts.
6. Reproduce the validated ZHD/ZWD/ZTD equations.
7. Fit calibration separately in B0 and B1.
8. Reject insufficient or degenerate calibration instead of silently substituting (0,1).
9. Record intercept, slope, pair count, predictor variance, correlation and residual RMSE.
10. Record per-window event coverage and temporal warnings.
11. Rebuild dependence groups within each exact evaluation population.
12. Retain all 111 records in a feature provenance/eligibility table, including excluded rows and explicit reasons.
13. Write analysis outputs only to reports/stage6a1/strict_tcwv_v001/.
14. Never alter the original v004 scripts, caches, reports or manuscript tables.

## 10. Interpretation and inferential limitations

Stage 6A.1 is a post-audit sensitivity analysis of W0-versus-W1 temporal discrimination.

It is not earthquake prediction or prospective forecasting.

The cohort definitions were determined after inspecting the Stage 6A v004 data. The resulting tests are sensitivity analyses and must not be described as pre-registered confirmatory tests.

The full analysis still needs the matched non-earthquake placebo-window experiment. This addendum does not claim that Stage 6A.1 completes all scientific validation of LAIC-GUARD.

No positive result may be described as proof of a precursor, causality or a physical LAIC mechanism without further independent validation.

---

**End of Addendum 002.**
