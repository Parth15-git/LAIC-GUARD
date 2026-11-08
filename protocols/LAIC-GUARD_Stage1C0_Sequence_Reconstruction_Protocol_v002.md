# LAIC-GUARD Stage 1C.0 — Earthquake Sequence Reconstruction Protocol

**Protocol ID:** `LAIC-GUARD-STAGE1C0-SEQ-RECON-v002`  
**Version:** 002  
**Prepared:** 2026-11-08  
**Status:** Draft for review — not yet frozen  
**Supersedes for review:** v001 (preserved unchanged)  
**Study target population:** 1,186 USGS ComCat candidate events, 2000-01-01 through 2025-12-31 UTC, initial query threshold `minmagnitude=6.5`  
**Repository baseline:** Stage 1B commit `6d969422edaf24cf9fa10c0827e8c6c675360819`

---

## 1. Purpose and decision boundary

This protocol defines how LAIC-GUARD will reconstruct retrospective earthquake sequences around the large-earthquake candidate population. It covers supporting-catalogue acquisition, event-relationship analysis, magnitude completeness, uncertainty handling, method comparison and validation. It does **not** predict earthquakes, determine physical causation, or authorize changes to the frozen Stage 1A/1B catalogue.

The Stage 1A candidate catalogue remains the target population. Supporting events below the target-catalogue threshold are acquired in a separate supporting catalogue so that smaller foreshocks, aftershocks and swarm activity are not omitted merely because they are below the target-catalogue threshold.

A statistical cluster is not automatically proof that all of its earthquakes share one physical source process. A ComCat association/disassociation product is an administrative catalogue instruction, not by itself a tectonic sequence label. Those concepts must remain separate in all tables and reports.

### 1.1 Explicit non-goals for Stage 1C.0

- No supporting-catalogue downloads.
- No event merging, splitting, removal, re-identification or candidate-catalogue edits.
- No assignment of `sequence_id`, mainshock, foreshock or aftershock labels.
- No declaration that an unclustered event is physically independent.
- No use of retrospective sequence labels as forecasting predictors.
- No claim that ComCat preferred magnitude values or query counts represent a homogeneous Mw catalogue.

### 1.2 Governing principles

1. Preserve source observations and catalogue identities before deriving relationships.
2. Keep target-population membership, supporting-catalogue membership, ComCat identity relationships and statistical sequence membership as distinct concepts.
3. Preserve method-specific results and uncertainty; do not force a consensus label where the evidence is unstable.
4. Treat catalogue completeness and location/magnitude quality as part of the sequence method, not as a post-processing footnote.
5. Make every acquisition, transformation, parameter choice and adjudication reproducible from versioned code and provenance records.

## 2. Fixed target population and separate supporting population

### 2.1 Target population

The frozen target file is `metadata/event_catalogue_v002.csv` (1,186 rows), covering 2000-01-01 through 2025-12-31 UTC, originally selected using the USGS ComCat query threshold `minmagnitude=6.5` and earthquake event type. It remains unchanged throughout Stage 1C.

The Stage 1A audit found that some candidate records have magnitude labels other than an explicit moment-magnitude subtype. Inclusion in the original query is therefore not to be silently reinterpreted as a confirmed Mw≥6.5 observation. Preserve the reported magnitude, magnitude type, source and Stage 1A screening fields. Magnitude-family adjudication remains a distinct field from sequence membership.

### 2.2 Supporting population

Create a separate event-level supporting catalogue containing smaller earthquakes and sufficient temporal context around each target event. The supporting population is used to identify candidate relationships and sequence context. It must never overwrite or expand `event_catalogue_v002.csv`.

USGS ComCat is the initial primary source because it provides a documented FDSN Event Web Service and detailed event products. However, historic regional network catalogues have not all been fully loaded into ComCat. Global completeness cannot be assumed; regional/time-dependent coverage must be assessed, and suitable independent catalogues may be considered for validation or documented supplementation.

### 2.3 Distinguish API magnitude screening from a harmonized magnitude threshold

