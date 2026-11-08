#!/usr/bin/env python3
"""Audit the v001 USGS catalogue and create a corrected, portable v002.

Run from the LAIC-GUARD project root:
    python scripts/02_audit_and_version_catalogue.py

This script does NOT download data. It verifies the existing v001 catalogue,
all 26 raw GeoJSON chunks and the manifest, then creates v002 outputs without
overwriting v001.

Only Python's standard library is required.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOGUE_IN = Path("metadata/event_catalogue.csv")
MANIFEST_PATH = Path("metadata/data_manifest.csv")
METADATA_IN = Path("reports/coverage_audit/usgs_catalogue_retrieval_metadata_2000_2025_v001.json")
OUT_CATALOGUE = Path("metadata/event_catalogue_v002.csv")
OUT_REPORT = Path("reports/coverage_audit/usgs_catalogue_quality_audit_2000_2025_v002.md")
OUT_METADATA = Path("reports/coverage_audit/usgs_catalogue_correction_metadata_2000_2025_v002.json")
OUT_MAG_SUMMARY = Path("reports/coverage_audit/usgs_magnitude_type_summary_2000_2025_v002.csv")
OUT_DEPTH_SUMMARY = Path("reports/coverage_audit/usgs_depth_distribution_2000_2025_v002.csv")
OUT_YEAR_SUMMARY = Path("reports/coverage_audit/usgs_yearly_catalogue_summary_2000_2025_v002.csv")

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
EXPLICIT_MW_TYPES = {"mww", "mwc", "mwb", "mwr", "mwp"}
NON_MW_TYPES = {"mb", "ms", "md", "ml", "mlg", "mb_lg", "mb_lg"}


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


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def relative_raw_path(value: str, project_root: Path) -> str:
    """Convert the v001 absolute Windows path into a project-relative POSIX path."""
    normalized = str(value).replace("\\", "/")
    marker = "/LAIC-GUARD/"
    if marker in normalized:
        rel = normalized.split(marker, 1)[1]
    elif normalized.startswith("data/"):
        rel = normalized
    else:
        # Try to locate the stable data/raw suffix without embedding a username.
        idx = normalized.find("/data/raw/")
        if idx >= 0:
            rel = normalized[idx + 1:]
        else:
            raise ValueError(f"Cannot convert raw_geojson_path to portable relative path: {value}")
    rel = rel.lstrip("/")
    if not rel.startswith("data/raw/usgs/"):
        raise ValueError(f"Unexpected raw GeoJSON path after normalization: {rel}")
    return rel


def classify_magnitude_type(mag_type: str) -> tuple[str, str]:
    mt = (mag_type or "").strip().lower()
    if mt in EXPLICIT_MW_TYPES:
        return "moment_magnitude_family", "USGS moment-magnitude subtype is explicitly identified by magType."
    if mt == "mw":
        return "generic_mw_label_review", "Generic Mw label; preserve as an Mw-family candidate but review source/product metadata before final eligibility decisions."
    if mt in NON_MW_TYPES:
        return "other_or_non_moment_type", "Reported preferred magnitude is not an Mw subtype; do not treat as Mw without additional event-product evidence."
    if mt:
        return "other_or_unresolved_type", "Unrecognized or source-specific magnitude type; inspect event metadata before eligibility decisions."
    return "unknown_mag_type", "Magnitude type is missing; event requires metadata review."


def append_manifest(path: Path, new_record: dict[str, Any]) -> None:
    if path.exists() and path.stat().st_size:
        fields, rows = read_csv(path)
        if not set(MANIFEST_FIELDS).issubset(fields):
            raise ValueError(f"Manifest schema mismatch. Expected fields: {MANIFEST_FIELDS}; found: {fields}")
    else:
        fields, rows = MANIFEST_FIELDS, []
    by_path = {r.get("local_relative_path"): r for r in rows}
    by_path[new_record["local_relative_path"]] = new_record
    write_csv(path, MANIFEST_FIELDS, list(by_path.values()))


def append_artifact_register(project_root: Path, records: list[dict[str, Any]]) -> None:
    path = project_root / "metadata" / "artifact_register.csv"
    if path.exists() and path.stat().st_size:
        fields, rows = read_csv(path)
        if not set(ARTIFACT_FIELDS).issubset(fields):
            logging.warning("artifact_register.csv has an unexpected schema; not modifying it")
            return
    else:
        fields, rows = ARTIFACT_FIELDS, []
    by_path = {r.get("relative_path"): r for r in rows}
    for rec in records:
        by_path[rec["relative_path"]] = rec
    write_csv(path, ARTIFACT_FIELDS, list(by_path.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the v001 USGS catalogue and create portable v002 outputs.")
    parser.add_argument("--project-root", default=".", help="LAIC-GUARD project root (default: current directory)")
    parser.add_argument("--metadata-only", action="store_true", help="Skip reading raw GeoJSON bytes; outputs are NOT marked fully raw-verified")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    cat_path = root / CATALOGUE_IN
    manifest_path = root / MANIFEST_PATH
    metadata_path = root / METADATA_IN
    for p in (cat_path, manifest_path, metadata_path):
        if not p.exists():
            raise FileNotFoundError(f"Required input is missing: {p}")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    logging.info("Project root: %s", root)

    cat_fields, source_rows = read_csv(cat_path)
    manifest_fields, manifest_rows = read_csv(manifest_path)
    retrieval = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest_by_path = {r.get("local_relative_path", ""): r for r in manifest_rows}
    manifest_by_path = {k.replace("\\", "/"): v for k, v in manifest_by_path.items()}

    source_hash = sha256_file(cat_path)
    if source_hash != retrieval.get("catalogue_sha256"):
        raise ValueError("The v001 catalogue SHA-256 does not match retrieval metadata. Stop and investigate.")
    catalogue_manifest = manifest_by_path.get("metadata/event_catalogue.csv")
    if not catalogue_manifest or catalogue_manifest.get("sha256", "").lower() != source_hash:
        raise ValueError("The v001 catalogue SHA-256 does not match its data_manifest.csv entry.")

    expected_total = int(retrieval.get("count_endpoint_total", -1))
    expected_rows = int(retrieval.get("unique_event_rows", -1))
    expected_ids = int(retrieval.get("unique_event_ids", -1))
    if len(source_rows) != expected_rows or len(source_rows) != expected_total:
        raise ValueError(f"Row-count mismatch: CSV={len(source_rows)}, metadata rows={expected_rows}, count endpoint={expected_total}")

    required = ["event_id", "origin_time_utc", "latitude_deg", "longitude_deg", "depth_km", "magnitude", "magnitude_type", "event_type", "event_status", "raw_geojson_path", "query_chunk_start_utc"]
    missing_columns = [c for c in required if c not in cat_fields]
    if missing_columns:
        raise ValueError(f"Catalogue lacks required columns: {missing_columns}")

    ids = [r.get("event_id", "") for r in source_rows]
    duplicate_ids = len(ids) - len(set(ids))
    if duplicate_ids:
        raise ValueError(f"Found {duplicate_ids} duplicate event IDs")
    if len(set(ids)) != expected_ids:
        raise ValueError("Unique event ID count does not match retrieval metadata")

    # Validate all 26 annual chunks against row counts, raw file bytes and manifest.
    chunk_counts = Counter(r.get("query_chunk_start_utc", "") for r in source_rows)
    raw_checks: list[dict[str, Any]] = []
    raw_missing: list[str] = []
    raw_hash_mismatches: list[str] = []
    raw_count_mismatches: list[str] = []
    manifest_hash_mismatches: list[str] = []
    for chunk in retrieval.get("chunks", []):
        start = chunk["start_time_utc"]
        rel = chunk["raw_geojson_path"].replace("\\", "/")
        expected = int(chunk["expected_count"])
        returned = int(chunk["returned_count"])
        if chunk_counts.get(start, 0) != returned:
            raise ValueError(f"Catalogue rows for chunk {start} do not match retrieval metadata: {chunk_counts.get(start, 0)} vs {returned}")
        manifest_entry = manifest_by_path.get(rel)
        if not manifest_entry:
            manifest_hash_mismatches.append(f"Manifest entry missing: {rel}")
        elif manifest_entry.get("sha256", "").lower() != str(chunk.get("raw_sha256", "")).lower():
            manifest_hash_mismatches.append(f"Manifest SHA mismatch: {rel}")
        raw_path = root / rel
        raw_actual_sha = ""
        raw_actual_count = None
        raw_ids_match_catalogue = None
        sidecar_ok = None
        if not args.metadata_only:
            if not raw_path.exists():
                raw_missing.append(rel)
            else:
                raw_actual_sha = sha256_file(raw_path)
                if raw_actual_sha.lower() != str(chunk.get("raw_sha256", "")).lower():
                    raw_hash_mismatches.append(rel)
                payload = json.loads(raw_path.read_text(encoding="utf-8"))
                features = payload.get("features", [])
                raw_actual_count = len(features)
                if raw_actual_count != returned or returned != expected:
                    raw_count_mismatches.append(rel)
                raw_event_ids = {str(f.get("id", "")) for f in features if f.get("id")}
                catalogue_event_ids = {r.get("event_id", "") for r in source_rows if r.get("query_chunk_start_utc") == start}
                raw_ids_match_catalogue = raw_event_ids == catalogue_event_ids
                if not raw_ids_match_catalogue:
                    raise ValueError(f"Raw GeoJSON event IDs do not match catalogue rows for chunk {rel}")

                sidecar_path = raw_path.with_suffix(".query.json")
                sidecar_rel = sidecar_path.relative_to(root).as_posix()
                sidecar_manifest = manifest_by_path.get(sidecar_rel)
                if not sidecar_path.exists() or not sidecar_manifest:
                    raise ValueError(f"Query sidecar or manifest entry is missing: {sidecar_rel}")
                sidecar_sha = sha256_file(sidecar_path)
                if sidecar_sha.lower() != sidecar_manifest.get("sha256", "").lower():
                    raise ValueError(f"Query sidecar SHA-256 mismatch: {sidecar_rel}")
                sidecar_payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
                sidecar_ok = (
                    int(sidecar_payload.get("expected_count_from_count_endpoint", -1)) == expected
                    and int(sidecar_payload.get("returned_count", -1)) == returned
                )
                if not sidecar_ok:
                    raise ValueError(f"Query sidecar count metadata mismatch: {sidecar_rel}")
        raw_checks.append({
            "path": rel, "expected_count": expected, "returned_count": returned,
            "catalogue_rows": int(chunk_counts.get(start, 0)),
            "metadata_manifest_hash_match": bool(manifest_entry and manifest_entry.get("sha256", "").lower() == str(chunk.get("raw_sha256", "")).lower()),
            "raw_file_present": (root / rel).exists() if not args.metadata_only else None,
            "raw_sha256_verified": (raw_actual_sha.lower() == str(chunk.get("raw_sha256", "")).lower()) if raw_actual_sha else None,
            "raw_feature_count": raw_actual_count,
            "raw_event_ids_match_catalogue": raw_ids_match_catalogue,
            "query_sidecar_verified": sidecar_ok,
        })

    if manifest_hash_mismatches:
        raise ValueError("Raw chunk manifest/sidecar hash mapping problems: " + "; ".join(manifest_hash_mismatches[:5]))
    if not args.metadata_only and (raw_missing or raw_hash_mismatches or raw_count_mismatches):
        raise ValueError(
            "Raw verification failed. Missing=" + str(raw_missing[:5]) +
            " SHA mismatches=" + str(raw_hash_mismatches[:5]) +
            " count mismatches=" + str(raw_count_mismatches[:5])
        )

    # Parse and validate event attributes.
    numeric = {k: [] for k in ("latitude_deg", "longitude_deg", "depth_km", "magnitude")}
    mag_type_counts: Counter[str] = Counter()
    mag_type_mins: dict[str, float] = {}
    mag_type_maxs: dict[str, float] = {}
    depth_bands = Counter()
    yearly = Counter()
    reviewed = Counter()
    fixed_10km = 0
    magnitude_at_query_floor = 0
    missing_core: Counter[str] = Counter()
    corrected_rows: list[dict[str, Any]] = []
    query_min = float(retrieval["minimum_magnitude_query"])
    for row in source_rows:
        for col in required:
            if row.get(col, "") == "":
                missing_core[col] += 1
        lat = float(row["latitude_deg"])
        lon = float(row["longitude_deg"])
        depth = float(row["depth_km"])
        mag = float(row["magnitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Out-of-range coordinates for {row['event_id']}")
        if depth < 0 or not math.isfinite(depth):
            raise ValueError(f"Invalid depth for {row['event_id']}")
        if not math.isfinite(mag) or mag < query_min:
            raise ValueError(f"Magnitude below query floor or invalid for {row['event_id']}: {mag}")
        if row.get("event_type") != "earthquake":
            raise ValueError(f"Non-earthquake event type in earthquake-only query: {row['event_id']}")
        year = row["origin_time_utc"][:4]
        yearly[year] += 1
        mt = (row.get("magnitude_type") or "").strip().lower()
        mag_type_counts[mt or "unknown"] += 1
        mag_type_mins[mt] = min(mag_type_mins.get(mt, mag), mag)
        mag_type_maxs[mt] = max(mag_type_maxs.get(mt, mag), mag)
        if mag == query_min:
            magnitude_at_query_floor += 1
        if depth == 10.0:
            fixed_10km += 1
        if depth < 70:
            depth_bands["shallow_<70_km"] += 1
        elif depth < 300:
            depth_bands["intermediate_70_to_<300_km"] += 1
        else:
            depth_bands["deep_>=300_km"] += 1
        reviewed[row.get("event_status", "unknown")] += 1

        new = dict(row)
        family, type_note = classify_magnitude_type(mt)
        new["magnitude_family"] = family
        new["magnitude_type_note"] = type_note
        new["magnitude_threshold_query"] = f"{query_min:g}"
        new["candidate_status"] = "pending_project_screening"
        new["inclusion_reason"] = (
            f"Returned by USGS ComCat earthquake query with minmagnitude>={query_min:g}; "
            "preferred magnitude type, focal depth, sequence dependence and data coverage "
            "have not yet been used to determine final study eligibility."
        )
        new["raw_geojson_path"] = relative_raw_path(row["raw_geojson_path"], root)
        new["catalogue_version"] = "v002"
        corrected_rows.append(new)

    if any(missing_core.values()):
        raise ValueError(f"Missing values in required fields: {dict(missing_core)}")

    # All chunk counts must agree with the original annual count audit.
    if sum(chunk_counts.values()) != expected_total:
        raise ValueError("Sum of catalogue rows by chunk does not equal the USGS count endpoint total")

    # Prepare versioned output columns while preserving all v001 columns.
    out_fields = list(cat_fields)
    for new_col in ("magnitude_type_note", "magnitude_threshold_query"):
        if new_col not in out_fields:
            out_fields.append(new_col)
    write_csv(root / OUT_CATALOGUE, out_fields, corrected_rows)
    out_hash = sha256_file(root / OUT_CATALOGUE)

    # Summaries
    mag_summary = []
    for mt, n in sorted(mag_type_counts.items(), key=lambda x: (-x[1], x[0])):
        family, note = classify_magnitude_type(mt)
        mag_summary.append({
            "magnitude_type": mt, "count": n, "fraction": f"{n/len(source_rows):.6f}",
            "minimum_magnitude": mag_type_mins.get(mt, ""), "maximum_magnitude": mag_type_maxs.get(mt, ""),
            "classification": family, "interpretation_note": note,
        })
    write_csv(root / OUT_MAG_SUMMARY,
              ["magnitude_type", "count", "fraction", "minimum_magnitude", "maximum_magnitude", "classification", "interpretation_note"],
              mag_summary)

    depth_labels = ["shallow_<70_km", "intermediate_70_to_<300_km", "deep_>=300_km"]
    depth_summary = [{
        "depth_class": label,
        "count": depth_bands.get(label, 0),
        "fraction": f"{depth_bands.get(label, 0)/len(source_rows):.6f}",
        "definition": {"shallow_<70_km": "0 <= depth < 70 km", "intermediate_70_to_<300_km": "70 <= depth < 300 km", "deep_>=300_km": "300 <= depth <= 700 km (and any retained value beyond, if present)"}[label],
    } for label in depth_labels]
    write_csv(root / OUT_DEPTH_SUMMARY, ["depth_class", "count", "fraction", "definition"], depth_summary)

    year_summary = [{"year": y, "count": yearly[y]} for y in sorted(yearly)]
    write_csv(root / OUT_YEAR_SUMMARY, ["year", "count"], year_summary)

    # Corrected catalogue manifest record; v001 is retained untouched.
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    corrected_manifest = {
        "manifest_id": "USGS-CATALOGUE-V002",
        "source_id": "USGS_COMCAT",
        "provider": "U.S. Geological Survey",
        "product": "USGS ComCat candidate event catalogue CSV — corrected portable derivative",
        "product_version": "v002 derived from v001; no re-download; see correction metadata",
        "source_url": "https://earthquake.usgs.gov/fdsnws/event/1/query",
        "local_relative_path": str(OUT_CATALOGUE).replace("\\", "/"),
        "start_time_utc": f"{retrieval['start_year']}-01-01T00:00:00.000Z",
        "end_time_utc": f"{retrieval['end_year_inclusive']}-12-31T23:59:59.999Z",
        "download_time_utc": now,
        "file_size_bytes": (root / OUT_CATALOGUE).stat().st_size,
        "sha256": out_hash,
        "licence_or_terms": "Derived from USGS ComCat data; verify and follow current USGS attribution/terms before redistribution",
        "processing_status": "verified_derivative_raw_checks_passed" if not args.metadata_only else "metadata_audit_only_raw_bytes_not_rechecked",
        "notes": "Corrects v001 query-threshold explanation and absolute raw paths; preserves original event values; does not apply magnitude/depth/sequence exclusions.",
    }
    append_manifest(manifest_path, corrected_manifest)

    correction_meta = {
        "project": "LAIC-GUARD",
        "catalogue_version": "v002",
        "derived_from_catalogue": str(CATALOGUE_IN).replace("\\", "/"),
        "source_catalogue_sha256": source_hash,
        "corrected_catalogue": str(OUT_CATALOGUE).replace("\\", "/"),
        "corrected_catalogue_sha256": out_hash,
        "retrieved_at_utc_source": retrieval.get("retrieved_at_utc"),
        "audit_run_at_utc": now,
        "source_rows": len(source_rows),
        "unique_event_ids": len(set(ids)),
        "count_endpoint_total": expected_total,
        "magnitude_query_minimum": query_min,
        "raw_byte_verification_performed": not args.metadata_only,
        "raw_chunks": raw_checks,
        "corrections": [
            "Corrected inclusion_reason to state the actual query threshold, rather than repeating each event's preferred magnitude.",
            "Converted raw_geojson_path from machine-specific absolute Windows paths to project-relative POSIX paths.",
            "Changed candidate_status to pending_project_screening to distinguish internal eligibility review from the USGS event_status field.",
            "Reclassified generic 'mw' separately as generic_mw_label_review rather than lumping it with non-Mw magnitude types.",
            "Added magnitude_type_note and magnitude_threshold_query fields for transparent screening.",
        ],
        "magnitude_type_counts": dict(mag_type_counts),
        "depth_class_counts": dict(depth_bands),
        "usgs_event_status_counts": dict(reviewed),
        "fixed_10km_depth_count_flag_for_review": fixed_10km,
        "magnitude_at_query_floor_count": magnitude_at_query_floor,
        "limitations": [
            "This remains a candidate catalogue, not the final eligible earthquake sample.",
            "No event-sequence grouping, tectonic-region classification, magnitude-type exclusion or depth exclusion has been applied.",
            "A depth of exactly 10 km is flagged for review, not automatically treated as erroneous.",
            "Generic magType='mw' is kept as a separately reviewable generic Mw label; it is not silently merged with explicitly named Mww/Mwc/Mwb subtypes.",
            "All USGS event_status values are preserved; this is distinct from LAIC-GUARD project screening status.",
        ],
    }
    (root / OUT_METADATA).parent.mkdir(parents=True, exist_ok=True)
    (root / OUT_METADATA).write_text(json.dumps(correction_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Human-readable audit report
    pct = lambda n: 100.0 * n / len(source_rows)
    explicit_mw = sum(mag_type_counts.get(x, 0) for x in EXPLICIT_MW_TYPES)
    generic_mw = mag_type_counts.get("mw", 0)
    non_mw = sum(n for mt, n in mag_type_counts.items() if mt not in EXPLICIT_MW_TYPES and mt != "mw")
    report = f"""# LAIC-GUARD — USGS Candidate Catalogue Quality Audit (v002)

