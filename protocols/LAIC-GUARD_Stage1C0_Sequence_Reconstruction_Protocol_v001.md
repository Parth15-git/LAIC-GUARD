# LAIC-GUARD Stage 1C.0 — Earthquake Sequence Reconstruction Protocol

**Protocol ID:** `LAIC-GUARD-STAGE1C0-SEQ-RECON-v001`  
**Version:** 001  
**Prepared:** 2026-11-08  
**Status:** Draft for review — not yet frozen  
**Study target population:** 1,186 USGS ComCat candidate events, 2000-01-01 through 2025-12-31 UTC, initial query threshold M≥6.5  
**Repository baseline:** Stage 1B commit `6d969422edaf24cf9fa10c0827e8c6c675360819`

---

## 1. Purpose and decision boundary

This protocol defines how LAIC-GUARD will reconstruct retrospective earthquake sequences around the large-earthquake candidate population. It is a protocol for data acquisition, event-relationship analysis, uncertainty handling and validation. It does **not** predict earthquakes, determine physical causation, or authorize changes to the frozen Stage 1A/1B catalogue.

The Stage 1A candidate catalogue remains the target population. Supporting events below M6.5 are acquired in a separate supporting catalogue so that smaller foreshocks, aftershocks and swarm activity are not omitted merely because they are below the target-catalogue threshold.

A statistical cluster is not automatically proof that all of its earthquakes share one physical source process. A ComCat association/disassociation product is an administrative catalogue instruction, not by itself a tectonic sequence label. Those concepts must remain separate in all tables and reports.

### Explicit non-goals for Stage 1C.0

- No supporting catalogue downloads.
- No event merging, splitting, removal, re-identification or candidate-catalogue edits.
- No assignment of `sequence_id`, mainshock, foreshock or aftershock labels.
- No declaration that an unclustered event is physically independent.
- No use of retrospective sequence labels as forecasting predictors.

## 2. Fixed target population and separate supporting population

### 2.1 Target population

The frozen target file is `metadata/event_catalogue_v002.csv` (1,186 rows), covering 2000-01-01 through 2025-12-31 UTC, originally selected using the USGS ComCat query threshold `minmagnitude=6.5` and earthquake event type. It remains unchanged throughout Stage 1C.

The Stage 1A audit found that some candidate records have magnitude labels other than an explicit moment-magnitude subtype. Therefore, inclusion in the original query is not to be silently reinterpreted as a confirmed Mw≥6.5 observation. Preserve the reported magnitude, magnitude type, source and the Stage 1A screening fields. Magnitude-family adjudication remains a distinct field from sequence membership.

### 2.2 Supporting population

Create a separate event-level supporting catalogue containing smaller earthquakes and sufficient temporal context around each target event. The supporting population is used only to identify candidate relationships and sequence context. It must never overwrite or expand `event_catalogue_v002.csv`.

USGS ComCat is the initial primary source because it provides a documented FDSN Event Web Service and detailed event products. However, USGS documentation notes that historic regional network catalogues have not all been fully loaded into ComCat. Consequently, global completeness cannot be assumed; regional/time-dependent coverage must be assessed, and suitable independent catalogues may be considered for validation or documented supplementation.

## 3. Temporal scope and right-censoring

The target-event period remains 2000-01-01 through 2025-12-31 UTC.

For the initial supporting-catalogue coverage audit, test a pre-target context beginning **1990-01-01 UTC** and continuing through the actual retrieval end time. The ten-year pre-context is an initial coverage choice, not a physical sequence boundary. Sensitivity analyses must compare shorter and longer pre-contexts (at least 5, 10 and 20 years where source coverage permits).

The post-event observation window ends at the actual data-extraction cutoff and must be recorded in UTC. Events near that cutoff are right-censored: the absence of later aftershocks in the downloaded window is not evidence that the sequence has ended. For targets near the end of 2025, report the available follow-up duration explicitly. Do not invent a fixed aftershock duration for every mainshock.

For each candidate sequence, retain `observation_start_utc`, `observation_end_utc`, `followup_duration_days`, and `right_censored` fields.

## 4. Supporting-catalogue acquisition protocol

### 4.1 Count-first retrieval

Before downloading event rows, use the USGS FDSN Event Web Service `count` method with the same selection parameters planned for `query`. The service documentation states that `count` accepts the same parameters as `query`.

The USGS service limit is 20,000 events per query. Every data request must remain within that limit. Use a conservative operational ceiling below 20,000; recursively subdivide time intervals (year → month → day, as needed) when a count approaches the ceiling. Never silently accept a truncated result.

