#!/usr/bin/env python3
"""Final local integrity and provenance check for LAIC-GUARD Stage 1A.

This script does not download data, modify either earthquake catalogue, or
change raw GeoJSON/query sidecars. It rechecks the 26 local raw chunks and
sidecars, verifies catalogue and summary invariants, fixes two provenance
bookkeeping details, clarifies the 10 km depth-review wording, and registers
this finalizer plus the prior provenance finalizer in artifact_register.csv.

Run from the LAIC-GUARD project root:
    python .\\scripts\\04_prepare_stage1a_commit.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
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
PROVENANCE_FINALIZER = Path("scripts/03_finalize_stage1a_provenance.py")
SCRIPT_ABS = Path(__file__).resolve()
try:
    THIS_REL = SCRIPT_ABS.relative_to(Path.cwd().resolve()).as_posix()
except ValueError as exc:
    raise SystemExit("Run this script from the LAIC-GUARD project root.") from exc
THIS_SCRIPT = Path(THIS_REL)

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
OLD_DEPTH_SENTENCE = (
    "Events with reported depth exactly 10.0 km: **171**. These are flagged for "
    "depth-quality review, not automatically excluded. USGS notes that 10 km can "
    "be used as a fixed default when depth cannot be reliably determined."
)
NEW_DEPTH_SENTENCE = (
    "Events with reported depth exactly 10.0 km: **171**. These records are "
    "identified for review by their reported value (`depth_km == 10.0`); in v002, "
    "the per-record `depth_screening_status` remains `not_screened` for all 1,186 "
    "records. This is an audit finding, not a completed depth-quality determination. "
    "The records are not automatically excluded. USGS notes that 10 km can be used "
    "as a fixed default when depth cannot be reliably determined."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv_atomic(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def require_files(paths: list[Path]) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("Required Stage 1A file(s) missing:\n  " + "\n  ".join(missing))


def normalized_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def add_or_update_artifact(
    by_path: dict[str, dict[str, str]], path: Path, artifact_type: str,
    description: str, qc_status: str, run_id: str, notes: str, now: str,
) -> None:
    rel = path.as_posix()
    by_path[rel] = {
        "artifact_id": hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12],
        "relative_path": rel,
        "artifact_type": artifact_type,
        "description": description,
        "owner": "LAIC-GUARD",
        "status": "verified",
        "sha256": sha256_file(path),
        "qc_status": qc_status,
        "analysis_run_id": run_id,
        "github_commit": "",
        "verification_notes": notes,
        "updated_utc": now,
    }


def main() -> int:
    require_files([
        V1, V2, MANIFEST, ARTIFACTS, RETRIEVAL, CORRECTION, REPORT,
        MAG_SUMMARY, DEPTH_SUMMARY, YEAR_SUMMARY, RECOVERY_SCRIPT,
        AUDIT_SCRIPT, PROVENANCE_FINALIZER, THIS_SCRIPT,
    ])

    v1_hash = sha256_file(V1)
    v2_hash = sha256_file(V2)
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    correction = json.loads(CORRECTION.read_text(encoding="utf-8"))
    if retrieval.get("metadata_reconstruction", {}).get("reconstructed") is not True:
        raise ValueError("Retrieval metadata does not disclose that it was reconstructed.")
    if retrieval.get("catalogue_sha256", "").lower() != v1_hash:
        raise ValueError("v001 catalogue hash does not match reconstructed retrieval metadata.")
    if correction.get("source_catalogue_sha256", "").lower() != v1_hash:
        raise ValueError("Correction metadata source hash does not match v001.")
    if correction.get("corrected_catalogue_sha256", "").lower() != v2_hash:
        raise ValueError("Correction metadata output hash does not match v002.")
    if correction.get("source_retrieval_metadata_sha256", "").lower() != sha256_file(RETRIEVAL):
        raise ValueError("Correction metadata does not point to the current reconstructed retrieval JSON.")
    if correction.get("raw_byte_verification_performed") is not True:
        raise ValueError("Correction metadata does not record the prior raw-byte audit.")

    v1_fields, v1_rows = read_csv(V1)
    v2_fields, v2_rows = read_csv(V2)
    if len(v1_rows) != 1186 or len(v2_rows) != 1186:
        raise ValueError(f"Expected 1,186 rows in both catalogues; got {len(v1_rows)} and {len(v2_rows)}.")
    v1_ids = [r.get("event_id", "") for r in v1_rows]
    v2_ids = [r.get("event_id", "") for r in v2_rows]
    if len(set(v1_ids)) != 1186 or len(set(v2_ids)) != 1186 or v1_ids != v2_ids:
        raise ValueError("Catalogue event IDs are not unique and identically ordered between v001 and v002.")
    allowed_changed = {"candidate_status", "inclusion_reason", "catalogue_version", "raw_geojson_path", "magnitude_family"}
    shared = set(v1_fields).intersection(v2_fields)
    for i, (old, new) in enumerate(zip(v1_rows, v2_rows)):
        for field in shared - allowed_changed:
            if old.get(field, "") != new.get(field, ""):
                raise ValueError(f"Unexpected source-value change at row {i + 2}, column {field!r}.")
        if new.get("catalogue_version") != "v002":
            raise ValueError(f"Incorrect catalogue_version at row {i + 2}.")
        if new.get("candidate_status") != "pending_project_screening":
            raise ValueError(f"Incorrect candidate_status at row {i + 2}.")
        if new.get("magnitude_threshold_query") != "6.5":
            raise ValueError(f"Incorrect query threshold at row {i + 2}.")
        if not new.get("raw_geojson_path", "").startswith("data/raw/usgs/"):
            raise ValueError(f"Non-portable raw path at row {i + 2}.")

    if len(retrieval.get("chunks", [])) != 26:
        raise ValueError("Expected 26 chunks in reconstructed retrieval metadata.")
    raw_checks = correction.get("raw_chunks", [])
    if len(raw_checks) != 26:
        raise ValueError("Expected 26 chunk records in correction metadata.")
    audit_by_path = {normalized_path(x.get("path", "")): x for x in raw_checks}

    manifest_fields, manifest_rows = read_csv(MANIFEST)
    if not set(MANIFEST_FIELDS).issubset(manifest_fields):
        raise ValueError(f"Unexpected data_manifest schema: {manifest_fields}")
    manifest_by_path = {normalized_path(r.get("local_relative_path", "")): r for r in manifest_rows}
    if len(manifest_by_path) != len(manifest_rows):
        raise ValueError("Duplicate local_relative_path values in data_manifest.csv.")

    rows_by_chunk: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in v1_rows:
        rows_by_chunk[row.get("query_chunk_start_utc", "")].append(row)

    # Rehash every original raw response and query sidecar from the user's local project.
    raw_total = 0
    for chunk in retrieval["chunks"]:
        rel = normalized_path(chunk["raw_geojson_path"])
        raw_path = Path(rel)
        sidecar_path = raw_path.with_suffix(".query.json")
        sidecar_rel = sidecar_path.as_posix()
        start = chunk["start_time_utc"]
        expected = int(chunk["expected_count"])
        returned = int(chunk["returned_count"])
        if expected != returned:
            raise ValueError(f"Count endpoint and response count differ for {rel}.")
        if len(rows_by_chunk.get(start, [])) != returned:
            raise ValueError(f"Catalogue row count does not match the chunk for {rel}.")

        raw_manifest = manifest_by_path.get(rel)
        side_manifest = manifest_by_path.get(sidecar_rel)
        if not raw_manifest or not side_manifest:
            raise ValueError(f"Raw file or sidecar is absent from manifest: {rel}")
        if not raw_path.is_file() or not sidecar_path.is_file():
            raise FileNotFoundError(f"Local raw file or query sidecar is missing: {rel}")

        actual_raw_hash = sha256_file(raw_path)
        actual_side_hash = sha256_file(sidecar_path)
        expected_raw_hash = str(chunk.get("raw_sha256", "")).lower()
        if actual_raw_hash != expected_raw_hash or actual_raw_hash != raw_manifest.get("sha256", "").lower():
            raise ValueError(f"Raw GeoJSON SHA-256 mismatch: {rel}")
        if actual_side_hash != side_manifest.get("sha256", "").lower():
            raise ValueError(f"Query sidecar SHA-256 mismatch: {sidecar_rel}")
        if int(raw_manifest.get("file_size_bytes", "-1")) != raw_path.stat().st_size:
            raise ValueError(f"Raw GeoJSON file-size mismatch: {rel}")
        if int(side_manifest.get("file_size_bytes", "-1")) != sidecar_path.stat().st_size:
            raise ValueError(f"Query sidecar file-size mismatch: {sidecar_rel}")

        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        raw_ids = {str(f.get("id", "")) for f in features if f.get("id")}
        catalogue_ids = {r.get("event_id", "") for r in rows_by_chunk[start]}
        if len(features) != returned or raw_ids != catalogue_ids:
            raise ValueError(f"Raw GeoJSON feature count or event-ID set mismatch: {rel}")

        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if int(sidecar.get("expected_count_from_count_endpoint", -1)) != expected or int(sidecar.get("returned_count", -1)) != returned:
            raise ValueError(f"Query-sidecar count metadata mismatch: {sidecar_rel}")
        audit_record = audit_by_path.get(rel)
        if not audit_record:
            raise ValueError(f"Correction metadata lacks a raw-chunk record: {rel}")
        for flag in ("metadata_manifest_hash_match", "raw_file_present", "raw_sha256_verified", "raw_event_ids_match_catalogue", "query_sidecar_verified"):
            if audit_record.get(flag) is not True:
                raise ValueError(f"Prior audit flag {flag!r} is not true for {rel}.")
        raw_total += returned

    if raw_total != 1186 or int(retrieval.get("count_endpoint_total", -1)) != 1186:
        raise ValueError(f"Raw chunk total does not equal 1,186: {raw_total}.")

    # Confirm key derived counts and summary files agree with v002.
    mag_counts = Counter(r.get("magnitude_type", "").lower() for r in v2_rows)
    expected_mags = {"mww": 647, "mwc": 390, "mwb": 116, "mw": 20, "mb": 8, "md": 2, "ms": 2, "ml": 1}
    if dict(mag_counts) != expected_mags:
        raise ValueError(f"Magnitude-type counts do not match the Stage 1A audit: {dict(mag_counts)}")
    depth_counts = Counter()
    for r in v2_rows:
        d = float(r["depth_km"])
        if d < 70:
            depth_counts["shallow_<70_km"] += 1
        elif d < 300:
            depth_counts["intermediate_70_to_<300_km"] += 1
        else:
            depth_counts["deep_>=300_km"] += 1
    if dict(depth_counts) != {"shallow_<70_km": 912, "intermediate_70_to_<300_km": 151, "deep_>=300_km": 123}:
        raise ValueError(f"Depth distribution mismatch: {dict(depth_counts)}")
    fixed_10km = sum(float(r["depth_km"]) == 10.0 for r in v2_rows)
    depth_statuses = Counter(r.get("depth_screening_status", "") for r in v2_rows)
    if fixed_10km != 171 or depth_statuses != {"not_screened": 1186}:
        raise ValueError(f"Unexpected 10 km/depth-screening status: fixed10={fixed_10km}, statuses={depth_statuses}")

    # Verify v001/v002 manifest entries and their byte sizes before metadata edits.
    for rel, path, digest in ((V1.as_posix(), V1, v1_hash), (V2.as_posix(), V2, v2_hash)):
        row = manifest_by_path.get(rel)
        if not row or row.get("sha256", "").lower() != digest:
            raise ValueError(f"Catalogue manifest SHA-256 mismatch: {rel}")
        if int(row.get("file_size_bytes", "-1")) != path.stat().st_size:
            raise ValueError(f"Catalogue manifest size mismatch: {rel}")
    if manifest_by_path[V2.as_posix()].get("download_time_utc", ""):
        raise ValueError("v002 still has a download timestamp even though it was generated locally.")

    # Check registered artifacts before updating any of the bookkeeping.
    artifact_fields, artifact_rows = read_csv(ARTIFACTS)
    if not set(ARTIFACT_FIELDS).issubset(artifact_fields):
        raise ValueError(f"Unexpected artifact_register schema: {artifact_fields}")
    artifact_by_path = {r.get("relative_path", ""): r for r in artifact_rows}
    if len(artifact_by_path) != len(artifact_rows):
        raise ValueError("Duplicate relative_path values in artifact_register.csv.")
    for rel, row in artifact_by_path.items():
        path = Path(rel)
        if not path.is_file():
            raise FileNotFoundError(f"Registered artifact is missing: {rel}")
        if rel != REPORT.as_posix() and sha256_file(path) != row.get("sha256", "").lower():
            raise ValueError(f"Existing artifact-register hash mismatch: {rel}")

    # Clarify that exact 10 km records are identified by value, not by a completed
    # per-row screening decision. This avoids overstating the v002 QC state.
    report_text = REPORT.read_text(encoding="utf-8")
    if OLD_DEPTH_SENTENCE in report_text:
        report_text = report_text.replace(OLD_DEPTH_SENTENCE, NEW_DEPTH_SENTENCE, 1)
    elif NEW_DEPTH_SENTENCE not in report_text:
        raise ValueError("Could not find the expected 10 km depth statement to clarify safely.")

    # The v001 CSV is also a local derivative from raw USGS files; it was not
    # separately downloaded. Its original row/hash/bytes remain unchanged.
    v1_manifest = manifest_by_path[V1.as_posix()]
    old_v1_timestamp = v1_manifest.get("download_time_utc", "")
    v1_manifest["download_time_utc"] = ""
    v1_manifest["processing_status"] = "derived_hashed"
    note = v1_manifest.get("notes", "").strip()
    suffix = "Catalogue CSV generated locally from preserved raw GeoJSON responses; no separate catalogue CSV download occurred."
    if suffix not in note:
        v1_manifest["notes"] = (note + " " + suffix).strip()

    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    # Save report text before computing its registered hash.
    REPORT.write_text(report_text.rstrip() + "\n", encoding="utf-8")

    # Update report hash and register both finalizer scripts, including this script.
    report_rel = REPORT.as_posix()
    if report_rel not in artifact_by_path:
        raise ValueError("Audit report is not present in artifact_register.csv.")
    artifact_by_path[report_rel]["sha256"] = sha256_file(REPORT)
    artifact_by_path[report_rel]["updated_utc"] = now
    add_or_update_artifact(
        artifact_by_path, PROVENANCE_FINALIZER, "script",
        "Utility that finalizes Stage 1A provenance metadata, source references and artifact hashes.",
        "pass_execution_and_crosschecks", "stage1a_provenance_finalization_v001",
        "Executed successfully; corrected the derivative download timestamp, registered rebuilt provenance and added USGS source references.", now,
    )
    add_or_update_artifact(
        artifact_by_path, THIS_SCRIPT, "script",
        "Final local integrity and provenance check before the Stage 1A Git commit.",
        "pass_local_integrity_and_provenance_checks", "stage1a_commit_readiness_v001",
        "Executed successfully; rehashed all 26 local raw GeoJSON files and query sidecars, matched event-ID sets, and verified catalogue/summary/register consistency.", now,
    )

    # Confirm the finalizer's and audit's key registered hashes are current.
    for path in (V2, CORRECTION, RETRIEVAL, MAG_SUMMARY, DEPTH_SUMMARY, YEAR_SUMMARY, RECOVERY_SCRIPT, AUDIT_SCRIPT, PROVENANCE_FINALIZER, THIS_SCRIPT):
        rel = path.as_posix()
        if rel not in artifact_by_path:
            raise ValueError(f"Required artifact is not registered: {rel}")
        if artifact_by_path[rel].get("sha256", "").lower() != sha256_file(path):
            raise ValueError(f"Artifact hash does not match its register entry: {rel}")

    # Persist the metadata registers. v001/v002 catalogue files are never written.
    write_csv_atomic(MANIFEST, MANIFEST_FIELDS, list(manifest_by_path.values()))
    write_csv_atomic(ARTIFACTS, ARTIFACT_FIELDS, list(artifact_by_path.values()))

    # Final round-trip checks on the files written by this script.
    _, manifest_after = read_csv(MANIFEST)
    manifest_after_by_path = {normalized_path(r.get("local_relative_path", "")): r for r in manifest_after}
    if manifest_after_by_path[V1.as_posix()].get("download_time_utc", ""):
        raise AssertionError("v001 local derivative unexpectedly retains a download timestamp.")
    if manifest_after_by_path[V2.as_posix()].get("download_time_utc", ""):
        raise AssertionError("v002 local derivative unexpectedly retains a download timestamp.")
    _, artifacts_after = read_csv(ARTIFACTS)
    artifacts_after_by_path = {r.get("relative_path", ""): r for r in artifacts_after}
    for path in (REPORT, PROVENANCE_FINALIZER, THIS_SCRIPT):
        if artifacts_after_by_path[path.as_posix()]["sha256"] != sha256_file(path):
            raise AssertionError(f"Artifact hash failed after write: {path}")

    print("STAGE 1A COMMIT-READINESS CHECK COMPLETE")
    print(f"v001 catalogue SHA-256            : {v1_hash}")
    print(f"v002 catalogue SHA-256            : {v2_hash}")
    print(f"Raw GeoJSON hashes                 : 26/26 matched local bytes + manifest")
    print(f"Query sidecar hashes               : 26/26 matched local bytes + manifest")
    print(f"Raw feature counts / event IDs     : 26/26 matched catalogue")
    print(f"Catalogue rows / unique IDs        : 1186 / 1186")
    print(f"Magnitude / depth summaries        : matched")
    print(f"Exactly 10 km records              : {fixed_10km}; depth status remains not_screened")
    print(f"v001 catalogue download timestamp  : cleared (previous value={old_v1_timestamp!r})")
    print("v002 catalogue download timestamp  : blank (locally generated derivative)")
    print("Artifact register                  : finalizer and this script registered; hashes checked")
    print("Audit report                       : clarified 10 km review wording; hash refreshed")
    print("Catalogue data files               : not modified")
    print("Raw data / sidecars                : not modified")
    print("Git commit                         : NOT created")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: Stage 1A commit-readiness check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