The FDSN `minmagnitude` parameter is a numerical query filter. It is **not** a filter for a specific magnitude scale such as Mw. Therefore, reconnaissance queries at `minmagnitude=4.0`, `4.5` and `5.0` must be described as **ComCat numerical preferred-magnitude screening thresholds**, not as Mw≥4.0, Mw≥4.5 or Mw≥5.0 counts.

The count and query requests must use identical parameters. For each returned event, retain the query/preferred magnitude and `magType`. Where a detailed event request is made, request and preserve all available magnitude estimates (`includeallmagnitudes=true`) and their contributors/origins where supported. Do not assume that the query threshold has selected on every alternative magnitude attached to an event.

After retrieval, produce distributions by magnitude type, source and time/region. A magnitude-harmonized analytical subset may be formed only after a documented conversion or comparison procedure with uncertainty. Keep the original ComCat screening population unchanged.

## 3. Temporal scope, censoring and observation windows

### 3.1 Target period and pre-target context

The target-event period remains 2000-01-01 through 2025-12-31 UTC.

To make a 20-year pre-context sensitivity analysis possible for the earliest target events beginning in 2000, the **planned supporting-catalogue start is 1980-01-01 UTC**, subject to actual source availability and the Stage 1C.1 coverage audit. This is a data-acquisition start target, not a physical sequence boundary. The earlier v001 proposal of 1990-01-01 would not provide a full 20-year pre-context for target events in 2000–2009; v002 corrects that limitation.

Compare pre-context windows of at least 5, 10 and 20 years where source coverage permits. For each target event, calculate the available pre-context explicitly. If a requested window is not covered by the source, mark that sensitivity analysis unavailable for that target; do not imply that the window was tested.

### 3.2 Post-event observation and fixed acquisition cutoff

Before the first count reconnaissance, set a single `acquisition_cutoff_utc` in the Stage 1C.1 acquisition plan. All query `endtime` values must be bounded by this fixed cutoff. The cutoff must be recorded as a literal UTC timestamp, not a moving value such as “now”.

Record separately:

- the event-origin time interval requested;
- the `acquisition_cutoff_utc` used as the maximum origin-time bound;
- the count-request timestamp;
- each data-request timestamp;
- the actual data-extraction end timestamp; and
- the ComCat service version and response metadata where available.

A fixed origin-time cutoff does not make ComCat a frozen database snapshot: preferred origins, magnitudes and products can be revised. Count and query requests are not assumed to be atomic. Record their separate timestamps, compare the count response with the retrieved feature count, and preserve/reconcile any discrepancy. Hash the exact raw response bytes.

Events near the acquisition cutoff are right-censored. The absence of later aftershocks in the downloaded window is not evidence that the sequence has ended. Do not invent a fixed aftershock duration for every mainshock.

### 3.3 Left-censoring and incomplete sequence history

A sequence may have begun before the supporting catalogue starts. The first event observed in the downloaded interval must not automatically be treated as the sequence's physical or statistical beginning.

For every target event and every derived candidate cluster, retain at minimum:

- `observation_start_utc`;
- `observation_end_utc`;
- `pre_context_duration_days`;
- `followup_duration_days`;
- `left_censored`;
- `right_censored`;
- `left_censor_reason`; and
- `right_censor_reason`.

Set `left_censored=true` when the requested pre-context is unavailable or the cluster may connect to an event before the available catalogue boundary. Set `right_censored=true` when the requested follow-up is cut off by the fixed extraction end. Preserve “unknown” or “not assessable” states where evidence is insufficient; do not coerce them to false.

A missing preceding nearest neighbour at the catalogue boundary is a boundary condition, not proof that an event is an independent background event. Report the share of targets/clusters affected by left and right censoring.

## 4. Supporting-catalogue acquisition protocol

### 4.1 Count-first retrieval

Before downloading event rows, use the USGS FDSN Event Web Service `count` method with the same selection parameters planned for `query`. The service documentation states that `count` accepts the same parameters as `query`.