### 4.2 Threshold reconnaissance only

During the first coverage audit, obtain counts for candidate lower-magnitude thresholds such as M≥4.0, M≥4.5 and M≥5.0 across representative year/time and geographic strata. These are **planning thresholds only**. They do not pre-approve a universal supporting-catalogue threshold.

Choose the minimum supporting magnitude only after assessing regional/time-dependent magnitude completeness, retrieval volume, catalogue quality and sequence-method stability. A global threshold must not be assumed complete merely because it is computationally convenient.

### 4.3 Query fields and provenance

For each request, preserve:

- Exact request URL and all query parameters.
- UTC start/end bounds, minimum/maximum magnitude, event type, output format, sort order, and limit.
- Count response and retrieval timestamp.
- HTTP status, retry history and response metadata where available.
- Raw response bytes, byte size and SHA-256.
- A sidecar linking each raw file to the query and the manifest.

Use `eventtype=earthquake`, explicit UTC boundaries and a deterministic time ordering. Use GeoJSON for the initial reproducible pipeline unless a pilot demonstrates a justified need for another format. Record API/service version information where available.

Use conservative request pacing, bounded retries and exponential backoff for transient service failures. A failed, partial or count-mismatched query must be marked failed and retried or subdivided; it must not be silently treated as zero events.

### 4.4 ComCat fields and product-version handling

Preserve the ComCat preferred event ID and full `ids` alias string, plus event time, latitude, longitude, depth, magnitude, magnitude type, magnitude source, location source, horizontal/depth/magnitude uncertainty fields where present, review status, event type, and update time.

For detailed event records, preserve product source, type, code, update time, preferred weight, status and relevant origin/magnitude details. ComCat products are versioned by source, type, code and update time; a later version supersedes an earlier version for that product identity. Do not flatten this provenance into one untraceable value.

Retain the Stage 1B identity audit decisions as catalogue-identity evidence. Do not use a time/distance coincidence alone to merge event IDs. Alias connectivity and physical-event identity remain separate questions.

## 5. Magnitude and event-quality policy

1. Store the originally reported magnitude value, magnitude type (`magType`), magnitude contributor/source and uncertainty without alteration.
2. Do not treat `mb`, `ms`, `ml`, `md`, generic `mw`, and explicit moment-magnitude subtypes as interchangeable without a documented, validated conversion and uncertainty model.
3. For mainshock ranking, prefer a harmonized moment-magnitude estimate only when the available evidence supports it. Preserve explicit subtypes such as `mww`, `mwc`, `mwb` and `mwr` separately in the source fields. A generic `mw` label remains distinguishable from explicit subtypes.
4. If no defensible common magnitude estimate exists, mark the mainshock ordering as magnitude-incomparable or uncertain rather than forcing a ranking.
5. Preserve origin/location quality information and missingness. Do not impute missing depth or uncertainty silently.
6. Assess magnitude completeness (`Mc`) by region and time window using more than one suitable frequency-magnitude method where sample size permits (for example, maximum curvature and goodness-of-fit/b-value stability methods). Report method disagreement and uncertainty. Sparse regions/windows are `Mc_unresolved`, not automatically assigned a global value.

## 6. Sequence reconstruction methods

No single method is treated as ground truth. The protocol uses complementary methods and retains each method's output separately.

### 6.1 Primary candidate method: space-time-magnitude nearest-neighbour (NN)

For an earlier event `i` and later event `j`, use a documented space-time-magnitude proximity of the form:

`eta_ij = t_ij * r_ij^d_f * 10^(-b * m_i)`, for `t_ij > 0`.

Here `t_ij` is elapsed time, `r_ij` is the selected spatial separation, `m_i` is the earlier event's magnitude on the declared scale, `b` is the Gutenberg–Richter b-value, and `d_f` is the spatial correlation/fractal dimension. Each later event's nearest preceding neighbour is its candidate parent under this construction.

Implementation requirements:

- Declare units, logarithm base, spatial-distance definition, b-value estimation window and `d_f` estimation method in the code and report.
- Estimate or justify `b` and `d_f` using regional/time-specific data above the assessed completeness threshold; do not silently fix both to 1 globally.
- Calibrate the clustered/background separation from the observed nearest-neighbour distribution and appropriate synthetic/null catalogues. Do not select an arbitrary universal `eta` cutoff without sensitivity evidence.
- Preserve parent-child edges and the full directed forest/tree output, not only a final cluster label.
- Use epicentral distance as the initial comparable baseline if depth quality is heterogeneous; test hypocentral/3-D distance as a sensitivity analysis where depth quality supports it.
- Keep low-quality, missing or uncertain locations visible and test their influence.

