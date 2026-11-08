#!/usr/bin/env python3
"""
Download USGS ComCat GeoJSON Detail records for the Stage 1B priority list.

Safety properties:
- Dry-run is the default; network requests require --execute.
- Reads the existing manifest schema without changing its column order.
- Verifies source summary GeoJSON files against the manifest before using them.
- Uses each summary feature's official `properties.detail` URL where available.
- Saves original response bytes unchanged and a separate retrieval sidecar.
- Adds one manifest row for the detail response and one for its sidecar.
- Resumes safely: already-downloaded files are skipped only when files and manifest
  hashes agree; unexpected partial/orphan files cause a stop rather than overwrite.
- Does not download product attachments or modify either event catalogue.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
DEFAULT_PRIORITY = BASE / "reports" / "stage1b" / "detail_review_priority_v001.csv"
DEFAULT_CATALOGUE = BASE / "metadata" / "event_catalogue_v002.csv"
DEFAULT_MANIFEST = BASE / "metadata" / "data_manifest.csv"
DEFAULT_RAW_DIR = BASE / "data" / "raw" / "usgs_event_details"
DEFAULT_REPORT = BASE / "reports" / "stage1b" / "comcat_detail_retrieval_status_v001.csv"
DEFAULT_PRODUCT_INDEX = BASE / "reports" / "stage1b" / "comcat_detail_product_index_v001.csv"

MANIFEST_COLUMNS = [
    "manifest_id", "source_id", "provider", "product", "product_version",
    "source_url", "local_relative_path", "start_time_utc", "end_time_utc",
    "download_time_utc", "file_size_bytes", "sha256", "licence_or_terms",
    "processing_status", "notes",
]
ID_COLUMN_CANDIDATES = [
    "event_id", "preferred_event_id", "comcat_event_id", "eventid",
    "usgs_event_id", "id",
]
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
USGS_HOSTS = {"earthquake.usgs.gov"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv_atomic(path: Path, columns: list[str], rows: list[dict[str, Any]], *, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
    tmp.replace(path)


def normalize_id(value: Any, *, context: str) -> str:
    event_id = str(value or "").strip()
    if not event_id or not SAFE_ID.fullmatch(event_id):
        raise ValueError(f"Invalid or unsafe event ID {event_id!r} in {context}")
    return event_id


def detect_id_column(columns: list[str], requested: str | None) -> str:
    if requested:
        if requested not in columns:
            raise ValueError(
                f"Requested ID column {requested!r} is not in priority CSV. "
                f"Available columns: {columns}"
            )
        return requested
    matches = [name for name in ID_COLUMN_CANDIDATES if name in columns]
    if len(matches) != 1:
        raise ValueError(
            "Could not identify exactly one event-ID column in detail_review_priority_v001.csv. "
            f"Candidate matches: {matches}; available columns: {columns}. "
            "Rerun with --id-column YOUR_COLUMN."
        )
    return matches[0]


def load_event_inputs(priority_path: Path, catalogue_path: Path, id_column: str | None):
    pcols, prows = read_csv(priority_path)
    p_id_col = detect_id_column(pcols, id_column)
    if not prows:
        raise ValueError(f"Priority CSV contains no data rows: {priority_path}")

    priority_ids = [normalize_id(row.get(p_id_col), context=str(priority_path)) for row in prows]
    duplicates = sorted({x for x in priority_ids if priority_ids.count(x) > 1})
    if duplicates:
        raise ValueError(f"Priority file has duplicate event IDs; refusing silent deduplication: {duplicates[:20]}")

    ccols, crows = read_csv(catalogue_path)
    required = {"event_id", "origin_time_utc"}
    missing = required - set(ccols)
    if missing:
        raise ValueError(f"Catalogue missing required columns: {sorted(missing)}")
    cat_by_id = {}
    for row in crows:
        eid = normalize_id(row.get("event_id"), context=str(catalogue_path))
        if eid in cat_by_id:
            raise ValueError(f"Duplicate event_id in v002 catalogue: {eid}")
        cat_by_id[eid] = row

    not_in_catalogue = sorted(set(priority_ids) - set(cat_by_id))
    if not_in_catalogue:
        raise ValueError(
            f"{len(not_in_catalogue)} priority IDs are absent from v002 catalogue; "
            f"examples: {not_in_catalogue[:20]}"
        )
    return priority_ids, cat_by_id, p_id_col


def load_manifest(path: Path):
    columns, rows = read_csv(path)
    if columns != MANIFEST_COLUMNS:
        raise ValueError(
            "Manifest column structure differs from the validated Stage 1A schema.\n"
            f"Expected: {MANIFEST_COLUMNS}\nFound:    {columns}"
        )
    ids = [r["manifest_id"] for r in rows]
    paths = [r["local_relative_path"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Existing data_manifest.csv contains duplicate manifest_id values.")
    if len(paths) != len(set(paths)):
        raise ValueError("Existing data_manifest.csv contains duplicate local_relative_path values.")
    return columns, rows


def verify_and_map_summary_features(manifest_rows, catalogue_ids: set[str]):
    raw_rows = [
        r for r in manifest_rows
        if r["product"] == "USGS ComCat GeoJSON raw response"
        and r["local_relative_path"].endswith(".geojson")
        and not r["local_relative_path"].endswith(".query.json")
    ]
    if len(raw_rows) != 26:
        raise ValueError(
            f"Expected 26 annual USGS raw GeoJSON manifest entries; found {len(raw_rows)}."
        )
    mapping: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        p = BASE / Path(row["local_relative_path"])
        if not p.is_file():
            raise FileNotFoundError(f"Raw source GeoJSON is missing: {p}")
        data = p.read_bytes()
        actual_hash = sha256_bytes(data)
        if len(data) != int(row["file_size_bytes"]) or actual_hash != row["sha256"]:
            raise ValueError(f"Raw source file fails manifest size/hash verification: {p}")
        try:
            obj = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in raw source file {p}: {exc}") from exc
        features = obj.get("features")
        if not isinstance(features, list):
            raise ValueError(f"Expected GeoJSON FeatureCollection in {p}")
        if len(features) != int(obj.get("metadata", {}).get("count", len(features))):
            raise ValueError(f"Feature count disagrees with metadata count in {p}")
        for feature in features:
            eid = normalize_id(feature.get("id"), context=str(p))
            if eid in mapping:
                raise ValueError(f"Duplicate preferred event ID across summary chunks: {eid}")
            props = feature.get("properties") or {}
            mapping[eid] = {
                "detail_url": props.get("detail"),
                "summary_feature": feature,
                "summary_source_path": row["local_relative_path"],
            }

    missing = sorted(catalogue_ids - set(mapping))
    extra = sorted(set(mapping) - catalogue_ids)
    if missing or extra:
        raise ValueError(
            f"Summary GeoJSON/catalogue ID set mismatch. Missing={len(missing)} {missing[:10]}; "
            f"extra={len(extra)} {extra[:10]}"
        )
    return mapping


def build_fallback_detail_url(event_id: str) -> str:
    query = urllib.parse.urlencode({"eventid": event_id, "format": "geojson"})
    return "https://earthquake.usgs.gov/fdsnws/event/1/query?" + query


def validate_detail_url(url: Any, event_id: str) -> tuple[str, str]:
    if isinstance(url, str) and url.strip():
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme == "https" and parsed.hostname in USGS_HOSTS:
            return url.strip(), "summary_property_detail_url"
    return build_fallback_detail_url(event_id), "fdsn_eventid_fallback"


def parse_detail_response(data: bytes, requested_id: str) -> tuple[dict[str, Any], str]:
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("type") != "Feature":
        raise ValueError(f"Expected one GeoJSON Feature, got type={obj.get('type') if isinstance(obj, dict) else type(obj)}")
    returned_id = normalize_id(obj.get("id"), context="detail response")
    props = obj.get("properties") or {}
    associated = props.get("ids") or ""
    associated_ids = {
        token.strip().lstrip(",") for token in str(associated).split(",") if token.strip(", ")
    }
    if returned_id == requested_id:
        return obj, "exact_id_match"
    if requested_id in associated_ids:
        return obj, "requested_id_listed_in_associated_ids"
    raise ValueError(
        f"Detail response identity mismatch: requested={requested_id}, returned={returned_id}, "
        f"requested_in_associated_ids={requested_id in associated_ids}"
    )


def summarize_products(detail: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    products = (detail.get("properties") or {}).get("products") or {}
    summary: dict[str, int] = {}
    index_rows = []
    if not isinstance(products, dict):
        return summary, index_rows
    for product_type, versions in products.items():
        if not isinstance(versions, list):
            continue
        summary[product_type] = len(versions)
        for product in versions:
            if not isinstance(product, dict):
                continue
            contents = product.get("contents") or {}
            update_ms = product.get("updateTime")
            update_iso = ""
            if isinstance(update_ms, (int, float)):
                update_iso = datetime.fromtimestamp(update_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            index_rows.append({
                "requested_event_id": "",
                "returned_event_id": detail.get("id", ""),
                "product_type": product_type,
                "source": product.get("source", ""),
                "code": product.get("code", ""),
                "product_id": product.get("id", ""),
                "update_time_utc": update_iso,
                "status": product.get("status", ""),
                "preferred_weight": product.get("preferredWeight", ""),
                "content_count": len(contents) if isinstance(contents, dict) else 0,
                "content_names": ";".join(sorted(contents.keys())) if isinstance(contents, dict) else "",
            })
    return summary, index_rows


def manifest_id(path_value: str) -> str:
    return "USGS-DET-" + hashlib.sha256(path_value.encode("utf-8")).hexdigest()[:12]


def create_manifest_rows(
    event_id: str,
    event_time: str,
    detail_url: str,
    retrieved_at: str,
    detail_path: str,
    detail_bytes: bytes,
    sidecar_path: str,
    sidecar_bytes: bytes,
    licence: str,
    identity_status: str,
) -> list[dict[str, Any]]:
    common = {
        "source_id": "USGS_COMCAT",
        "provider": "U.S. Geological Survey",
        "product_version": "USGS GeoJSON Detail Format; retrieval snapshot",
        "source_url": detail_url,
        "start_time_utc": event_time,
        "end_time_utc": event_time,
        "download_time_utc": retrieved_at,
        "licence_or_terms": licence,
        "processing_status": "downloaded_hashed",
    }
    return [
        {
            "manifest_id": manifest_id(detail_path),
            **common,
            "product": "USGS ComCat GeoJSON event detail response",
            "local_relative_path": detail_path,
            "file_size_bytes": len(detail_bytes),
            "sha256": sha256_bytes(detail_bytes),
            "notes": f"Original ComCat detail response bytes preserved for requested event {event_id}; identity result={identity_status}. Product attachments not downloaded.",
        },
        {
            "manifest_id": manifest_id(sidecar_path),
            **common,
            "product": "USGS ComCat event detail retrieval sidecar",
            "local_relative_path": sidecar_path,
            "file_size_bytes": len(sidecar_bytes),
            "sha256": sha256_bytes(sidecar_bytes),
            "notes": f"Request, retrieval timestamp, response identity, product summary and detail-response hash for {event_id}.",
        },
    ]


def retrieve(url: str, timeout: int, user_agent: str) -> tuple[bytes, int]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/geo+json, application/json;q=0.9, */*;q=0.5",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), int(response.status)


def update_manifest(manifest_path: Path, columns: list[str], existing_rows: list[dict[str, str]], new_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    existing_paths = {r["local_relative_path"] for r in existing_rows}
    existing_ids = {r["manifest_id"] for r in existing_rows}
    for row in new_rows:
        if row["local_relative_path"] in existing_paths:
            raise ValueError(f"Manifest path already exists: {row['local_relative_path']}")
        if row["manifest_id"] in existing_ids:
            raise ValueError(f"Manifest ID collision: {row['manifest_id']}")
        existing_paths.add(row["local_relative_path"])
        existing_ids.add(row["manifest_id"])
    combined = existing_rows + [{k: str(row.get(k, "")) for k in columns} for row in new_rows]
    # Preserve whether the existing manifest used UTF-8 BOM.
    bom = manifest_path.read_bytes().startswith(bytes((239, 187, 191)))
    write_csv_atomic(manifest_path, columns, combined, bom=bom)
    return combined


def load_existing_detail_status(event_id: str, detail_path: Path, sidecar_path: Path, manifest_rows):
    expected = [
        detail_path.relative_to(BASE).as_posix(),
        sidecar_path.relative_to(BASE).as_posix(),
    ]
    rows_by_path = {r["local_relative_path"]: r for r in manifest_rows}
    files_exist = [detail_path.exists(), sidecar_path.exists()]
    if not any(files_exist):
        if any(path in rows_by_path for path in expected):
            raise ValueError(f"Manifest already references missing detail files for {event_id}; manual repair required.")
        return False
    if not all(files_exist):
        raise ValueError(f"Partial/orphan detail files exist for {event_id}; refusing overwrite.")
    for p, rel in zip([detail_path, sidecar_path], expected):
        row = rows_by_path.get(rel)
        if row is None:
            raise ValueError(f"Existing detail file is not registered in manifest: {rel}")
        data = p.read_bytes()
        if len(data) != int(row["file_size_bytes"]) or sha256_bytes(data) != row["sha256"]:
            raise ValueError(f"Existing detail file fails manifest integrity check: {rel}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and register USGS ComCat GeoJSON Detail snapshots for Stage 1B priority events."
    )
    parser.add_argument("--priority-csv", type=Path, default=DEFAULT_PRIORITY)
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--product-index", type=Path, default=DEFAULT_PRODUCT_INDEX)
    parser.add_argument("--id-column", default=None, help="Override automatic event-ID column detection.")
    parser.add_argument("--execute", action="store_true", help="Actually make requests. Without this flag, only dry-run validation is performed.")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N events (useful for a small live test).")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Delay between successful/attempted event requests; default 1.0 seconds.")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    for p in [args.priority_csv, args.catalogue, args.manifest]:
        if not p.is_absolute():
            p = BASE / p

    priority_path = args.priority_csv if args.priority_csv.is_absolute() else BASE / args.priority_csv
    catalogue_path = args.catalogue if args.catalogue.is_absolute() else BASE / args.catalogue
    manifest_path = args.manifest if args.manifest.is_absolute() else BASE / args.manifest
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else BASE / args.raw_dir
    report_path = args.report if args.report.is_absolute() else BASE / args.report
    product_index_path = args.product_index if args.product_index.is_absolute() else BASE / args.product_index

    try:
        priority_ids, cat_by_id, id_col = load_event_inputs(priority_path, catalogue_path, args.id_column)
        manifest_columns, manifest_rows = load_manifest(manifest_path)
        feature_map = verify_and_map_summary_features(manifest_rows, set(cat_by_id))
    except Exception as exc:
        print(f"ERROR: input validation failed: {exc}", file=sys.stderr)
        return 2

    ids_to_process = priority_ids[:args.limit] if args.limit else priority_ids
    if args.limit is not None and args.limit < 1:
        print("ERROR: --limit must be >= 1", file=sys.stderr)
        return 2
    licence = next(
        (r["licence_or_terms"] for r in manifest_rows if r["source_id"] == "USGS_COMCAT" and r["licence_or_terms"]),
        "USGS public ComCat service; verify current USGS attribution/terms before redistribution",
    )

    planned = []
    already_complete = 0
    for eid in ids_to_process:
        detail_path = raw_dir / f"{eid}.detail.geojson"
        sidecar_path = raw_dir / f"{eid}.detail.metadata.json"
        complete = load_existing_detail_status(eid, detail_path, sidecar_path, manifest_rows)
        if complete:
            already_complete += 1
        url, url_source = validate_detail_url(feature_map[eid]["detail_url"], eid)
        planned.append((eid, detail_path, sidecar_path, url, url_source, complete))

    print("USGS COMCAT DETAIL RETRIEVAL — " + ("EXECUTION MODE" if args.execute else "DRY-RUN MODE"))
    print(f"Priority event IDs in input             : {len(priority_ids)}")
    print(f"Event-ID column                         : {id_col}")
    print(f"Events selected this run                : {len(ids_to_process)}")
    print(f"Already complete and hash-verified      : {already_complete}")
    print(f"New detail requests planned              : {len(ids_to_process) - already_complete}")
    print(f"Source summary GeoJSON files verified   : 26")
    print(f"Source summary event IDs mapped         : {len(feature_map)}")
    print(f"Existing manifest rows                  : {len(manifest_rows)}")
    print(f"Manifest columns                        : {len(manifest_columns)}")
    print(f"Detail output directory                 : {raw_dir.relative_to(BASE).as_posix() if raw_dir.is_relative_to(BASE) else raw_dir}")
    print(f"Request pacing                           : {args.sleep_seconds:.2f} seconds")
    print(f"Products attachments downloaded          : NO (detail metadata only)")
    if planned:
        print("First planned event IDs                 : " + ", ".join(x[0] for x in planned[:5]))
        print("First detail URL source                  : " + planned[0][4])
    if not args.execute:
        print("No network requests were made; no files were changed.")
        print("For a 3-event live test, rerun with: --execute --limit 3")
        print("For all events, rerun with: --execute")
        return 0

    report_rows: list[dict[str, Any]] = []
    product_rows: list[dict[str, Any]] = []
    success = 0
    skipped = 0
    failures = 0
    for idx, (eid, detail_path, sidecar_path, url, url_source, complete) in enumerate(planned, start=1):
        if complete:
            skipped += 1
            # Re-index cached detail files.
            detail_bytes = detail_path.read_bytes()
            detail_obj, identity_status = parse_detail_response(detail_bytes, eid)
            psummary, prows = summarize_products(detail_obj)
            for pr in prows:
                pr["requested_event_id"] = eid
                product_rows.append(pr)
            report_rows.append({
                "event_id": eid, "status": "already_verified_skip",
                "http_status": 200, "identity_match_status": identity_status,
                "detail_relative_path": detail_path.relative_to(BASE).as_posix(),
                "sha256": sha256_bytes(detail_bytes), "product_types": json.dumps(psummary, sort_keys=True),
                "retrieved_at_utc": "", "error": "",
            })
            continue

        retrieved_at = utc_now()
        response_bytes = None
        http_status = ""
        last_error = ""
        for attempt in range(1, args.retries + 1):
            try:
                response_bytes, http_status = retrieve(
                    url, args.timeout, "LAIC-GUARD/1.0 (research data retrieval; contact: project maintainer)"
                )
                break
            except urllib.error.HTTPError as exc:
                http_status = exc.code
                last_error = f"HTTP {exc.code}: {exc.reason}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < args.retries:
                time.sleep(min(2 ** (attempt - 1), 8))
        if response_bytes is None:
            failures += 1
            report_rows.append({
                "event_id": eid, "status": "download_failed", "http_status": http_status,
                "identity_match_status": "", "detail_relative_path": "",
                "sha256": "", "product_types": "", "retrieved_at_utc": retrieved_at,
                "error": last_error,
            })
            print(f"[{idx}/{len(planned)}] FAILED {eid}: {last_error}")
            time.sleep(max(args.sleep_seconds, 0))
            continue

        try:
            detail_obj, identity_status = parse_detail_response(response_bytes, eid)
        except Exception as exc:
            failures += 1
            report_rows.append({
                "event_id": eid, "status": "identity_or_format_failed", "http_status": http_status,
                "identity_match_status": "", "detail_relative_path": "",
                "sha256": sha256_bytes(response_bytes), "product_types": "",
                "retrieved_at_utc": retrieved_at, "error": str(exc),
            })
            print(f"[{idx}/{len(planned)}] FAILED VALIDATION {eid}: {exc}")
            time.sleep(max(args.sleep_seconds, 0))
            continue

        psummary, prows = summarize_products(detail_obj)
        returned_id = detail_obj.get("id", "")
        sidecar_obj = {
            "schema_version": "1.0",
            "source": "USGS ANSS ComCat GeoJSON Detail",
            "requested_event_id": eid,
            "returned_feature_id": returned_id,
            "identity_match_status": identity_status,
            "request_url": url,
            "detail_url_source": url_source,
            "request_method": "GET",
            "http_status": http_status,
            "retrieved_at_utc": retrieved_at,
            "response_content_type": "application/geo+json or application/json",
            "detail_response_file": detail_path.name,
            "detail_response_bytes": len(response_bytes),
            "detail_response_sha256": sha256_bytes(response_bytes),
            "product_version_counts": psummary,
            "product_versions_total": sum(psummary.values()),
            "product_attachments_downloaded": False,
            "note": "Detail JSON is preserved byte-for-byte. Product content attachments were not downloaded.",
        }
        sidecar_bytes = (json.dumps(sidecar_obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        detail_rel = detail_path.relative_to(BASE).as_posix()
        sidecar_rel = sidecar_path.relative_to(BASE).as_posix()
        event_time = str(cat_by_id[eid].get("origin_time_utc", ""))
        new_manifest_rows = create_manifest_rows(
            eid, event_time, url, retrieved_at,
            detail_rel, response_bytes, sidecar_rel, sidecar_bytes,
            licence, identity_status,
        )
        # Persist raw response and sidecar, then immediately append their hashes to the manifest.
        atomic_write_bytes(detail_path, response_bytes)
        atomic_write_bytes(sidecar_path, sidecar_bytes)
        try:
            manifest_rows = update_manifest(manifest_path, manifest_columns, manifest_rows, new_manifest_rows)
        except Exception:
            # Preserve the files for forensic recovery; do not delete downloaded source bytes.
            raise
        for pr in prows:
            pr["requested_event_id"] = eid
            product_rows.append(pr)
        success += 1
        report_rows.append({
            "event_id": eid, "status": "downloaded_and_verified",
            "http_status": http_status, "identity_match_status": identity_status,
            "detail_relative_path": detail_rel, "sha256": sha256_bytes(response_bytes),
            "product_types": json.dumps(psummary, sort_keys=True),
            "retrieved_at_utc": retrieved_at, "error": "",
        })
        print(f"[{idx}/{len(planned)}] OK {eid} | products={sum(psummary.values())} | {identity_status}")
        time.sleep(max(args.sleep_seconds, 0))

    report_columns = [
        "event_id", "status", "http_status", "identity_match_status",
        "detail_relative_path", "sha256", "product_types", "retrieved_at_utc", "error",
    ]
    write_csv_atomic(report_path, report_columns, report_rows)
    product_columns = [
        "requested_event_id", "returned_event_id", "product_type", "source",
        "code", "product_id", "update_time_utc", "status", "preferred_weight",
        "content_count", "content_names",
    ]
    write_csv_atomic(product_index_path, product_columns, product_rows)

    print("\nCOMCAT DETAIL RETRIEVAL COMPLETE")
    print(f"Downloaded and manifest-registered          : {success}")
    print(f"Already complete; verified and skipped     : {skipped}")
    print(f"Failed retrieval/validation                 : {failures}")
    print(f"Manifest rows currently                     : {len(manifest_rows)}")
    print(f"Retrieval status report                     : {report_path.relative_to(BASE).as_posix() if report_path.is_relative_to(BASE) else report_path}")
    print(f"Product index                               : {product_index_path.relative_to(BASE).as_posix() if product_index_path.is_relative_to(BASE) else product_index_path}")
    print("Raw detail response bytes were not edited; product attachments were not downloaded.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