**Audit time (UTC):** {now}
**Source:** USGS ComCat / FDSN Event Web Service
**Period:** {retrieval['start_year']}-01-01 through {retrieval['end_year_inclusive']}-12-31
**Query:** `minmagnitude={query_min:g}`, `eventtype=earthquake`
**Scope:** Candidate catalogue quality audit only; not the final event-selection decision.

## 1. Integrity results

| Check | Result |
|---|---:|
| USGS count endpoint total | {expected_total} |
| Catalogue rows | {len(source_rows)} |
| Unique event IDs | {len(set(ids))} |
| Duplicate event IDs | {duplicate_ids} |
| Annual chunks | {len(retrieval.get('chunks', []))} |
| Year/chunk row counts agree | Yes |
| v001 catalogue SHA matches retrieval metadata and manifest | Yes |
| Raw chunk SHA and feature counts verified locally | {'Yes' if not args.metadata_only else 'Not rechecked (metadata-only mode)'} |
| Event type | All rows are `earthquake` |
| USGS event status | {dict(reviewed)} |

## 2. Magnitude-type distribution

| magType | Count |
|---|---:|
"""
    for row in mag_summary:
        report += f"| `{row['magnitude_type']}` | {row['count']} |\n"
    report += f"""

- Explicit Mw subtypes (`mww`, `mwc`, `mwb`, and other named Mw families): **{explicit_mw} ({pct(explicit_mw):.2f}%)**.
- Generic `mw` labels: **{generic_mw} ({pct(generic_mw):.2f}%)**; retain for separate review rather than silently dropping or merging.
- Other preferred magnitude types: **{non_mw} ({pct(non_mw):.2f}%)**.