The documented service limit is 20,000 events per query. Use a conservative operational ceiling below 20,000. If a count approaches that ceiling, recursively subdivide time intervals (year → month → day, as needed). Every data request must remain within the service limit. Never silently accept a truncated result.

For every request, compare the count result with the number of parsed GeoJSON features. A mismatch, HTTP error, malformed response, partial response or unexplained count change must be recorded as a failed/inconsistent retrieval and retried or subdivided. Do not silently reinterpret such a result as zero events.

### 4.2 Threshold reconnaissance only

During the first coverage audit, obtain counts at candidate numerical `minmagnitude` thresholds 4.0, 4.5 and 5.0 across representative time and geographic strata. These are **planning thresholds for ComCat's numerical magnitude filter only**. They do not pre-approve a universal supporting-catalogue threshold and do not represent Mw thresholds.

Choose the minimum analytical supporting magnitude only after assessing regional/time-dependent magnitude completeness, magnitude-type mix, retrieval volume, catalogue quality and sequence-method stability. A global threshold must not be assumed complete merely because it is computationally convenient.

### 4.3 Query fields and provenance

For each request, preserve:

- exact request URL and all query parameters;
- UTC start/end bounds and the fixed `acquisition_cutoff_utc`;
- minimum/maximum numerical magnitude filters, event type, output format, sort order and limit;
- count response, count timestamp and returned feature count;
- retrieval timestamp, HTTP status and retry history;
- service/version response where available;
- raw response bytes, byte size and SHA-256; and
- a sidecar linking each raw file to the query and manifest.

Use `eventtype=earthquake`, explicit UTC boundaries and deterministic time ordering. Use GeoJSON for the initial reproducible pipeline unless a pilot demonstrates a justified need for another format. Record API/service version information where available.

Use conservative request pacing, bounded retries and exponential backoff for transient service failures. Preserve failed-attempt metadata. A query failure must never be represented as an empty catalogue interval.

### 4.4 ComCat fields and product-version handling

Preserve the ComCat preferred event ID and full `ids` alias string, event time, latitude, longitude, depth, query/preferred magnitude, magnitude type, magnitude source, location source, horizontal/depth/magnitude uncertainty fields where present, review status, event type and update time.

For detailed event records, preserve all available origin and magnitude records where supported, plus product source, type, code, update time, preferred weight, status and relevant origin/magnitude details. The API's `includeallmagnitudes` parameter is available for event-specific/all-magnitude retrieval; preserve the distinction between the preferred value and alternative magnitude estimates.

ComCat products are versioned by source, type, code and update time. A later version can supersede an earlier version for that product identity. Do not flatten this provenance into one untraceable value.

Retain the Stage 1B identity audit decisions as catalogue-identity evidence. Do not use a time/distance coincidence alone to merge event IDs. Alias connectivity, ComCat's sub-event instructions and physical-event identity remain separate questions.

## 5. Magnitude, location and event-quality policy

1. Store the originally reported magnitude value, magnitude type (`magType`), magnitude contributor/source, associated origin where available, and uncertainty without alteration.
2. Do not treat `mb`, `ms`, `ml`, `md`, generic `mw`, and explicit moment-magnitude subtypes as interchangeable without a documented, validated conversion and uncertainty model.
3. For mainshock ranking, prefer a harmonized moment-magnitude estimate only when the available evidence supports it. Preserve explicit subtypes such as `mww`, `mwc`, `mwb` and `mwr` separately in the source fields. A generic `mw` label remains distinguishable from explicit subtypes.
4. If no defensible common magnitude estimate exists, mark the mainshock ordering as `magnitude_incomparable` or `magnitude_order_uncertain` rather than forcing a ranking.
5. Preserve origin/location quality information and missingness. Do not impute missing depth or uncertainty silently.
6. Assess magnitude completeness (`Mc`) by region and time window using more than one suitable method where sample size permits (for example, maximum curvature and goodness-of-fit/b-value stability methods). Consider probabilistic methods that represent a gradual detection transition rather than assuming an infinitely sharp threshold. Report method disagreement and uncertainty. Sparse regions/windows are `Mc_unresolved`, not automatically assigned a global value.
7. **Assess short-term, sequence-dependent completeness.** Immediately after large earthquakes, overlapping signals, network saturation and analyst workload can reduce the detection of small events. Where event density and data permit, estimate or bound `Mc` in short post-mainshock time windows as a function of time since the mainshock and region. Compare these estimates with longer-window background `Mc`. If short-window estimates are too sparse or unstable, mark them unresolved and test threshold sensitivity rather than asserting completeness.
8. Magnitude-type harmonization and `Mc` estimation are separate operations. A low numerical `Mc` does not prove that different magnitude scales are equivalent.

