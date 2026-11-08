#!/usr/bin/env python3
"""Rebuild missing LAIC-GUARD USGS v001 retrieval metadata from preserved evidence.

This utility does NOT contact USGS, download data, edit the v001 catalogue, or
modify raw GeoJSON/sidecar/manifest files. It reconstructs the metadata JSON
only after cross-checking the catalogue, all annual GeoJSON files, all query
sidecars, and their SHA-256 values against metadata/data_manifest.csv.

Run from the LAIC-GUARD project root:
    python .\\scripts\\00_rebuild_usgs_retrieval_metadata.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOGUE = Path("metadata/event_catalogue.csv")
MANIFEST = Path("metadata/data_manifest.csv")
RAW_DIR = Path("data/raw/usgs")
OUTPUT = Path("reports/coverage_audit/usgs_catalogue_retrieval_metadata_2000_2025_v001.json")
RAW_GLOB = "usgs_comcat_candidate_events_*_v001.geojson"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def parse_utc(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value!r}")
    return result.astimezone(timezone.utc)


def as_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing or invalid integer for {label}: {value!r}") from exc


def manifest_path_value(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild missing USGS retrieval metadata from existing local evidence.")
    parser.add_argument("--project-root", default=".", help="LAIC-GUARD project root")
    parser.add_argument("--force", action="store_true", help="Replace the output only if it already exists")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()

    cat_path = root / CATALOGUE
    manifest_path = root / MANIFEST
    raw_dir = root / RAW_DIR
    out_path = root / OUTPUT
    for required in (cat_path, manifest_path, raw_dir):
        if not required.exists():
            raise FileNotFoundError(f"Required evidence is missing: {required}")
    if out_path.exists() and not args.force:
        raise FileExistsError(f"Output already exists; refusing to overwrite: {out_path}. Use --force only after reviewing it.")

    cat_fields, catalogue_rows = read_csv(cat_path)
    manifest_fields, manifest_rows = read_csv(manifest_path)
    required_cat = {
        "event_id", "origin_time_utc", "latitude_deg", "longitude_deg", "depth_km",
        "magnitude", "magnitude_type", "event_type", "event_status",
        "raw_geojson_path", "query_chunk_start_utc",
    }
    missing_cat = sorted(required_cat - set(cat_fields))
    if missing_cat:
        raise ValueError(f"Catalogue is missing required columns: {missing_cat}")
    required_manifest = {"local_relative_path", "sha256", "file_size_bytes", "source_url"}
    missing_manifest = sorted(required_manifest - set(manifest_fields))
    if missing_manifest:
        raise ValueError(f"Manifest is missing required columns: {missing_manifest}")

    manifest_by_path = {
        manifest_path_value(row.get("local_relative_path", "")): row
        for row in manifest_rows
    }

    # Validate the catalogue file against its original manifest hash.
    cat_rel = CATALOGUE.as_posix()
    cat_manifest = manifest_by_path.get(cat_rel)
    if not cat_manifest:
        raise ValueError(f"Catalogue is not registered in data_manifest.csv: {cat_rel}")
    catalogue_sha = sha256_file(cat_path)
    if catalogue_sha.lower() != str(cat_manifest.get("sha256", "")).lower():
        raise ValueError("Catalogue SHA-256 differs from its data_manifest.csv record; refusing reconstruction.")
    if len(catalogue_rows) != len({row.get("event_id", "") for row in catalogue_rows}):
        raise ValueError("Catalogue contains duplicate event IDs; refusing reconstruction.")

    raw_files = sorted(raw_dir.glob(RAW_GLOB))
    if len(raw_files) != 26:
        raise ValueError(f"Expected 26 annual raw GeoJSON files, found {len(raw_files)}.")

    chunks: list[dict[str, Any]] = []
    all_params: list[dict[str, str]] = []
    all_retrieval_times: list[str] = []
    chunk_start_seen: set[str] = set()
    total_count_endpoint = 0

    rows_by_chunk: dict[str, list[dict[str, str]]] = {}
    for row in catalogue_rows:
        rows_by_chunk.setdefault(row.get("query_chunk_start_utc", ""), []).append(row)

    for raw_path in raw_files:
        sidecar_path = raw_path.with_suffix(".query.json")
        if not sidecar_path.is_file():
            raise FileNotFoundError(f"Matching query sidecar is missing: {sidecar_path}")

        raw_rel = raw_path.relative_to(root).as_posix()
        sidecar_rel = sidecar_path.relative_to(root).as_posix()
        raw_manifest = manifest_by_path.get(raw_rel)
        sidecar_manifest = manifest_by_path.get(sidecar_rel)
        if not raw_manifest or not sidecar_manifest:
            raise ValueError(f"Raw file or sidecar has no manifest entry: {raw_rel} / {sidecar_rel}")

        raw_sha = sha256_file(raw_path)
        sidecar_sha = sha256_file(sidecar_path)
        if raw_sha.lower() != str(raw_manifest.get("sha256", "")).lower():
            raise ValueError(f"Raw GeoJSON SHA-256 differs from manifest: {raw_rel}")
        if sidecar_sha.lower() != str(sidecar_manifest.get("sha256", "")).lower():
            raise ValueError(f"Query sidecar SHA-256 differs from manifest: {sidecar_rel}")

        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        params = sidecar.get("parameters")
        if not isinstance(params, dict):
            raise ValueError(f"Sidecar lacks the original query parameters: {sidecar_rel}")
        for key in ("starttime", "endtime", "minmagnitude", "eventtype", "format", "orderby"):
            if key not in params:
                raise ValueError(f"Sidecar {sidecar_rel} is missing query parameter {key!r}")
        if str(params["eventtype"]).lower() != "earthquake":
            raise ValueError(f"Unexpected eventtype in {sidecar_rel}: {params['eventtype']!r}")
        if str(params["format"]).lower() != "geojson":
            raise ValueError(f"Unexpected response format in {sidecar_rel}: {params['format']!r}")

        start = str(params["starttime"])
        end = str(params["endtime"])
        start_dt = parse_utc(start)
        end_dt = parse_utc(end)
        if start in chunk_start_seen:
            raise ValueError(f"Duplicate query chunk start time: {start}")
        chunk_start_seen.add(start)

        expected = as_int(sidecar.get("expected_count_from_count_endpoint"), f"{sidecar_rel}: expected_count_from_count_endpoint")
        returned = as_int(sidecar.get("returned_count"), f"{sidecar_rel}: returned_count")
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        actual_feature_count = len(features)
        if actual_feature_count != returned or returned != expected:
            raise ValueError(
                f"Count mismatch for {raw_rel}: count endpoint={expected}, sidecar returned={returned}, raw features={actual_feature_count}"
            )

        chunk_rows = rows_by_chunk.get(start, [])
        if len(chunk_rows) != returned:
            raise ValueError(f"Catalogue rows for chunk {start} are {len(chunk_rows)}, sidecar reports {returned}.")
        raw_ids = {str(feature.get("id", "")) for feature in features if feature.get("id")}
        catalogue_ids = {row.get("event_id", "") for row in chunk_rows}
        if raw_ids != catalogue_ids:
            raise ValueError(f"Event IDs in raw file do not exactly match catalogue rows for {raw_rel}.")

        url = str(sidecar.get("api_endpoint", "")).strip()
        if not url:
            raise ValueError(f"Sidecar does not retain api_endpoint: {sidecar_rel}")
        if url != str(raw_manifest.get("source_url", "")):
            raise ValueError(f"Raw manifest source_url differs from sidecar api_endpoint: {raw_rel}")

        retrieved_at = str(sidecar.get("retrieved_at_utc", "")).strip()
        if retrieved_at:
            parse_utc(retrieved_at)
            all_retrieval_times.append(retrieved_at)
        all_params.append({key: str(value) for key, value in params.items()})
        total_count_endpoint += expected

        chunks.append({
            "start_time_utc": start,
            "end_time_utc": end,
            "expected_count": expected,
            "returned_count": returned,
            "raw_geojson_path": raw_rel,
            "raw_sha256": raw_sha,
            "query_url": url,
        })

    # Every catalogue row must belong to exactly one preserved chunk.
    if len(rows_by_chunk) != len(chunks):
        missing_or_unexpected = sorted(set(rows_by_chunk) ^ {chunk["start_time_utc"] for chunk in chunks})
        raise ValueError(f"Catalogue chunk keys and raw-sidecar chunks differ: {missing_or_unexpected[:10]}")
    if total_count_endpoint != len(catalogue_rows):
        raise ValueError(f"Sum of count-endpoint results ({total_count_endpoint}) != catalogue rows ({len(catalogue_rows)}).")

    # The known source run used annual UTC windows. Verify continuity and common query parameters.
    chunks.sort(key=lambda item: parse_utc(item["start_time_utc"]))
    first_start = parse_utc(chunks[0]["start_time_utc"])
    last_end = parse_utc(chunks[-1]["end_time_utc"])
    start_year = first_start.year
    end_year = last_end.year
    if len(chunks) != end_year - start_year + 1:
        raise ValueError("The recovered chunk list is not one annual chunk per year across its date range.")
    for index, chunk in enumerate(chunks):
        s = parse_utc(chunk["start_time_utc"])
        e = parse_utc(chunk["end_time_utc"])
        if s.year != start_year + index or (s.month, s.day, s.hour, s.minute, s.second, s.microsecond) != (1, 1, 0, 0, 0, 0):
            raise ValueError(f"Chunk does not start at a UTC year boundary: {chunk['start_time_utc']}")
        if e.year != s.year or (e.month, e.day, e.hour, e.minute, e.second) != (12, 31, 23, 59, 59):
            raise ValueError(f"Chunk does not end at the expected UTC year boundary: {chunk['end_time_utc']}")
        if index < len(chunks) - 1 and parse_utc(chunks[index + 1]["start_time_utc"]).year != s.year + 1:
            raise ValueError("Annual chunk sequence has a missing or overlapping year.")

    minima = {str(p["minmagnitude"]) for p in all_params}
    event_types = {str(p["eventtype"]).lower() for p in all_params}
    formats = {str(p["format"]).lower() for p in all_params}
    orderbys = {str(p["orderby"]).lower() for p in all_params}
    if len(minima) != 1 or len(event_types) != 1 or len(formats) != 1 or len(orderbys) != 1:
        raise ValueError("Query parameters are inconsistent across annual sidecars; refusing to infer a single run configuration.")
    min_magnitude = float(next(iter(minima)))

    # Cross-check each catalogue row uses the same threshold and the expected earthquake date window.
    for row in catalogue_rows:
        if not row.get("event_id"):
            raise ValueError("Catalogue contains a blank event ID.")
        if row.get("event_type", "").lower() != "earthquake":
            raise ValueError(f"Non-earthquake row found in candidate earthquake catalogue: {row.get('event_id')}")
        if float(row.get("magnitude", "nan")) < min_magnitude:
            raise ValueError(f"Event falls below the sidecar minmagnitude query: {row.get('event_id')}")

    recovered = {
        "project": "LAIC-GUARD",
        "catalogue_version": "v001",
        "provider": "USGS ComCat / FDSN Event Web Service",
        "retrieved_at_utc": max(all_retrieval_times, key=parse_utc) if all_retrieval_times else "",
        "start_year": start_year,
        "end_year_inclusive": end_year,
        "minimum_magnitude_query": min_magnitude,
        "event_type_filter": "earthquake",
        "magnitude_filter_caveat": "This query is not a strict Mw-only catalogue. Preferred magnitude and magType are preserved; final magnitude-type eligibility must be decided separately.",
        "depth_filter": None,
        "chunks": chunks,
        "count_endpoint_total": total_count_endpoint,
        "unique_event_rows": len(catalogue_rows),
        "unique_event_ids": len({row.get("event_id", "") for row in catalogue_rows}),
        "catalogue_csv": CATALOGUE.as_posix(),
        "catalogue_sha256": catalogue_sha,
        "raw_data_policy": "Raw response files are preserved unchanged in data/raw/usgs/; hashes rechecked against the original data_manifest.csv records during metadata reconstruction.",
        "sequence_policy": "sequence_id intentionally blank until a documented sequence grouping rule is approved.",
        "depth_policy": "No depth exclusion applied; depth_km retained for later screening.",
        "metadata_reconstruction": {
            "reconstructed": True,
            "reason": "Original retrieval-metadata JSON was not present at its expected path or elsewhere in the searched OneDrive directory.",
            "method": "Rebuilt from the 26 preserved query sidecars, 26 raw GeoJSON responses, v001 catalogue, and existing data_manifest.csv. All raw and sidecar SHA-256 values and event-ID sets were cross-checked before writing.",
            "important_note": "This is a reconstructed provenance record, not byte-for-byte recovery of the originally generated metadata JSON. It does not claim the original metadata file was preserved.",
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(recovered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(out_path)

    print("USGS RETRIEVAL METADATA RECONSTRUCTION COMPLETE")
    print(f"Annual chunks verified       : {len(chunks)}")
    print(f"Count-endpoint total         : {total_count_endpoint}")
    print(f"Catalogue rows / unique IDs  : {len(catalogue_rows)} / {len({r.get('event_id', '') for r in catalogue_rows})}")
    print(f"Query minmagnitude           : {min_magnitude:g}")
    print("Raw GeoJSON hashes           : MATCHED against data_manifest.csv")
    print("Query sidecar hashes         : MATCHED against data_manifest.csv")
    print("Raw feature IDs vs catalogue : MATCHED for all chunks")
    print(f"Reconstructed metadata       : {OUTPUT.as_posix()}")
    print("NOTE: Provenance JSON was reconstructed from preserved evidence; it is not the original JSON file.")
    print("Next: run the Stage 1A audit script. It will independently recheck the raw files again.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