The query's `minmagnitude` threshold is applied to the preferred magnitude returned by ComCat; the current USGS API documentation describes `minmagnitude` but does not expose a `magnitudetype` query parameter in its implementation parameter list. Therefore this is not a strict Mw-only catalogue. See the USGS API documentation and magnitude-type definitions in the literature register / project notes.

## 3. Depth distribution

| Class | Count | Percentage |
|---|---:|---:|
| Shallow (<70 km) | {depth_bands.get('shallow_<70_km', 0)} | {pct(depth_bands.get('shallow_<70_km', 0)):.2f}% |
| Intermediate (70 to <300 km) | {depth_bands.get('intermediate_70_to_<300_km', 0)} | {pct(depth_bands.get('intermediate_70_to_<300_km', 0)):.2f}% |
| Deep (>=300 km) | {depth_bands.get('deep_>=300_km', 0)} | {pct(depth_bands.get('deep_>=300_km', 0)):.2f}% |

Depth range: {min(float(r['depth_km']) for r in source_rows):.1f}–{max(float(r['depth_km']) for r in source_rows):.1f} km.
Events with reported depth exactly 10.0 km: **{fixed_10km}**. These are flagged for depth-quality review, not automatically excluded. USGS notes that 10 km can be used as a fixed default when depth cannot be reliably determined.