## 6. Sequence reconstruction methods

No single method is treated as ground truth. Method-specific outputs, parameterizations and limitations must be retained separately. The method comparison is a structured sensitivity analysis, not a majority-vote contest.

### 6.1 Primary candidate method: space-time-magnitude nearest-neighbour (NN)

For an earlier event `i` and later event `j`, use a documented space-time-magnitude proximity of the form:

`eta_ij = t_ij * r_ij^d_f * 10^(-b * m_i)`, for `t_ij > 0`.

Here `t_ij = t_j - t_i` is elapsed time, `r_ij` is the selected spatial separation, `m_i` is the earlier event's magnitude on the declared analytical scale, `b` is the Gutenberg–Richter b-value, and `d_f` is the spatial correlation/fractal dimension. Each later event's nearest preceding neighbour is its candidate parent under this construction. This is a statistical parent relation, not a demonstrated causal relation.

#### 6.1.1 Units, distance and magnitude scale

- For the primary implementation, use elapsed time in years and epicentral distance in kilometres to match the published formulation unless a documented reproduction test justifies another convention.
- Use `log10(eta)` for numerical diagnostics and threshold modelling. Preserve the raw components (`t`, `r`, `m`, `b`, `d_f`) and the exact units used in every run.
- The numerical value and threshold of `eta` depend on units and parameterization. Values from runs with different units or parameter scales must not be compared as if they were identical.
- Use epicentral distance as the initial comparable baseline when depth quality is heterogeneous. Test hypocentral/3-D distance as a sensitivity analysis only where depth quality supports it.
- Treat zero-distance/duplicate-coordinate cases, coordinate rounding and exact ties explicitly. Do not add an undocumented arbitrary epsilon to make `log10(eta)` finite. Preserve a zero-distance flag; use documented precision-aware handling and a deterministic, recorded tie rule. Exclude mathematically non-finite values from log-mixture fitting while retaining the underlying event/edge records for review.

#### 6.1.2 Parameter estimation and regional assignment

Estimate or justify `b` and `d_f` using regional/time-specific data above the assessed completeness threshold; do not silently fix both to 1 globally. Record estimator, sample, time window, region ID, uncertainty and exclusions for each parameter estimate.

The geographic analysis-region framework and its version must be selected and documented before fitting regional parameters. It must not be drawn after examining desired cluster results. A tectonic-region boundary must not automatically prohibit a cross-boundary candidate parent link.

For a child event `j`, the **primary regional parameter convention** is to use the parameter set assigned to the predeclared region containing the child event, because the NN decision is made for that child. For links whose parent lies in a different region, preserve a `cross_region_parent_link=true` flag and run at least two sensitivity alternatives: (a) the parent-region parameter set, and (b) a pooled/region-independent parameter set where statistically defensible. If the parent/child/pooled variants materially change the parent or cluster membership, classify the relationship as parameter-sensitive or unresolved.

Where a region has insufficient complete events to estimate `b` or `d_f` stably, do not fabricate a regional estimate. Mark the parameter `unresolved`; report any pooled fallback as a separately named sensitivity run, never as an unqualified regional estimate.

#### 6.1.3 Nearest-neighbour forest construction

For each event `j`, evaluate eligible preceding events `i` within the explicitly declared catalogue and geographic/search scope, compute `eta_ij`, and retain the minimum as the candidate parent. Each non-initial event has one candidate parent under the complete-catalogue construction; the first event or a boundary-limited event may have no eligible preceding event. Preserve all candidate-parent metadata and the selected edge, not only a final cluster ID.

