#!/usr/bin/env python3
"""Retrieve three out-of-catalogue ComCat counterpart records for Stage 1B.2.

Safety:
- Dry-run is the default; --execute is required for network requests and writes.
- Does not add these counterpart events to event_catalogue_v002.csv.
- Does not alter existing detail responses or product attachments.
- Preserves raw response bytes and records SHA-256 in sidecars + data_manifest.csv.
- Uses the USGS FDSN eventid query with includesuperseded=true to retain product history.
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

COUNTERPART_IDS = ["ci10169070", "at00s53wgj", "usc0007dax"]
BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MANIFEST_COLUMNS = [
    "manifest_id", "source_id", "provider", "product", "product_version",
    "source_url", "local_relative_path", "start_time_utc", "end_time_utc",
    "download_time_utc", "file_size_bytes", "sha256", "licence_or_terms",
    "processing_status", "notes",
]
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_id(path_value: str) -> str:
    return "USGS-DET-" + hashlib.sha256(path_value.encode("utf-8")).hexdigest()[:12]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required file is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv_atomic(path: Path, columns: list[str], rows: list[dict[str, Any]], bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: "" if v is None else json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    temp.replace(path)


def build_url(event_id: str) -> str:
    # includesuperseded is only valid with eventid and includes all superseded/deleted
    # product versions. It is not combined with includedeleted (mutually exclusive).
    query = urllib.parse.urlencode({
        "eventid": event_id,
        "format": "geojson",
        "includesuperseded": "true",
    })
    return BASE_URL + "?" + query


def parse_detail(data: bytes, requested_id: str) -> tuple[dict[str, Any], str]:
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("type") != "Feature":
        got = obj.get("type") if isinstance(obj, dict) else type(obj).__name__
        raise ValueError(f"Expected one GeoJSON Feature, got type={got}")
    returned_id = str(obj.get("id") or "").strip()
    if not returned_id:
        raise ValueError("GeoJSON Feature has no top-level id")
    props = obj.get("properties") or {}
    aliases = {
        token.strip().strip(",").lower()
        for token in str(props.get("ids") or "").split(",")
        if token.strip().strip(",")
    }
    if returned_id.lower() == requested_id.lower():
        status = "exact_id_match"
    elif requested_id.lower() in aliases:
        status = "requested_id_listed_in_associated_ids"
    else:
        raise ValueError(
            f"Requested counterpart ID not verified: requested={requested_id}; "
            f"returned={returned_id}; requested_in_properties_ids={requested_id.lower() in aliases}"
        )
    return obj, status


def product_index_rows(detail: dict[str, Any], requested_id: str) -> list[dict[str, Any]]:
    products = (detail.get("properties") or {}).get("products") or {}
    rows: list[dict[str, Any]] = []
    if not isinstance(products, dict):
        return rows
    for product_type, versions in products.items():
        if not isinstance(versions, list):
            continue
        for product in versions:
            if not isinstance(product, dict):
                continue
            update_ms = product.get("updateTime")
            rows.append({
                "requested_event_id": requested_id,
                "returned_event_id": detail.get("id", ""),
                "product_type": product_type,
                "source": product.get("source", ""),
                "code": product.get("code", ""),
                "product_id": product.get("id", ""),
                "update_time_utc": iso_ms(update_ms),
                "status": product.get("status", ""),
                "preferred_weight": product.get("preferredWeight", ""),
                "content_count": len(product.get("contents") or {}) if isinstance(product.get("contents") or {}, dict) else 0,
                "content_names": ";".join(sorted((product.get("contents") or {}).keys())) if isinstance(product.get("contents") or {}, dict) else "",
            })
    return rows


def request_bytes(url: str, timeout: int) -> tuple[bytes, int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LAIC-GUARD/1.0 (research data retrieval; ComCat identity adjudication)",
            "Accept": "application/geo+json, application/json;q=0.9, */*;q=0.5",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), int(response.status), response.headers.get("Content-Type", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="LAIC-GUARD project root")
    parser.add_argument("--execute", action="store_true", help="Make network requests and write counterpart files/manifest")
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest = root / "metadata" / "data_manifest.csv"
    raw_dir = root / "data" / "raw" / "usgs_event_details"
    outdir = root / "reports" / "stage1b" / "adjudication"
    if not manifest.is_file():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 2
    if not raw_dir.is_dir():
        print(f"ERROR: detail directory not found: {raw_dir}", file=sys.stderr)
        return 2

    try:
        columns, rows = read_csv(manifest)
        if columns != MANIFEST_COLUMNS:
            raise ValueError(f"Manifest columns do not match Stage 1A schema: {columns}")
        paths = {r["local_relative_path"]: r for r in rows}
        ids = {r["manifest_id"] for r in rows}
        plans = []
        for event_id in COUNTERPART_IDS:
            if not SAFE_ID.fullmatch(event_id):
                raise ValueError(f"Unsafe hard-coded event ID: {event_id}")
            detail_path = raw_dir / f"{event_id}.detail.geojson"
            sidecar_path = raw_dir / f"{event_id}.detail.metadata.json"
            rel_detail = detail_path.relative_to(root).as_posix()
            rel_sidecar = sidecar_path.relative_to(root).as_posix()
            have_detail, have_sidecar = detail_path.exists(), sidecar_path.exists()
            if have_detail != have_sidecar:
                raise ValueError(f"Partial counterpart files exist for {event_id}; manual recovery required")
            existing = []
            if have_detail:
                for p, rel in ((detail_path, rel_detail), (sidecar_path, rel_sidecar)):
                    mrow = paths.get(rel)
                    if mrow is None:
                        raise ValueError(f"Existing counterpart file is not registered in manifest: {rel}")
                    data = p.read_bytes()
                    if len(data) != int(mrow["file_size_bytes"]) or sha256(data) != mrow["sha256"]:
                        raise ValueError(f"Existing counterpart file fails manifest hash/size check: {rel}")
                existing.append(True)
            else:
                if rel_detail in paths or rel_sidecar in paths:
                    raise ValueError(f"Manifest references missing counterpart file(s) for {event_id}")
                existing.append(False)
            plans.append((event_id, detail_path, sidecar_path, build_url(event_id), existing[0]))
        new_manifest_ids = [manifest_id(p.relative_to(root).as_posix()) for _, d, s, _, _ in plans for p in (d, s)]
        if len(new_manifest_ids) != len(set(new_manifest_ids)):
            raise ValueError("New counterpart manifest-ID collision")
        for mid in new_manifest_ids:
            if mid not in ids:
                continue
            # Existing verified paths are handled above; an unexplained ID collision is unsafe.
            if not any(manifest_id(p.relative_to(root).as_posix()) == mid and p.exists() for _, d, s, _, _ in plans for p in (d, s)):
                raise ValueError(f"Manifest ID collision: {mid}")
    except Exception as exc:
        print(f"ERROR: input validation failed: {exc}", file=sys.stderr)
        return 2

    print("STAGE 1B.2 COUNTERPART DETAIL RETRIEVAL — " + ("EXECUTION MODE" if args.execute else "DRY-RUN MODE"))
    print(f"Counterpart IDs selected                 : {len(plans)}")
    print(f"Already complete and hash-verified        : {sum(1 for p in plans if p[4])}")
    print(f"New detail requests planned               : {sum(1 for p in plans if not p[4])}")
    print(f"Existing manifest rows                    : {len(rows)}")
    print("Catalogue modification                    : NO")
    print("Product attachments downloaded            : NO")
    for event_id, _, _, url, complete in plans:
        print(f"  {event_id}: {'VERIFIED / SKIP' if complete else 'REQUEST'} | {url}")
    if not args.execute:
        print("No network requests were made; no files or manifest rows were changed.")
        print("After reviewing the three planned IDs, rerun with --execute to retrieve them.")
        return 0

    licence = next((r["licence_or_terms"] for r in rows if r["source_id"] == "USGS_COMCAT" and r["licence_or_terms"]),
                   "USGS public ComCat service; verify and follow current USGS attribution/terms before redistribution")
    retrieval_rows: list[dict[str, Any]] = []
    product_rows: list[dict[str, Any]] = []
    success = skipped = failures = 0

    for number, (event_id, detail_path, sidecar_path, url, complete) in enumerate(plans, 1):
        if complete:
            detail_bytes = detail_path.read_bytes()
            detail_obj, identity_status = parse_detail(detail_bytes, event_id)
            indexed = product_index_rows(detail_obj, event_id)
            product_rows.extend(indexed)
            retrieval_rows.append({"requested_event_id": event_id, "returned_event_id": detail_obj.get("id", ""),
                                   "status": "already_verified_skip", "identity_match_status": identity_status,
                                   "http_status": 200, "detail_relative_path": detail_path.relative_to(root).as_posix(),
                                   "sha256": sha256(detail_bytes), "product_versions": len(indexed), "error": ""})
            skipped += 1
            continue

        response = None
        http_status = ""
        content_type = ""
        error = ""
        retrieved_at = utc_now()
        for attempt in range(1, args.retries + 1):
            try:
                response, http_status, content_type = request_bytes(url, args.timeout)
                break
            except urllib.error.HTTPError as exc:
                http_status = exc.code
                error = f"HTTP {exc.code}: {exc.reason}"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if attempt < args.retries:
                time.sleep(min(2 ** (attempt - 1), 8))

        if response is None:
            failures += 1
            retrieval_rows.append({"requested_event_id": event_id, "returned_event_id": "", "status": "download_failed",
                                   "identity_match_status": "", "http_status": http_status,
                                   "detail_relative_path": "", "sha256": "", "product_versions": 0, "error": error})
            print(f"[{number}/{len(plans)}] FAILED {event_id}: {error}")
            time.sleep(max(args.sleep_seconds, 0))
            continue

        try:
            detail_obj, identity_status = parse_detail(response, event_id)
        except Exception as exc:
            failures += 1
            retrieval_rows.append({"requested_event_id": event_id, "returned_event_id": "", "status": "identity_or_format_failed",
                                   "identity_match_status": "", "http_status": http_status,
                                   "detail_relative_path": "", "sha256": sha256(response), "product_versions": 0,
                                   "error": str(exc)})
            print(f"[{number}/{len(plans)}] FAILED VALIDATION {event_id}: {exc}")
            time.sleep(max(args.sleep_seconds, 0))
            continue

        indexed = product_index_rows(detail_obj, event_id)
        props = detail_obj.get("properties") or {}
        retrieved_at = utc_now()
        sidecar_obj = {
            "schema_version": "1.0",
            "source": "USGS ANSS ComCat FDSN Event Web Service GeoJSON Detail",
            "requested_event_id": event_id,
            "returned_feature_id": detail_obj.get("id", ""),
            "identity_match_status": identity_status,
            "request_url": url,
            "request_method": "GET",
            "http_status": http_status,
            "response_content_type": content_type,
            "retrieved_at_utc": retrieved_at,
            "detail_response_file": detail_path.name,
            "detail_response_bytes": len(response),
            "detail_response_sha256": sha256(response),
            "product_version_counts": {k: len(v) for k, v in (props.get("products") or {}).items() if isinstance(v, list)},
            "product_versions_total": len(indexed),
            "product_attachments_downloaded": False,
            "request_includes_superseded": True,
            "note": "Counterpart-only retrieval for Stage 1B.2 identity review; does not add the event to event_catalogue_v002.csv. Raw response bytes preserved unchanged.",
        }
        sidecar_bytes = (json.dumps(sidecar_obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        detail_rel = detail_path.relative_to(root).as_posix()
        sidecar_rel = sidecar_path.relative_to(root).as_posix()
        event_time = iso_ms(props.get("time"))
        common = {
            "source_id": "USGS_COMCAT", "provider": "U.S. Geological Survey",
            "product_version": "USGS FDSN Event Web Service GeoJSON; eventid query; includesuperseded=true",
            "source_url": url, "start_time_utc": event_time, "end_time_utc": event_time,
            "download_time_utc": retrieved_at, "licence_or_terms": licence,
            "processing_status": "downloaded_hashed",
        }
        new_rows = [
            {"manifest_id": manifest_id(detail_rel), **common,
             "product": "USGS ComCat counterpart GeoJSON event detail response", "local_relative_path": detail_rel,
             "file_size_bytes": len(response), "sha256": sha256(response),
             "notes": f"Counterpart-only retrieval for {event_id}; returned feature={detail_obj.get('id')}; identity={identity_status}; not added to candidate catalogue."},
            {"manifest_id": manifest_id(sidecar_rel), **common,
             "product": "USGS ComCat counterpart event detail retrieval sidecar", "local_relative_path": sidecar_rel,
             "file_size_bytes": len(sidecar_bytes), "sha256": sha256(sidecar_bytes),
             "notes": f"Request and hash metadata for counterpart-only retrieval {event_id}."},
        ]
        # Recheck collisions immediately before writing.
        current_paths = {r["local_relative_path"] for r in rows}
        current_mids = {r["manifest_id"] for r in rows}
        if detail_rel in current_paths or sidecar_rel in current_paths or any(r["manifest_id"] in current_mids for r in new_rows):
            raise RuntimeError(f"Manifest collision detected while processing {event_id}; no overwrite attempted")

        detail_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_bytes(response)
        sidecar_path.write_bytes(sidecar_bytes)
        bom = manifest.read_bytes().startswith(bytes((239, 187, 191)))
        rows.extend([{k: str(r.get(k, "")) for k in columns} for r in new_rows])
        write_csv_atomic(manifest, columns, rows, bom=bom)
        product_rows.extend(indexed)
        retrieval_rows.append({"requested_event_id": event_id, "returned_event_id": detail_obj.get("id", ""),
                               "status": "downloaded_and_verified", "identity_match_status": identity_status,
                               "http_status": http_status, "detail_relative_path": detail_rel,
                               "sha256": sha256(response), "product_versions": len(indexed), "error": ""})
        success += 1
        print(f"[{number}/{len(plans)}] OK {event_id} -> {detail_obj.get('id')} | products={len(indexed)} | {identity_status}")
        time.sleep(max(args.sleep_seconds, 0))

    status_cols = ["requested_event_id", "returned_event_id", "status", "identity_match_status", "http_status",
                   "detail_relative_path", "sha256", "product_versions", "error"]
    index_cols = ["requested_event_id", "returned_event_id", "product_type", "source", "code", "product_id",
                  "update_time_utc", "status", "preferred_weight", "content_count", "content_names"]
    write_csv_atomic(outdir / "counterpart_detail_retrieval_status_v001.csv", status_cols, retrieval_rows)
    write_csv_atomic(outdir / "counterpart_detail_product_index_v001.csv", index_cols, product_rows)
    print("\nCOUNTERPART DETAIL RETRIEVAL COMPLETE")
    print(f"Downloaded and manifest-registered : {success}")
    print(f"Already complete; verified/skipped: {skipped}")
    print(f"Failed retrieval/validation        : {failures}")
    print(f"Manifest rows currently            : {len(rows)}")
    print(f"Output directory                   : {outdir}")
    print("Candidate catalogue modified       : NO")
    print("Product attachments downloaded     : NO")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