The depth bands follow the common USGS classification: shallow 0–70 km, intermediate 70–300 km, deep 300–700 km. Boundary handling in this report is `<70`, `70 to <300`, and `>=300` to avoid double-counting.

## 4. Other data-quality observations

- Magnitude range: {min(float(r['magnitude']) for r in source_rows):.2f} to {max(float(r['magnitude']) for r in source_rows):.2f}.
- Events exactly at the query threshold ({query_min:g}): {magnitude_at_query_floor}.
- All event IDs are unique.
- All origin times and coordinates are present and within valid geographic bounds.
- `sequence_id` is intentionally blank; no sequence algorithm has been approved.
- `tectonic_region` is intentionally blank; no source-backed tectonic classification has been applied.

## 5. v001 defects corrected in v002

1. v001 `inclusion_reason` mistakenly repeated each event's own magnitude as if it were the query threshold. v002 correctly states `minmagnitude>={query_min:g}`.
2. v001 `raw_geojson_path` contained an absolute Windows path tied to one computer/user. v002 uses project-relative paths such as `data/raw/usgs/...`.
3. v001 `candidate_status=candidate_unreviewed` could be confused with USGS review status. v002 uses `pending_project_screening`; the separate USGS `event_status` remains unchanged.
4. v001 classified generic `mw` as non-moment. v002 labels it `generic_mw_label_review` so it remains visible for an explicit policy decision.

