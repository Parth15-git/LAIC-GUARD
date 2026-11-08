#!/usr/bin/env python3
"""Finalize LAIC-GUARD Stage 1A provenance bookkeeping after a successful audit.

This is a metadata-only finalizer. It does not download data, modify either
catalogue, alter raw GeoJSON/sidecars, or repeat raw-byte validation. It checks
the evidence records produced by the already-completed reconstruction/audit,
corrects a misleading derivative download timestamp, registers the rebuilt
provenance record and scripts, and adds direct source references to the report.

Run from the LAIC-GUARD project root:
    python .\\scripts\\03_finalize_stage1a_provenance.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

V1 = Path("metadata/event_catalogue.csv")
V2 = Path("metadata/event_catalogue_v002.csv")
MANIFEST = Path("metadata/data_manifest.csv")
ARTIFACTS = Path("metadata/artifact_register.csv")
RETRIEVAL = Path("reports/coverage_audit/usgs_catalogue_retrieval_metadata_2000_2025_v001.json")
CORRECTION = Path("reports/coverage_audit/usgs_catalogue_correction_metadata_2000_2025_v002.json")
REPORT = Path("reports/coverage_audit/usgs_catalogue_quality_audit_2000_2025_v002.md")
MAG_SUMMARY = Path("reports/coverage_audit/usgs_magnitude_type_summary_2000_2025_v002.csv")
DEPTH_SUMMARY = Path("reports/coverage_audit/usgs_depth_distribution_2000_2025_v002.csv")
YEAR_SUMMARY = Path("reports/coverage_audit/usgs_yearly_catalogue_summary_2000_2025_v002.csv")
RECOVERY_SCRIPT = Path("scripts/00_rebuild_usgs_retrieval_metadata.py")
AUDIT_SCRIPT = Path("scripts/02_audit_and_version_catalogue.py")

MANIFEST_FIELDS = [
    "manifest_id", "source_id", "provider", "product", "product_version",
    "source_url", "local_relative_path", "start_time_utc", "end_time_utc",
    "download_time_utc", "file_size_bytes", "sha256", "licence_or_terms",
    "processing_status", "notes",
]
ARTIFACT_FIELDS = [
    "artifact_id", "relative_path", "artifact_type", "description", "owner",
    "status", "sha256", "qc_status", "analysis_run_id", "github_commit",
    "verification_notes", "updated_utc",
]

SOURCES_SECTION = """## 8. References and provenance

### USGS source documentation

1. U.S. Geological Survey, **API Documentation — Earthquake Catalog (FDSN Event Web Service)**. https://earthquake.usgs.gov/fdsnws/event/1/swagger.json
   The documented query parameters include `minmagnitude` and `eventtype`; no `magnitudetype` query parameter is listed in the current USGS implementation documentation. The catalogue is therefore a preferred-magnitude-threshold candidate set, not a query-enforced Mw-only set.
2. U.S. Geological Survey, **Magnitude Types**. https://www.usgs.gov/programs/earthquake-hazards/magnitude-types
3. U.S. Geological Survey, **Determining the Depth of an Earthquake**. https://www.usgs.gov/programs/earthquake-hazards/determining-depth-earthquake
4. U.S. Geological Survey, **Why do so many earthquakes occur at a depth of 10 km?** https://www.usgs.gov/faqs/why-do-so-many-earthquakes-occur-a-depth-10km

### Provenance note

The file `usgs_catalogue_retrieval_metadata_2000_2025_v001.json` is a reconstructed provenance record, not a byte-for-byte recovery of the originally generated JSON. It was rebuilt from the preserved annual query sidecars, raw GeoJSON responses, v001 catalogue, and data manifest. The reconstruction utility and subsequent audit both completed their local verification checks. The original v001 catalogue remains unchanged.
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def require_files(paths: list[Path]) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("Required Stage 1A output(s) missing:\n  " + "\n  ".join(missing))


