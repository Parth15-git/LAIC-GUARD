# Stage 6A Audit-Compliant Repaired Benchmark (v004)

**Report status:** Generated from the completed v004 region-fix bounded-cache benchmark run.

**Regional metadata correction:** Frozen macro-regions are read from Stage 1D `frozen_macro_region_v001` and checked against the Stage 4B field for every event. Blank or mismatched labels stop the run.

**Distance source:** Stage 4B `verified_gnss_distance_km`; no default distance or imputation is used.
**Distance validation:** all 111 event distances were independently checked against Stage 1D epicentre and verified station-registry coordinates. Maximum absolute difference: 0.004990 km (acceptance tolerance: 0.1 km).
**Secondary analyses skipped:** 0. Skipped analyses remain visible in the summary CSV and JSON; they are not treated as evaluated results.

**IONEX memory policy:** Chronological sliding cache; maps earlier than the current event origin minus 45 days are evicted. The parser, interpolation and scientific time windows are unchanged.
- Maximum cached daily entries: 51
- Evicted daily entries: 2908

## 1. Scientific question and scope

This analysis evaluates retrospective discrimination between an earlier
pre-event window (W0) and a later pre-event window (W1). Each eligible
earthquake contributes a paired W0/W1 classifier sample.

**This is not prospective earthquake prediction.** It does not establish
operational warning capability, prospective lead time, earthquake-versus-
non-earthquake discrimination, or causal effects.

## 2. Event-relative temporal design

All intervals are event-relative hours and use half-open boundaries:

| Interval | Event-relative hours |
|---|---:|
| B0 | [-1080, -792) |
| W0 | [-792, -552) |
| B1 | [-552, -264) |
| W1 | [-264, -24) |
| Guard | [-24, 0) |

The classifier compares W0 (label 0) with W1 (label 1). Both are
pre-event periods. The final 24 hours are reserved as a guard interval.

## 3. Cohort and dependence structure

- Retained event-feature rows: 111
- Primary shallow-target events: 90
- Physical null-control events: 21
- Unique stations: 82
- Unique regions: 11
- Original overlap-graph components: 65

The primary dependence grouping connects events when their
event-relative [origin-45 days, origin-1 day) data intervals overlap,
or when they use the same station within 50 days. Components are
reconstructed within each exact analysis cohort after eligibility
filtering. Sensitivity groupings use shared time intervals alone and
shared time intervals or the same station at any temporal separation.

- Time-overlap-only components: 40
- Shared-time or same-station-within-50-days components: 38
- Shared-time or same-station-at-any-time components: 27

These grouping choices address dependence in the available event/station
data. They do not demonstrate generalisation to unseen stations, regions,
or future earthquakes.

## 4. Primary model families

- M2a: raw GNSS ZTD-only features.
- M2c: baseline-calibrated ERA5 residual features.
- M3: F10.7-adjusted quiet GIM VTEC features.
- M4: joint calibrated ERA5 residual and VTEC features.

The benchmark also retains secondary analyses, controls, and sensitivity
subsets. The benchmark summary CSV is the authoritative row-level record
of the numerical model results.

## 5. Validation and uncertainty procedures

- Primary validation holds out complete dependence components rather
  than splitting paired observations from the same component across
  training and test folds.
- Feature scaling and model fitting are performed within training folds.
- Group-bootstrap confidence intervals resample complete dependence
  groups and are conditional on the already-computed out-of-fold
  predictions; they do not refit the full pipeline in each bootstrap.
- Primary AUC permutation tests flip paired label orientation at the
  component level and refit the classifier for each permutation.
- Physical endpoint tests use two-sided component-level sign flips.
  Components, rather than individual events, receive equal weight.
- Model comparisons swap complete component-level blocks of fixed
  out-of-fold predictions. These comparisons are conditional on the
  fixed predictions and do not retrain models for each swap.

The permutation and sign-flip procedures rely on their stated
component-level exchangeability or sign-symmetry assumptions. Those
assumptions are not guaranteed merely by constructing components.

## 6. Multiple-testing correction

Holm step-down correction is applied separately to three defined
families: four primary AUC tests, three distinct physical endpoints,
and two matched primary model comparisons.

