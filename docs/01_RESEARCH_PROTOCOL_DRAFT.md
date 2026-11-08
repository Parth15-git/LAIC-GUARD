# Research Protocol — Draft v0.1 (NOT FROZEN)

## 1. Main question

Do independent lithospheric, atmospheric, ionospheric and electromagnetic observations contain statistically unusual, spatially coherent and temporally coordinated information before earthquakes after conditioning on known environmental, geomagnetic, solar and measurement confounders?

## 2. Candidate hypotheses

- H1 — Independent anomaly: domain anomalies occur more frequently or with different structure in pre-event periods than in matched controls.
- H2 — Cross-layer coordination: independent domains show spatially and temporally coherent behaviour beyond chance alignment.
- H3 — Incremental predictive information: a multimodal model improves out-of-sample forecasts beyond seismicity-only and environmental baselines.
- H4 — Generalization: findings survive geographic, temporal, seasonal and solar-cycle holdouts.

These hypotheses and their primary metrics must be finalized before analysis of event-aligned outcomes.

## 3. Provisional event catalogue scope

A starting candidate is shallow Mw >= 6.5 events during 2000–2025. This is a **provisional data-audit rule**, not a final inclusion rule. Define and document:
- Magnitude threshold and magnitude-type handling.
- Depth threshold.
- Event-type exclusions.
- Geographic/tectonic scope.
- Sequence grouping rules.
- Catalogue completeness requirements.
- Minimum available observations per domain.
- Treatment of dependent events and multiple stations.

Do not hand-select events because a signal appears interesting. Generate candidates algorithmically from a declared catalogue query and store the query/response metadata.

## 4. Observation windows

Candidate windows such as 1, 3, 7, 14 and 30 days may be explored during development. One primary window and a limited, predeclared secondary analysis must be frozen before confirmatory testing. Account for multiple comparisons.

## 5. Controls

- Matched quiet-time windows.
- Matched geographic control regions.
- Geomagnetically comparable reference stations where suitable.
- Meteorological conditioning.
- Solar/geomagnetic controls.
- Instrument/data-quality screening.
- Sequence-aware earthquake catalog models.

## 6. Validation

- Event/sequence-blocked cross-validation.
- Chronological holdout.
- Leave-one-region-out evaluation.
- Solar-cycle or geomagnetic-regime holdout where sample size permits.
- Pseudo-prospective replay using only information available at each historical time.
- Prospective frozen evaluation only after a complete protocol is registered.

Never randomly split rows from the same earthquake sequence across training and test sets.

## 7. Baselines

At minimum:
- Historical/constant-rate or declared reference forecast.
- ETAS or another suitable seismicity-only baseline.
- Environmental/space-weather-only model.
- Individual-domain models.
- Multimodal fusion model.

The main claim is based on incremental performance over the seismicity-only baseline, not on accuracy alone.

## 8. Metrics

Report event recall, precision-recall AUC, Brier score, log score, calibration, false alarms per station-year or region-time, lead-time distribution, Molchan-style miss/alarm trade-off, and uncertainty intervals where appropriate.

## 9. Missingness and quality

Missing data remain missing. No silent zero-imputation, forward-fill or backward-fill. Every feature must carry quality and coverage metadata. The model may abstain if coverage is inadequate.

## 10. Freeze requirements

Before confirmatory evaluation, freeze:
- Event inclusion rule and catalogue version.
- Sequence grouping.
- Spatial radii/control selection.
- Primary observation window.
- Feature definitions.
- Confounder rules.
- Threshold calibration procedure.
- Model hyperparameter search plan.
- Test splits and metrics.
- Exclusion rules.

Record every change in `03_DECISIONS_LOG.md`.