## 6. Recommended scientific treatment (not an exclusion decision)

- Keep all 1,186 records in the broad candidate catalogue.
- Create a primary shallow-event analysis stratum and separate intermediate/deep sensitivity strata; do not silently discard deeper events.
- Keep the three explicit Mw subtypes and generic `mw` labels distinguishable until the magnitude policy is frozen.
- Review all 10 km depth events and any other fixed/rounded depths using event detail products or source metadata where possible.
- Group dependent sequences before creating train/calibration/test splits.
- Only then intersect candidates with station and satellite coverage.

## 7. Outputs

- Corrected derivative: `{OUT_CATALOGUE.as_posix()}`
- Magnitude summary: `{OUT_MAG_SUMMARY.as_posix()}`
- Depth summary: `{OUT_DEPTH_SUMMARY.as_posix()}`
- Yearly summary: `{OUT_YEAR_SUMMARY.as_posix()}`
- Correction metadata: `{OUT_METADATA.as_posix()}`

**v001 remains preserved. v002 is a corrected derivative, not a new USGS download.**
"""
    (root / OUT_REPORT).write_text(report, encoding="utf-8")

    # Register outputs in artifact register where its template exists.
    artifact_records = []
    for rel, typ, desc in [
        (str(OUT_CATALOGUE).replace("\\", "/"), "dataset", "Corrected, portable candidate catalogue v002 derived from v001."),
        (str(OUT_REPORT).replace("\\", "/"), "report", "USGS candidate catalogue quality audit."),
        (str(OUT_METADATA).replace("\\", "/"), "metadata", "Audit and correction metadata for v002."),
        (str(OUT_MAG_SUMMARY).replace("\\", "/"), "summary", "Magnitude-type distribution summary."),
        (str(OUT_DEPTH_SUMMARY).replace("\\", "/"), "summary", "Depth-class distribution summary."),
        (str(OUT_YEAR_SUMMARY).replace("\\", "/"), "summary", "Annual candidate event counts."),
    ]:
        p = root / rel
        artifact_records.append({
            "artifact_id": hashlib.sha1(rel.encode()).hexdigest()[:12],
            "relative_path": rel,
            "artifact_type": typ,
            "description": desc,
            "owner": "LAIC-GUARD",
            "status": "verified" if not args.metadata_only else "qc_pending",
            "sha256": sha256_file(p),
            "qc_status": "pass_raw_integrity" if not args.metadata_only else "metadata_only_raw_pending",
            "analysis_run_id": "stage1a_catalogue_audit_v002",
            "github_commit": "",
            "verification_notes": "Derived from v001; raw file hashes checked locally." if not args.metadata_only else "Raw GeoJSON byte hashes were not rechecked; metadata-only audit.",
            "updated_utc": now,
        })
    append_artifact_register(root, artifact_records)

    print("\nSTAGE 1A CATALOGUE AUDIT COMPLETE")
    print(f"v001 source rows          : {len(source_rows)}")
    print(f"Unique event IDs          : {len(set(ids))}")
    print(f"Duplicate event IDs       : {duplicate_ids}")
    print(f"Explicit Mw subtypes      : {explicit_mw}")
    print(f"Generic mw labels         : {generic_mw}")
    print(f"Other magnitude types    : {non_mw}")
    print(f"Shallow <70 km            : {depth_bands.get('shallow_<70_km', 0)}")
    print(f"Intermediate 70-<300 km  : {depth_bands.get('intermediate_70_to_<300_km', 0)}")
    print(f"Deep >=300 km             : {depth_bands.get('deep_>=300_km', 0)}")
    print(f"Exactly 10 km depth       : {fixed_10km} (flag for review; not auto-excluded)")
    print(f"v002 catalogue SHA-256    : {out_hash}")
    print(f"Report                   : {OUT_REPORT}")
    print(f"Corrected catalogue      : {OUT_CATALOGUE}")
    print("v001 remains unchanged.")
    if args.metadata_only:
        print("WARNING: metadata-only mode; raw GeoJSON bytes were not rehashed locally.")
    else:
        print("RAW GEOJSON SHA-256 AND FEATURE COUNTS VERIFIED.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("Catalogue audit/correction failed: %s", exc)
        raise SystemExit(1)