The parent-child edges form a directed acyclic nearest-neighbour tree/forest structure under strictly increasing event time. Preserve event time ties and duplicated origin-time handling explicitly; do not create cycles. Store edge direction, parent ID, child ID, time separation, distance, magnitude scale/value, `b`, `d_f`, `eta`, `log10_eta`, region assignment, location-quality flags and run ID.

#### 6.1.4 Cluster/background separation and calibration

The published Zaliapin–Ben-Zion workflow connects each event to its nearest preceding neighbour, then removes weak (large-`eta`) links to create a spanning forest. The separation between clustered and background links is commonly estimated from the bimodal distribution of nearest-neighbour distances, for example with a two-component Gaussian mixture on `log10(eta)` or on the two normalized log-components. It is not a universal fixed `eta` value.

For LAIC-GUARD:

1. Predeclare a primary calibration model: a two-component Gaussian mixture fitted to `log10(eta)` within each eligible analysis region/time stratum, with the one-component alternative retained for model comparison.
2. Record fitting initialization, convergence diagnostics, component weights, means/variances, model-selection diagnostics (including BIC where applicable), and the estimated intersection of component densities. The candidate separation threshold `eta_0` is the density intersection between the fitted cluster and background modes, not a hand-selected universal constant.
3. Use the two-dimensional mixture on `(log10(T), log10(R))` as a method sensitivity analysis where sample size supports it. Define the normalized components and split parameter `q` explicitly (`T = t * 10^(-q*b*m_i)`, `R = r^d_f * 10^(-(1-q)*b*m_i)`, so `eta=T*R`) and preserve the selected `q` value.
4. Bootstrap or otherwise resample the eligible nearest-neighbour sample to quantify threshold uncertainty and edge/cluster assignment stability.
5. Report mode-separation quality, posterior mode probabilities and the proportion of ambiguous assignments. Do not label a regional distribution as bimodal solely because a two-component mixture can be fitted.
6. If the one-component model is not rejected/supported against the two-component alternative, the fit does not converge, the density intersection is not uniquely/meaningfully located between component modes, or the threshold/assignments are unstable under resampling, mark the region/run `NN_separation_unresolved`. Do not force an `eta_0` or cluster/background classification.
7. Remove edges with `eta >= eta_0` only in runs where the separation is supported. The resulting connected components are method-specific NN clusters. Preserve singleton components as `unlinked_under_NN`, not physically independent earthquakes.

The original studies motivate this approach but do not establish that one parameterization, mixture fit or regional boundary transfers unchanged to every region.

### 6.2 Independent comparator: Reasenberg-style interaction clustering

Implement a documented Reasenberg (1985)-style physical interaction/second-order-moment method as a separate comparator. Record the exact algorithm version, parameter names and units, implementation source, source-code hash, compiler/runtime and configuration.

The USGS CLUSTER2000 software release identifies its method as based on Reasenberg (1985), but its documentation notes software/format limitations. It may be evaluated as an implementation candidate; its suitability for this project must be demonstrated, not assumed.

Acceptance requires:

- inspection and archival identification of the exact source version;
- an explicit mapping of implemented parameters to the published method;
- reproducible build/run instructions and source checksum;
- tests on documented known cases or reference outputs;
- time, magnitude, location and input-format compatibility checks; and
- sensitivity analysis over relevant parameters.

Do not invent defaults or describe an approximate time-distance window as the Reasenberg algorithm. If a faithful and testable implementation cannot be established, record this comparator as unavailable and do not imply it was run. Preserve the method's native output semantics; a declustered background catalogue is not automatically equivalent to an NN cluster partition.

### 6.3 Simple baseline: time-distance windows

Implement a transparent time-distance window baseline for comparison and sensitivity analysis. Parameters must be explicit, versioned and tested over a predeclared grid. Include the window definition, whether windows are symmetric/asymmetric in time, whether magnitude enters the window, how overlapping windows are joined, and the deterministic tie/overlap rule.

