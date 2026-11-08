# Data Dictionary and Conventions

## General conventions

- Time: UTC, ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) unless the source explicitly requires another representation.
- Coordinates: decimal degrees, WGS84 where appropriate.
- Longitude: document whether source uses -180..180 or 0..360; normalize only in derived copies.
- Magnitude: retain original magnitude value and magnitude type; do not silently merge Mw, ML, mb, etc.
- Missing values: explicit null/NA plus a reason/quality flag where available; never substitute zero by default.
- Units: record units in column names or data dictionary.
- Raw data: immutable.

## Core files

### `event_catalogue.csv`
`event_id, origin_time_utc, latitude_deg, longitude_deg, depth_km, magnitude, magnitude_type, event_type, sequence_id, tectonic_region, candidate_status, inclusion_reason, source_url, catalogue_version`

### `event_exclusions.csv`
`event_id, exclusion_stage, exclusion_reason, rule_id, decision_date_utc, reviewer, notes`

### `station_registry.csv`
`station_id, network, provider, station_type, latitude_deg, longitude_deg, elevation_m, start_time_utc, end_time_utc, parameters_available, source_url, access_notes, licence_notes, qc_status`

### `data_manifest.csv`
`manifest_id, provider, product, product_version, source_url, local_relative_path, start_time_utc, end_time_utc, download_time_utc, file_size_bytes, sha256, licence_or_terms, processing_status, notes`

### `coverage_matrix.csv`
`event_id, sequence_id, station_id, domain, parameter, product, window_start_utc, window_end_utc, expected_samples, valid_samples, coverage_fraction, qa_pass_fraction, local_relative_path, manifest_id, coverage_status, notes`

### `artifact_register.csv`
`artifact_id, relative_path, artifact_type, description, owner, status, sha256, qc_status, analysis_run_id, github_commit, verification_notes, updated_utc`

## Status vocabulary

`planned`, `downloaded`, `hashed`, `qc_pending`, `qc_pass`, `qc_fail`, `analysed`, `verified`, `commit_ready`, `committed`, `excluded`.