The published Zaliapin–Ben-Zion method used nearest-neighbour distances in space-time-energy and evaluated stability against ETAS synthetic catalogues, magnitude cutoffs, catalogue incompleteness and location errors. Their 2013 identification study used a relocated Southern California catalogue; their 2016 work applied nearest-neighbour clustering to a global catalogue. These studies motivate the method but do not establish that one parameterization transfers unchanged to every region.

### 6.2 Independent comparator: Reasenberg-style interaction clustering

Implement a documented Reasenberg (1985)-style physical interaction/second-order-moment method as a separate comparator. Record the exact algorithm version, parameters, units, and any implementation source. Do not invent defaults or describe an approximate time-distance window as the Reasenberg algorithm.

If a faithful and testable implementation cannot be established, record this comparator as unavailable and do not imply it was run.

### 6.3 Simple baseline: time-distance windows

Implement a transparent time-distance window baseline for comparison and sensitivity analysis. Parameters must be explicit and tested over a predeclared grid. This baseline is not the primary scientific classifier and must not be represented as physically definitive.

### 6.4 Synthetic/null calibration

Where feasible, generate ETAS-based synthetic catalogues or another explicitly justified null model to examine false clustering, sensitivity to missing events and parameter stability. Synthetic catalogues test method behaviour; they do not supply ground-truth labels for real earthquakes.

## 7. Cluster and event-role vocabulary

Keep method-specific outputs and consensus outputs separate. Use the following vocabulary only after the method outputs have been reviewed:

- **Cluster member:** assigned to a statistical cluster by a named method.
- **Candidate parent / offspring:** directed nearest-neighbour relation under the NN method; not automatically a causal claim.
- **Mainshock candidate:** largest harmonized magnitude in the cluster when the magnitude ranking is sufficiently comparable and uncertainty does not make the ordering indeterminate.
- **Foreshock:** a cluster member preceding the retrospectively identified mainshock. This is a retrospective role, not a real-time label available before the mainshock.
- **Aftershock:** a cluster member following the retrospectively identified mainshock under the declared cluster method.
- **Swarm-like / burst-like / mixed:** descriptive cluster morphology based on predeclared topology/temporal-spatial metrics; do not force a mainshock in a cluster without a clear dominant event.
- **Singleton / unlinked under method:** not linked by a specified method under its parameters. This does **not** mean tectonically or physically independent.
- **Unresolved / method-dependent:** methods disagree materially, the catalogue is incomplete/uncertain, or event identity/magnitude/location evidence is inadequate.

When two or more large events have indistinguishable or uncertain magnitude ranking, retain multiple mainshock candidates or mark the role unresolved. Do not use the event's later impact or outcome to choose a mainshock retrospectively unless that criterion is explicitly part of a separately named descriptive analysis.

## 8. Agreement, uncertainty and sensitivity analysis

For every target event, store the output of each clustering method and a separate consensus/adjudication status. At minimum test:

- Supporting magnitude thresholds selected from the Mc audit; include threshold sensitivity.
- Regional/time-window `b` and `d_f` estimates and their uncertainty.
- Epicentral versus hypocentral distance where justified by depth quality.
- 5-, 10- and 20-year pre-context where source coverage permits.
- Alternative NN cluster separation/calibration choices.
- Reasenberg parameter sensitivity (if faithfully implemented).
- Time-distance baseline parameter grid.
- High-quality-location subset versus all eligible records.
- Exclusion or separate treatment of uncertain magnitude types and low-quality origins.

Report method agreement (including event-level agreement and pairwise cluster co-membership measures), assignment stability under sensitivity runs, number of unresolved cases, and region/time coverage limitations. Disagreement is a result to preserve, not an inconvenience to erase.

## 9. Validation and leakage controls

1. Validate the pipeline on documented regional case studies and synthetic catalogues before applying it globally.
2. Compare cluster outputs from independent methods; do not use one method's output as the validation truth for another.
3. Where expert or published sequence labels are used, record their source, date, geographic scope and known selection bias.
4. If a forecasting model is later evaluated, group all members of the same reconstructed sequence into the same data partition. Do not allow members of one sequence to leak across training, validation and test sets.
5. Retrospective foreshock/mainshock/aftershock labels are target/analysis labels only. Do not feed information that becomes available after forecast time into predictor features.
6. For any prospective-style feature table, enforce an explicit as-of timestamp and include only data available by that timestamp.