This baseline is not the primary scientific classifier and must not be represented as physically definitive. Parameter choices must not be tuned against downstream LAIC-GUARD forecasting outcomes.

### 6.4 Synthetic/null calibration

Where feasible, generate ETAS-based synthetic catalogues or another explicitly justified null model to examine false clustering, sensitivity to missing events, location errors, magnitude uncertainty and parameter stability. Record the ETAS parameterization, simulation domain, boundary conditions, random seeds and number of simulations.

Synthetic catalogues test method behaviour; they do not supply ground-truth labels for real earthquakes. Include null/synthetic tests before global assignments are generated.

## 7. Cluster and event-role vocabulary

Keep method-specific outputs and consensus/adjudication outputs separate. Use the following vocabulary only after method outputs have been reviewed:

- **Cluster member:** assigned to a statistical cluster by a named method and parameterization.
- **Candidate parent / offspring:** directed nearest-neighbour relation under the NN method; not automatically a causal claim.
- **Mainshock candidate:** largest harmonized magnitude in the cluster when the magnitude ranking is sufficiently comparable and uncertainty does not make the ordering indeterminate.
- **Foreshock:** a cluster member preceding the retrospectively identified mainshock. This is a retrospective role, not a real-time label available before the mainshock.
- **Aftershock:** a cluster member following the retrospectively identified mainshock under the declared cluster method.
- **Swarm-like / burst-like / mixed:** descriptive cluster morphology based on predeclared topology/temporal-spatial metrics; do not force a mainshock in a cluster without a clear dominant event.
- **Singleton / unlinked under method:** not linked by a specified method under its parameters. This does **not** mean tectonically or physically independent.
- **Unresolved / method-dependent:** methods disagree materially, the catalogue is incomplete/uncertain, or event identity/magnitude/location evidence is inadequate.

When two or more large events have indistinguishable or uncertain magnitude ranking, retain multiple mainshock candidates or mark the role unresolved. Do not use an event's later impact or outcome to choose a mainshock unless that criterion is explicitly part of a separately named descriptive analysis.

### 7.1 Consensus/adjudication status — no majority vote

Do not assign final consensus by simple majority voting among methods. The methods have different assumptions and may produce partitions with different granularity.

Retain at least these distinct status values:

- `METHOD_CONCORDANT`: independently available methods produce materially compatible co-membership/relationship evidence for the target event under the declared comparison scope.
- `SENSITIVITY_STABLE`: the method-specific assignment persists across the predeclared plausible parameter, threshold and catalogue-quality sensitivity runs.
- `METHOD_DEPENDENT`: cluster membership or event role changes materially across methods or parameterizations.
- `UNRESOLVED`: evidence, catalogue completeness, magnitude/location quality, censoring or method calibration is insufficient for a defensible assignment.
- `SINGLETON_UNLINKED_UNDER_METHOD`: no link is assigned by the named method; this is not an independence statement.

The final adjudication table must contain method-specific IDs/labels, pairwise co-membership evidence, sensitivity stability, censoring flags, catalogue-quality flags, rationale and reviewer status. A consensus sequence identifier may be issued only at Gate 1C.4 under a separately reviewed rule; the raw method partitions remain immutable.

## 8. Agreement, uncertainty and sensitivity analysis

For every target event, store the output of each available clustering method and a separate consensus/adjudication status. At minimum test:

- supporting numerical magnitude thresholds and magnitude-type mix selected from the `Mc` audit;
- regional/time-window `b` and `d_f` estimates and their uncertainty;
- child-region, parent-region and pooled parameter conventions for cross-region NN edges;
- epicentral versus hypocentral distance where justified by depth quality;
- 5-, 10- and 20-year pre-context where source coverage permits;
- left/right-censoring and shorter/longer observation windows;
- alternative NN mixture/calibration choices and bootstrap stability;
- one-component versus two-component nearest-neighbour distributions;
- Reasenberg parameter sensitivity, if faithfully implemented;
- time-distance baseline parameter grid;
- high-quality-location subset versus all otherwise eligible records;
- exclusion or separate treatment of uncertain magnitude types and low-quality origins; and
- short-term post-mainshock completeness thresholds versus background `Mc` estimates.