def main() -> int:
    required = [
        V1, V2, MANIFEST, ARTIFACTS, RETRIEVAL, CORRECTION, REPORT,
        MAG_SUMMARY, DEPTH_SUMMARY, YEAR_SUMMARY, RECOVERY_SCRIPT, AUDIT_SCRIPT,
    ]
    require_files(required)

    v1_hash = sha256_file(V1)
    v2_hash = sha256_file(V2)
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    correction = json.loads(CORRECTION.read_text(encoding="utf-8"))

    # Confirm that the provenance JSON explicitly identifies itself as reconstructed.
    reconstruction = retrieval.get("metadata_reconstruction", {})
    if reconstruction.get("reconstructed") is not True:
        raise ValueError("Retrieval metadata does not explicitly identify itself as reconstructed.")
    if retrieval.get("catalogue_sha256", "").lower() != v1_hash.lower():
        raise ValueError("Reconstructed retrieval metadata does not match the current v001 catalogue hash.")
    if correction.get("source_catalogue_sha256", "").lower() != v1_hash.lower():
        raise ValueError("Correction metadata does not match the current v001 catalogue hash.")
    if correction.get("corrected_catalogue_sha256", "").lower() != v2_hash.lower():
        raise ValueError("Correction metadata does not match the current v002 catalogue hash.")
    if correction.get("raw_byte_verification_performed") is not True:
        raise ValueError("Correction metadata does not record a successful full raw-byte audit.")
    raw_checks = correction.get("raw_chunks", [])
    if len(raw_checks) != len(retrieval.get("chunks", [])) or len(raw_checks) != 26:
        raise ValueError("Expected 26 raw-chunk audit records.")
    for item in raw_checks:
        for field in ("metadata_manifest_hash_match", "raw_file_present", "raw_sha256_verified",
                      "raw_event_ids_match_catalogue", "query_sidecar_verified"):
            if item.get(field) is not True:
                raise ValueError(f"Raw-chunk verification flag {field!r} is not true for {item.get('path')}")

    manifest_fields, manifest_rows = read_csv(MANIFEST)
    if not set(MANIFEST_FIELDS).issubset(manifest_fields):
        raise ValueError(f"Unexpected manifest schema: {manifest_fields}")
    manifest_by_path = {r.get("local_relative_path", "").replace("\\", "/"): r for r in manifest_rows}
    if len(manifest_by_path) != len(manifest_rows):
        raise ValueError("Duplicate paths in data_manifest.csv.")

    # Cross-check all 26 raw-file hash records and ensure each sidecar is registered.
    for chunk in retrieval["chunks"]:
        raw_path = chunk["raw_geojson_path"].replace("\\", "/")
        raw_row = manifest_by_path.get(raw_path)
        if raw_row is None or raw_row.get("sha256", "").lower() != chunk.get("raw_sha256", "").lower():
            raise ValueError(f"Raw chunk metadata/manifest mismatch for {raw_path}")
        sidecar_path = str(Path(raw_path).with_suffix(".query.json")).replace("\\", "/")
        if sidecar_path not in manifest_by_path:
            raise ValueError(f"Query sidecar missing from manifest: {sidecar_path}")

    # Catalogue rows in manifest must match exact hashes and byte sizes.
    for rel, file_path, expected_hash in (
        (V1.as_posix(), V1, v1_hash),
        (V2.as_posix(), V2, v2_hash),
    ):
        row = manifest_by_path.get(rel)
        if row is None:
            raise ValueError(f"Catalogue missing from manifest: {rel}")
        if row.get("sha256", "").lower() != expected_hash.lower():
            raise ValueError(f"Catalogue hash differs from manifest: {rel}")
        if int(row.get("file_size_bytes", "-1")) != file_path.stat().st_size:
            raise ValueError(f"Catalogue file size differs from manifest: {rel}")

    # The v002 row is a local derivative, not a new download. Preserve its
    # processing timestamp in correction metadata, not in download_time_utc.
    v2_manifest = manifest_by_path[V2.as_posix()]
    old_download_timestamp = v2_manifest.get("download_time_utc", "")
    v2_manifest["download_time_utc"] = ""
    existing_note = v2_manifest.get("notes", "").strip()
    suffix = "Generated locally from v001; no download occurred. Generation time is recorded in correction metadata."
    if suffix not in existing_note:
        v2_manifest["notes"] = (existing_note + " " + suffix).strip()

    # Explicitly connect the correction metadata to the reconstructed source record.
    retrieval_hash = sha256_file(RETRIEVAL)
    correction["source_retrieval_metadata_path"] = RETRIEVAL.as_posix()
    correction["source_retrieval_metadata_sha256"] = retrieval_hash
    correction["source_retrieval_metadata_reconstructed"] = True
    correction["source_retrieval_metadata_note"] = (
        "The referenced retrieval metadata was reconstructed from preserved evidence; "
        "it is not the original JSON byte-for-byte."
    )
    CORRECTION.write_text(json.dumps(correction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    correction_hash = sha256_file(CORRECTION)

    # Add direct references and make the reconstructed-provenance caveat visible
    # in the stand-alone report. Avoid adding the section twice.
    report_text = REPORT.read_text(encoding="utf-8")
    if "## 8. References and provenance" not in report_text:
        REPORT.write_text(report_text.rstrip() + "\n\n" + SOURCES_SECTION, encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    artifact_fields, artifact_rows = read_csv(ARTIFACTS)
    if not set(ARTIFACT_FIELDS).issubset(artifact_fields):
        raise ValueError(f"Unexpected artifact-register schema: {artifact_fields}")
    artifact_by_path = {r.get("relative_path", ""): r for r in artifact_rows}

    records = [
        (RETRIEVAL, "metadata", "Reconstructed USGS retrieval provenance record; not the original JSON byte-for-byte.",
         "pass_reconstruction_crosschecks", "stage1a_metadata_reconstruction_v001",
         "Reconstructed from preserved query sidecars, raw GeoJSON, v001 catalogue and manifest; local cross-checks passed."),
        (RECOVERY_SCRIPT, "script", "Utility that reconstructs missing USGS retrieval metadata from preserved evidence.",
         "pass_execution_and_crosschecks", "stage1a_metadata_reconstruction_v001",
         "Executed successfully; verified all 26 raw chunks, query sidecars, counts and event-ID sets."),
        (AUDIT_SCRIPT, "script", "Utility that audits v001 and creates the corrected portable v002 catalogue.",
         "pass_execution_and_crosschecks", "stage1a_catalogue_audit_v002",
         "Executed successfully; local raw-byte, feature-count and event-ID checks passed."),
    ]
    for path, typ, desc, qc, run_id, notes in records:
        rel = path.as_posix()
        artifact_by_path[rel] = {
            "artifact_id": hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12],
            "relative_path": rel,
            "artifact_type": typ,
            "description": desc,
            "owner": "LAIC-GUARD",
            "status": "verified",
            "sha256": sha256_file(path),
            "qc_status": qc,
            "analysis_run_id": run_id,
            "github_commit": "",
            "verification_notes": notes,
            "updated_utc": now,
        }

    # The report and correction metadata were intentionally edited above, so
    # refresh their registered hashes. For the catalogue and summary CSVs,
    # require the existing hashes to match; never bless an unexpected change.
    for path in (V2, MAG_SUMMARY, DEPTH_SUMMARY, YEAR_SUMMARY):
        rel = path.as_posix()
        if rel not in artifact_by_path:
            raise ValueError(f"Expected generated output missing from artifact register: {rel}")
        actual_hash = sha256_file(path)
        if artifact_by_path[rel].get("sha256", "").lower() != actual_hash.lower():
            raise ValueError(f"Existing artifact-register hash mismatch; do not overwrite it blindly: {rel}")

    for path in (REPORT, CORRECTION):
        rel = path.as_posix()
        if rel not in artifact_by_path:
            raise ValueError(f"Expected generated output missing from artifact register: {rel}")
        artifact_by_path[rel]["sha256"] = sha256_file(path)
        artifact_by_path[rel]["updated_utc"] = now

    # Write all metadata only after all checks above have passed.
    write_csv(MANIFEST, MANIFEST_FIELDS, list(manifest_by_path.values()))
    write_csv(ARTIFACTS, ARTIFACT_FIELDS, list(artifact_by_path.values()))

    # Final consistency check of the two updated registers.
    _, manifest_after = read_csv(MANIFEST)
    _, artifacts_after = read_csv(ARTIFACTS)
    manifest_after_by_path = {r.get("local_relative_path"): r for r in manifest_after}
    artifacts_after_by_path = {r.get("relative_path"): r for r in artifacts_after}
    if manifest_after_by_path[V2.as_posix()].get("download_time_utc", ""):
        raise AssertionError("v002 derivative unexpectedly retains a download timestamp.")
    if artifacts_after_by_path[RETRIEVAL.as_posix()]["sha256"] != retrieval_hash:
        raise AssertionError("Reconstructed retrieval metadata hash was not registered.")
    if artifacts_after_by_path[CORRECTION.as_posix()]["sha256"] != correction_hash:
        raise AssertionError("Correction metadata hash was not refreshed.")
    if artifacts_after_by_path[REPORT.as_posix()]["sha256"] != sha256_file(REPORT):
        raise AssertionError("Audit report hash was not refreshed.")

    print("STAGE 1A PROVENANCE FINALIZATION COMPLETE")
    print(f"v001 catalogue SHA-256       : {v1_hash}")
    print(f"v002 catalogue SHA-256       : {v2_hash}")
    print(f"Retrieval metadata SHA-256   : {retrieval_hash}")
    print(f"Correction metadata SHA-256  : {correction_hash}")
    print(f"Audit report SHA-256         : {sha256_file(REPORT)}")
    print(f"v002 download_time_utc       : cleared (no download occurred; previous value={old_download_timestamp!r})")
    print("Reconstructed metadata      : registered in artifact_register.csv")
    print("Recovery and audit scripts  : registered in artifact_register.csv")
    print("Summary artifact hashes     : checked against existing registered values")
    print("Source URLs                 : added to audit report")
    print("NOTE: This finalizer does not rehash raw GeoJSON bytes; the prior audit run performed that check.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: Stage 1A finalization failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