M4 repeats the calibrated ERA5 and VTEC physical endpoints already
represented by M2c and M3 on the same cohort. Those duplicate M4
physical tests are not counted again in the three-endpoint family.

## 7. Permutation-resolution limitation

The four primary refitted AUC permutation tests currently use 99
permutations as a computational pilot. Their minimum attainable
Monte Carlo p-value is 0.01. This is coarse resolution and is not
suitable as final confirmatory evidence. The pilot count must be
increased and the full-run computational cost assessed before any
confirmatory interpretation.

## 8. Interpretation limits

1. The target is earlier-versus-later pre-event temporal discrimination,
   not prospective earthquake prediction.
2. The evaluated cohort is the selected paired Stage 4B cohort; results
   do not automatically generalise to all earthquakes or stations.
3. Grouped validation and component-level resampling reduce specified
   dependence risks but cannot eliminate unmeasured confounding or
   establish physical causality.
4. Bootstrap intervals based on fixed out-of-fold predictions are
   conditional uncertainty estimates, not full-pipeline retraining
   intervals.
5. The 99-permutation AUC analysis is a pilot with limited p-value
   resolution and must not be presented as final confirmation.
6. No operational false-alarm rate, warning lead time, or prospective
   forecast skill is established by this experiment.

## 9. Output files

- `analysis/stage6a_v004_benchmark_summary.csv`: model-level results
  and adjusted p-values.
- `analysis/stage6a_v004_event_features.csv`: retained event-level
  feature and metadata rows.
- `analysis/stage6a_unit_and_window_tests_v004.json`: unit/window
  tests, cohort counts, dependence-group counts, model comparisons,
  multiple-testing definitions, and scientific-scope metadata.
- `SHA256SUMS.csv`: file sizes and SHA256 digests for package files.
- `VERIFY_PACKAGE.ps1`: package integrity and scientific-metadata checks.

## 10. Machine-readable multiple-testing metadata

```json
{
  "method": "Holm step-down within three pre-specified families",
  "families": {
    "four_primary_model_auc_tests": {
      "raw_p_values": {
        "M2a: Raw GNSS ZTD-Only (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 0.73,
        "M2c: Baseline-Calibrated ERA5 Residual (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 0.2,
        "M3: Quiet F10.7-Adj. GIM VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 0.8,
        "M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 0.62
      },
      "holm_adjusted_p_values": {
        "M2a: Raw GNSS ZTD-Only (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 1.0,
        "M2c: Baseline-Calibrated ERA5 Residual (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 0.8,
        "M3: Quiet F10.7-Adj. GIM VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 1.0,
        "M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)": 1.0
      }
    },
    "three_distinct_physical_endpoint_tests": {
      "raw_p_values": {
        "raw_gnss_ztd_q95": 0.7288,
        "calibrated_era5_residual_q95": 0.4866,
        "quiet_adjusted_vtec_q95": 0.7026
      },
      "holm_adjusted_p_values": {
        "raw_gnss_ztd_q95": 1.0,
        "calibrated_era5_residual_q95": 1.0,
        "quiet_adjusted_vtec_q95": 1.0
      }
    },
    "two_primary_model_comparisons": {
      "raw_p_values": {
        "M2c_vs_M2a": 0.2032,
        "M4_vs_M3": 0.0171
      },
      "holm_adjusted_p_values": {
        "M2c_vs_M2a": 0.2032,
        "M4_vs_M3": 0.0342
      }
    }
  },
  "duplicate_policy": "M4 physical tests repeat M2c residual and M3 VTEC measurements on the same cohort and are not recounted.",
  "auc_permutation_resolution_warning": "The four primary AUC tests currently use 99 refitted permutations as a computational pilot. Minimum attainable Monte Carlo p-value is 0.01; this is not final confirmatory resolution."
}
```

## 11. Reproducibility note

This report is written by the v004 script from the values calculated
during that run. It should be distributed together with the CSV/JSON
outputs and the checksum manifest. Do not interpret this report as
evidence that the benchmark has run until the output package exists
and `VERIFY_PACKAGE.ps1` passes.