Report method agreement using more than one view:

1. event-level agreement for each target event;
2. pairwise co-membership agreement, including Jaccard similarity where appropriate;
3. partition-level agreement metrics such as adjusted Rand index, with limitations for unequal cluster-size distributions described;
4. assignment stability across bootstrap/sensitivity runs;
5. the number and proportion of method-dependent/unresolved targets; and
6. region/time coverage and censoring limitations.

Do not collapse these measures into one unqualified score. Report the underlying contingency/co-membership tables or reproducible summaries. Disagreement is a result to preserve, not an inconvenience to erase.

## 9. Validation and leakage controls

1. Validate the pipeline on documented regional case studies and synthetic catalogues before applying it globally.
2. Compare cluster outputs from independent methods; do not use one method's output as the validation truth for another.
3. Where expert or published sequence labels are used, record their source, version/date, geographic scope, event-selection rules and known selection bias.
4. If a forecasting model is later evaluated, group all members of the same reviewed sequence into the same data partition. Do not allow members of one sequence to leak across training, validation and test sets. Unresolved relationships should be handled conservatively in partitioning or excluded from the relevant leakage-sensitive analysis with the exclusion documented.
5. Retrospective foreshock/mainshock/aftershock labels are target/analysis labels only. Do not feed information that becomes available after forecast time into predictor features.
6. For any prospective-style feature table, enforce an explicit as-of timestamp and include only data available by that timestamp.
7. Sequence reconstruction and label adjudication must be completed without access to downstream LAIC-GUARD model performance for the same target events, to reduce outcome-informed tuning.

## 10. Required output artifacts for later Stage 1C implementation

The exact filenames may be finalized when the data schema is designed, but the following logical artifacts are mandatory:

- protocol version, approval record and change log;
- supporting-catalogue query plan, count audit and fixed acquisition cutoff;
- raw query responses and request sidecars (outside Git, with manifest hashes);
- supporting-catalogue event table with preserved identifiers, preferred/all magnitudes, origins and uncertainties;
- event identity/alias crosswalk; no silent merges;
- query count versus feature-count reconciliation report;
- magnitude-type and magnitude-completeness report by region/time, including post-mainshock completeness where estimable;
- censoring/observation-window table for each target and candidate cluster;
- method-specific NN parent-child edge table, mixture-calibration results and cluster assignments;
- Reasenberg-style comparator outputs, if implemented faithfully;
- time-distance baseline outputs;
- parameter/sensitivity results and method-agreement/co-membership tables;
- event-role and consensus/adjudication table with unresolved statuses retained;
- synthetic/null catalogue configuration, seeds and validation outputs;
- reproducible scripts, environment/run metadata, artifact-register entries and SHA-256 checksums.

## 11. Stage gates

### Gate 1C.0 — Protocol approval

This document is reviewed, corrections are versioned, scope and decision boundaries are agreed, and the protocol is committed. No supporting-catalogue acquisition or sequence assignment is authorized before this gate is passed.

### Gate 1C.1 — Acquisition readiness

Count-first reconnaissance, query subdivision design, fixed acquisition cutoff, temporal context (including whether the 1980 start is supported), candidate numerical magnitude thresholds, output schema and manifest plan are approved. No event data are downloaded until the count/limit and provenance plan passes review.

### Gate 1C.2 — Catalogue quality and completeness

Raw bytes, query metadata, manifest, counts, duplicates/aliases, magnitude types, origin/location quality, time-dependent and regional `Mc`, short-term post-mainshock completeness and censoring are audited before clustering.

### Gate 1C.3 — Method validation

Method implementations and parameter choices pass unit tests, known-case checks, synthetic/null tests and sensitivity reporting before global sequence assignments are generated. A Reasenberg comparator is marked unavailable if a faithful implementation cannot be verified.