## 10. Required output artifacts for later Stage 1C implementation

The exact filenames may be finalized when the data schema is designed, but the following logical artifacts are mandatory:

- Supporting-catalogue query plan and count audit.
- Raw query responses and request sidecars (outside Git, with manifest hashes).
- Supporting-catalogue event table with preserved identifiers, magnitudes, origins and uncertainties.
- Event identity/alias crosswalk; no silent merges.
- Magnitude-completeness report by region/time window.
- Method-specific NN parent-child edge table and cluster assignments.
- Reasenberg-style comparator outputs, if implemented faithfully.
- Time-distance baseline outputs.
- Parameter/sensitivity results and method-agreement table.
- Event-role and consensus adjudication table with unresolved statuses retained.
- Reproducible scripts, run metadata, artifact register entries and SHA-256 checksums.

## 11. Stage gates

### Gate 1C.0 — Protocol approval

This document is reviewed, corrections are versioned, scope and decision boundaries are agreed, and the protocol is committed. No supporting catalogue acquisition or sequence assignment is authorized before this gate is passed.

### Gate 1C.1 — Acquisition readiness

Count-first reconnaissance, query subdivision design, temporal context, magnitude-threshold candidates, output schema and manifest plan are approved. No event data are downloaded until the plan passes the count/limit checks.

### Gate 1C.2 — Catalogue quality and completeness

Raw bytes, query metadata, manifest, counts, duplicates/aliases, magnitude type, location quality and Mc estimates are audited before clustering.

### Gate 1C.3 — Method validation

Method implementations and parameter choices pass unit tests, known-case checks, synthetic/null tests and sensitivity reporting before global sequence assignments are generated.

### Gate 1C.4 — Sequence catalogue freeze

Method-specific outputs, consensus rules, unresolved cases and provenance are reviewed. The resulting sequence catalogue is a new versioned derivative; the Stage 1A/1B candidate catalogue remains unchanged.

## 12. Initial source references

1. **USGS FDSN Event Web Service API documentation** — query/count methods, query parameters and service constraints: https://earthquake.usgs.gov/fdsnws/event/1/swagger.json
2. **USGS ComCat documentation** — catalogue scope and documented data availability limitations: https://www.usgs.gov/programs/earthquake-hazards/anss-comprehensive-earthquake-catalog-comcat-documentation
3. **USGS “How Products Work in ComCat”** — product version identity and preferred-product behaviour: https://earthquake.usgs.gov/data/catalog/products.php
4. **Reasenberg, P. (1985)**, “Second-order moment of central California seismicity, 1969–1982,” *Journal of Geophysical Research*, 90(B7), 5479–5495. https://doi.org/10.1029/JB090iB07p05479
5. **Zaliapin, I. & Ben-Zion, Y. (2013)**, “Earthquake clusters in southern California, I: Identification and stability,” *Journal of Geophysical Research: Solid Earth*, 118, 2847–2864. https://doi.org/10.1002/jgrb.50179
6. **Zaliapin, I. & Ben-Zion, Y. (2013)**, “Earthquake clusters in southern California, II: Classification and relation to physical properties of lithosphere,” *Journal of Geophysical Research: Solid Earth*, 118, 2865–2877. https://doi.org/10.1002/jgrb.50178
7. **Zaliapin, I. & Ben-Zion, Y. (2016)**, “A global classification and characterization of earthquake clusters,” *Geophysical Journal International*, 207(1), 608–634. https://doi.org/10.1093/gji/ggw300
8. **Michael, A. J. (2014)**, “How complete is the ISC-GEM Global Earthquake Catalog?” *Bulletin of the Seismological Society of America*. https://doi.org/10.1785/0120130227
9. **Mignan, A. et al. (2025)**, “Estimating Magnitude Completeness in Earthquake Catalogs: A Comparative Study of Catalog-Based Methods,” *Journal of Geophysical Research: Solid Earth*. https://doi.org/10.1029/2025JB031441

---

## Version history

| Version | Date | Change | Status |
|---|---|---|---|
| v001 | 2026-11-08 | Initial protocol draft covering supporting catalogue, completeness, sequence methods, uncertainty, validation and leakage controls. | Draft for review; not frozen |

**Protocol freeze rule:** Any material change to target population, supporting-catalogue time range, magnitude policy, clustering algorithms, parameter calibration, event-role definitions or validation controls requires a new protocol version and a written rationale. Do not edit a frozen version in place.