### Gate 1C.4 — Sequence catalogue freeze

Method-specific outputs, consensus rules, unresolved cases, censoring and provenance are reviewed. The resulting sequence catalogue is a new versioned derivative; the Stage 1A/1B candidate catalogue remains unchanged.

## 12. Initial source references

1. **USGS FDSN Event Web Service API documentation** — count/query methods, UTC time handling, `includeallmagnitudes`, `minmagnitude` and the 20,000-event service limit: https://earthquake.usgs.gov/fdsnws/event/1/swagger.json
2. **USGS ComCat documentation** — catalogue scope, preferred information and data availability limitations: https://www.usgs.gov/programs/earthquake-hazards/anss-comprehensive-earthquake-catalog-comcat-documentation
3. **USGS “How Products Work in ComCat”** — product version identity and preferred-product behaviour: https://earthquake.usgs.gov/data/catalog/products.php
4. **USGS CLUSTER2000 software release** — implementation candidate describing its relation to Reasenberg (1985), with stated software limitations: https://www.usgs.gov/software/cluster2000
5. **Reasenberg, P. (1985)**, “Second-order moment of central California seismicity, 1969–1982,” *Journal of Geophysical Research*, 90(B7), 5479–5495. https://doi.org/10.1029/JB090iB07p05479
6. **Zaliapin, I. & Ben-Zion, Y. (2013a)**, “Earthquake clusters in southern California, I: Identification and stability,” *Journal of Geophysical Research: Solid Earth*, 118, 2847–2864. https://doi.org/10.1002/jgrb.50179
7. **Zaliapin, I. & Ben-Zion, Y. (2013b)**, “Earthquake clusters in southern California, II: Classification and relation to physical properties of the crust,” *Journal of Geophysical Research: Solid Earth*, 118(6), 2865–2877. https://doi.org/10.1002/jgrb.50178
8. **Zaliapin, I. & Ben-Zion, Y. (2016)**, “A global classification and characterization of earthquake clusters,” *Geophysical Journal International*, 207(1), 608–634. https://doi.org/10.1093/gji/ggw300
9. **Michael, A. J. (2014)**, “How complete is the ISC-GEM Global Earthquake Catalog?” *Bulletin of the Seismological Society of America*, 104(4), 1829–1837. https://doi.org/10.1785/0120130227
10. **Wang, X., Li, J., Feng, A., & Sornette, D. (2025)**, “Estimating Magnitude Completeness in Earthquake Catalogs: A Comparative Study of Catalog-Based Methods,” *Journal of Geophysical Research: Solid Earth*, 130(9), e2025JB031441. https://doi.org/10.1029/2025JB031441

## 13. Version history and amendment record

| Version | Date | Change | Status |
|---|---|---|---|
| v001 | 2026-11-08 | Initial protocol draft covering supporting catalogue, completeness, sequence methods, uncertainty, validation and leakage controls. | Preserved; draft superseded for review |
| v002 | 2026-11-08 | Clarified ComCat numerical magnitude filters versus Mw; added left-censoring; specified NN forest and mixture-threshold calibration; defined regional parameter conventions and cross-region sensitivity; added short-term post-mainshock completeness; defined non-majority method-agreement statuses; strengthened Reasenberg implementation acceptance; fixed 1980 pre-context requirement for 20-year sensitivity across 2000-start targets; fixed acquisition-cutoff/count-query reconciliation; corrected Wang et al. (2025) authorship. | Draft for review; not frozen |

### Protocol freeze rule

Any material change to target population, supporting-catalogue time range, magnitude policy, clustering algorithms, parameter calibration, event-role definitions or validation controls requires a new protocol version and a written rationale. Do not edit a frozen version in place. Preserve v001 and v002 as immutable versioned artifacts; a later approved protocol must supersede rather than overwrite them.

**Current authorization:** This v002 document is a draft for review. No supporting-catalogue downloads, global clustering run, event-role assignment or `sequence_id` assignment is authorized until Gate 1C.0 approval and commit.
