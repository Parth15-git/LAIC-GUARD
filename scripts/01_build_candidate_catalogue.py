#!/usr/bin/env python3
"""Build the first reproducible USGS ComCat candidate earthquake catalogue.

This script deliberately creates a BROAD candidate catalogue. It does not decide
which magnitude types, depths, or earthquake sequences qualify for the final study.
It preserves preferred magnitude and magnitude type exactly as returned by USGS.

Examples (PowerShell, from the LAIC-GUARD project root):
  python scripts/01_build_candidate_catalogue.py --count-only
  python scripts/01_build_candidate_catalogue.py
  python scripts/01_build_candidate_catalogue.py --start-year 2000 --end-year 2025 --min-magnitude 6.5

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://earthquake.usgs.gov/fdsnws/event/1"
USER_AGENT = "LAIC-GUARD-research/0.1 (reproducible research catalogue client)"
API_MAX_LIMIT = 20_000
SAFE_SPLIT_COUNT = 18_000
VERSION = "v001"

EVENT_FIELDS = [
    "event_id", "origin_time_utc", "latitude_deg", "longitude_deg", "depth_km",
    "magnitude", "magnitude_type", "event_type", "sequence_id", "tectonic_region",
    "candidate_status", "inclusion_reason", "source_url", "catalogue_version",
    "place", "network", "network_code", "preferred_event_url", "updated_time_utc",
    "event_status", "magnitude_family", "depth_screening_status",
    "query_chunk_start_utc", "query_chunk_end_utc", "raw_geojson_path",
]
MANIFEST_FIELDS = [
    "manifest_id", "source_id", "provider", "product", "product_version",
    "source_url", "local_relative_path", "start_time_utc", "end_time_utc",
    "download_time_utc", "file_size_bytes", "sha256", "licence_or_terms",
    "processing_status", "notes",
]
COUNT_FIELDS = [
    "chunk_start_utc", "chunk_end_utc", "expected_event_count", "split_level", "status"
]

MOMENT_MAG_TYPES = {"mww", "mwc", "mwb", "mwr", "mwp"}


@dataclass
class Chunk:
    start: datetime
    end: datetime  # inclusive
    count: int
    level: int


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc_date(value: str) -> datetime:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD, got {value!r}") from exc
    return dt


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def request_bytes(url: str, retries: int = 5) -> tuple[int, bytes]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json, text/plain"}
    for attempt in range(retries + 1):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=90) as response:
                return response.status, response.read()
        except HTTPError as exc:
            body = exc.read()
            if exc.code == 204:
                return 204, b""
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                wait = min(60, 2 ** attempt)
                logging.warning("HTTP %s; retrying in %ss", exc.code, wait)
                time.sleep(wait)
                continue
            message = body.decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"USGS HTTP {exc.code} for {url}\n{message}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt >= retries:
                raise RuntimeError(f"Network failure for {url}: {exc}") from exc
            wait = min(60, 2 ** attempt)
            logging.warning("Network error; retrying in %ss: %s", wait, exc)
            time.sleep(wait)
    raise RuntimeError("Request failed after retries")


def build_params(start: datetime, end: datetime, min_magnitude: float, fmt: str) -> dict[str, str]:
    # eventtype=earthquake avoids non-earthquake ComCat event types.
    # We intentionally DO NOT filter on a presumed Mw-only list here. The broad
    # candidate catalogue retains the magnitude type for a separately documented screen.
    return {
        "format": fmt,
        "starttime": utc_iso(start),
        "endtime": utc_iso(end),
        "minmagnitude": f"{min_magnitude:g}",
        "eventtype": "earthquake",
        "orderby": "time-asc",
    }


def get_count(start: datetime, end: datetime, min_magnitude: float) -> int:
    params = build_params(start, end, min_magnitude, "text")
    url = f"{API_BASE}/count?{urlencode(params)}"
    status, body = request_bytes(url)
    if status == 204 or not body.strip():
        return 0
    text = body.decode("utf-8", errors="replace").strip()
    try:
        count = int(text)
    except ValueError as exc:
        raise RuntimeError(f"Could not parse USGS count response: {text[:300]!r}") from exc
    if count < 0:
        raise RuntimeError(f"USGS returned negative count: {count}")
    return count


def split_interval(start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    # Millisecond resolution matches the service's ISO-8601 time support.
    span_ms = int((end - start).total_seconds() * 1000)
    if span_ms < 2:
        raise RuntimeError("Cannot split interval further at millisecond precision")
    left_span_ms = span_ms // 2
    midpoint = start + timedelta(milliseconds=left_span_ms)
    left_end = midpoint - timedelta(milliseconds=1)
    right_start = midpoint
    return (start, left_end), (right_start, end)


def discover_chunks(start: datetime, end: datetime, min_magnitude: float, level: int = 0) -> list[Chunk]:
    count = get_count(start, end, min_magnitude)
    if count >= SAFE_SPLIT_COUNT:
        left, right = split_interval(start, end)
        logging.info("Splitting %s to %s (%s events; split level %s)", utc_iso(start), utc_iso(end), count, level)
        return (
            discover_chunks(left[0], left[1], min_magnitude, level + 1)
            + discover_chunks(right[0], right[1], min_magnitude, level + 1)
        )
    return [Chunk(start=start, end=end, count=count, level=level)]


def year_intervals(start_year: int, end_year: int) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for year in range(start_year, end_year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        next_year = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        end = next_year - timedelta(milliseconds=1)
        intervals.append((start, end))
    return intervals


def parse_epoch_ms(value: Any) -> str:
    if value is None:
        return ""
    try:
        dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        return utc_iso(dt)
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def magnitude_family(mag_type: Any) -> str:
    mt = str(mag_type or "").strip().lower()
    if mt in MOMENT_MAG_TYPES:
        return "moment_magnitude_family"
    if mt:
        return "other_or_non_moment_type"
    return "unknown_mag_type"


def chunk_stem(chunk: Chunk) -> str:
    s = chunk.start.strftime("%Y%m%dT%H%M%S")
    e = chunk.end.strftime("%Y%m%dT%H%M%S")
    return f"usgs_comcat_candidate_events_{s}_{e}_{VERSION}"


def fetch_chunk(chunk: Chunk, min_magnitude: float, raw_dir: Path, overwrite: bool) -> tuple[list[dict[str, Any]], Path, str]:
    params = build_params(chunk.start, chunk.end, min_magnitude, "geojson")
    params["limit"] = str(API_MAX_LIMIT)
    url = f"{API_BASE}/query?{urlencode(params)}"
    stem = chunk_stem(chunk)
    raw_path = raw_dir / f"{stem}.geojson"
    sidecar_path = raw_dir / f"{stem}.query.json"
    if raw_path.exists() and not overwrite:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        logging.info("Reusing existing raw file: %s", raw_path)
    else:
        status, body = request_bytes(url)
        if status == 204 or not body.strip():
            payload = {"type": "FeatureCollection", "metadata": {"count": 0, "status": status}, "features": []}
            body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        else:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict) or "features" not in payload:
                raise RuntimeError(f"Unexpected GeoJSON structure from {url}")
            # Save exactly the downloaded response bytes.
        atomic_write(raw_path, body)
        sidecar = {
            "provider": "USGS ComCat",
            "api_endpoint": url,
            "parameters": params,
            "retrieved_at_utc": utc_iso(datetime.now(timezone.utc)),
            "expected_count_from_count_endpoint": chunk.count,
            "returned_count": len(payload.get("features", [])),
            "api_metadata": payload.get("metadata", {}),
        }
        atomic_write(sidecar_path, (json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    features = payload.get("features", [])
    actual_count = len(features)
    if actual_count != chunk.count:
        logging.warning(
            "Count/query difference for %s: count endpoint=%s, returned features=%s. "
            "This can occur if the catalogue changes between requests; preserve and inspect.",
            raw_path.name, chunk.count, actual_count
        )
    return features, raw_path, url


def feature_to_row(feature: dict[str, Any], chunk: Chunk, raw_path: Path, query_url: str) -> dict[str, Any]:
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    lon = coords[0] if len(coords) > 0 else ""
    lat = coords[1] if len(coords) > 1 else ""
    depth = coords[2] if len(coords) > 2 else ""
    mag = props.get("mag")
    mag_type = props.get("magType") or ""
    event_id = feature.get("id") or props.get("ids") or ""
    return {
        "event_id": event_id,
        "origin_time_utc": parse_epoch_ms(props.get("time")),
        "latitude_deg": lat,
        "longitude_deg": lon,
        "depth_km": depth,
        "magnitude": mag if mag is not None else "",
        "magnitude_type": mag_type,
        "event_type": props.get("type", "earthquake"),
        "sequence_id": "",  # assigned only after a documented sequence algorithm is selected
        "tectonic_region": "",  # added only from a documented tectonic-region source
        "candidate_status": "candidate_unreviewed",
        "inclusion_reason": f"Returned by USGS ComCat minmagnitude>={mag if mag is not None else 'unknown'} query threshold; magnitude type and depth not yet screened.",
        "source_url": query_url,
        "catalogue_version": VERSION,
        "place": props.get("place", ""),
        "network": props.get("net", ""),
        "network_code": props.get("code", ""),
        "preferred_event_url": props.get("url", ""),
        "updated_time_utc": parse_epoch_ms(props.get("updated")),
        "event_status": props.get("status", ""),
        "magnitude_family": magnitude_family(mag_type),
        "depth_screening_status": "not_screened",
        "query_chunk_start_utc": utc_iso(chunk.start),
        "query_chunk_end_utc": utc_iso(chunk.end),
        "raw_geojson_path": str(raw_path).replace("\\", "/"),
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp.replace(path)


def append_manifest(project_root: Path, records: list[dict[str, Any]]) -> None:
    path = project_root / "metadata" / "data_manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and set(MANIFEST_FIELDS).issubset(set(reader.fieldnames)):
                existing = list(reader)
            else:
                backup = path.with_name(f"data_manifest_pre_catalogue_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv")
                path.replace(backup)
                logging.warning("Manifest schema differed; old file preserved as %s", backup)
    by_path = {r.get("local_relative_path"): r for r in existing}
    for record in records:
        by_path[record["local_relative_path"]] = record
    write_csv(path, MANIFEST_FIELDS, list(by_path.values()))


def make_manifest_record(project_root: Path, path: Path, source_url: str, start: datetime, end: datetime,
                         product: str, notes: str) -> dict[str, Any]:
    rel = str(path.relative_to(project_root)).replace("\\", "/")
    return {
        "manifest_id": f"USGS-{hashlib.sha1(rel.encode()).hexdigest()[:12]}",
        "source_id": "USGS_COMCAT",
        "provider": "U.S. Geological Survey",
        "product": product,
        "product_version": "FDSN Event Web Service; record response metadata in sidecar",
        "source_url": source_url,
        "local_relative_path": rel,
        "start_time_utc": utc_iso(start),
        "end_time_utc": utc_iso(end),
        "download_time_utc": utc_iso(datetime.now(timezone.utc)),
        "file_size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "licence_or_terms": "USGS public ComCat service; verify and follow current USGS attribution/terms before redistribution",
        "processing_status": "downloaded_hashed",
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reproducible USGS ComCat candidate earthquake catalogue.")
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=2025, help="Inclusive end year")
    parser.add_argument("--min-magnitude", type=float, default=6.5)
    parser.add_argument("--count-only", action="store_true", help="Count candidates by year/chunk without downloading event records")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned year intervals without contacting USGS")
    parser.add_argument("--overwrite", action="store_true", help="Redownload raw response files even if they already exist")
    args = parser.parse_args()

    if args.start_year < 1900 or args.end_year < args.start_year or args.end_year > datetime.now(timezone.utc).year:
        parser.error("Provide a valid year range; end-year cannot be in the future.")
    if not math.isfinite(args.min_magnitude) or args.min_magnitude < 0 or args.min_magnitude > 10:
        parser.error("--min-magnitude must be between 0 and 10.")

    project_root = Path(__file__).resolve().parents[1]
    raw_dir = project_root / "data" / "raw" / "usgs"
    report_dir = project_root / "reports" / "coverage_audit"
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
    intervals = year_intervals(args.start_year, args.end_year)

    if args.dry_run:
        print(f"Project root: {project_root}")
        print(f"Candidate magnitude query: minmagnitude={args.min_magnitude:g} (NOT an Mw-only filter)")
        for start, end in intervals:
            print(f"{utc_iso(start)} -> {utc_iso(end)}")
        print(f"Planned annual intervals: {len(intervals)}")
        return 0

    chunks: list[Chunk] = []
    count_rows: list[dict[str, Any]] = []
    logging.info("Counting candidate events for %s–%s", args.start_year, args.end_year)
    for start, end in intervals:
        found = discover_chunks(start, end, args.min_magnitude)
        chunks.extend(found)
        for chunk in found:
            count_rows.append({
                "chunk_start_utc": utc_iso(chunk.start),
                "chunk_end_utc": utc_iso(chunk.end),
                "expected_event_count": chunk.count,
                "split_level": chunk.level,
                "status": "counted",
            })
        total = sum(c.count for c in found)
        logging.info("%s: %s candidate events across %s chunk(s)", start.year, total, len(found))

    count_csv = report_dir / f"usgs_catalogue_count_audit_{args.start_year}_{args.end_year}_{VERSION}.csv"
    write_csv(count_csv, COUNT_FIELDS, count_rows)
    count_total = sum(c.count for c in chunks)
    logging.info("Total count returned by USGS count endpoint: %s", count_total)
    logging.info("Count audit saved: %s", count_csv)

    # Register the manual smoke-test response supplied during setup, if present.
    # This ensures that even the first connectivity test has a traceable checksum.
    smoke_test = project_root / "data" / "raw" / "usgs_test_2000-01-01_2000-01-10.geojson"
    if smoke_test.exists():
        try:
            smoke_payload = json.loads(smoke_test.read_text(encoding="utf-8"))
            smoke_url = (smoke_payload.get("metadata") or {}).get("url", "USGS FDSN test query; see raw test file")
        except (json.JSONDecodeError, OSError):
            smoke_url = "USGS FDSN test query; response metadata could not be parsed"
        smoke_record = make_manifest_record(
            project_root, smoke_test, smoke_url,
            datetime(2000, 1, 1, tzinfo=timezone.utc),
            datetime(2000, 1, 10, 23, 59, 59, 999000, tzinfo=timezone.utc),
            "USGS ComCat smoke-test GeoJSON",
            "Initial API connectivity test; preserved as a test artifact, not merged as a separate catalogue source."
        )
        append_manifest(project_root, [smoke_record])
        logging.info("Registered smoke-test file in metadata/data_manifest.csv")

    if args.count_only:
        print("\nCOUNT-ONLY COMPLETE — no full event catalogue downloaded.")
        print(f"Candidate count: {count_total}")
        print(f"Count audit: {count_csv.relative_to(project_root)}")
        print("Next: inspect annual counts and confirm no chunk is close to the USGS 20,000-event query limit.")
        return 0

    all_rows: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    query_log: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        logging.info("Downloading chunk %s/%s: %s to %s (%s expected)", index, len(chunks), utc_iso(chunk.start), utc_iso(chunk.end), chunk.count)
        features, raw_path, query_url = fetch_chunk(chunk, args.min_magnitude, raw_dir, args.overwrite)
        sidecar_path = raw_path.with_suffix(".query.json")
        if not sidecar_path.exists():
            sidecar = {
                "provider": "USGS ComCat", "api_endpoint": query_url,
                "retrieved_at_utc": utc_iso(datetime.now(timezone.utc)),
                "expected_count_from_count_endpoint": chunk.count,
                "returned_count": len(features), "reused_existing_raw_file": True,
            }
            atomic_write(sidecar_path, (json.dumps(sidecar, indent=2) + "\n").encode("utf-8"))
        for feature in features:
            row = feature_to_row(feature, chunk, raw_path, query_url)
            event_id = str(row["event_id"])
            if not event_id:
                logging.warning("Skipping feature without an event ID in %s", raw_path.name)
                continue
            # Annual chunks should not overlap, but ID de-duplication protects against boundary repeats.
            previous = seen.get(event_id)
            if previous is None:
                seen[event_id] = row
            else:
                # Retain the row with the latest USGS update timestamp, but log any duplicate.
                logging.warning("Duplicate USGS event ID across chunks: %s", event_id)
                if str(row.get("updated_time_utc", "")) > str(previous.get("updated_time_utc", "")):
                    seen[event_id] = row
        manifest_records.append(make_manifest_record(
            project_root, raw_path, query_url, chunk.start, chunk.end,
            "USGS ComCat GeoJSON raw response", "Untouched USGS GeoJSON response; do not edit."
        ))
        manifest_records.append(make_manifest_record(
            project_root, sidecar_path, query_url, chunk.start, chunk.end,
            "USGS ComCat query sidecar", "Query parameters, retrieval timestamp and response metadata."
        ))
        query_log.append({
            "start_time_utc": utc_iso(chunk.start), "end_time_utc": utc_iso(chunk.end),
            "expected_count": chunk.count, "returned_count": len(features),
            "raw_geojson_path": str(raw_path.relative_to(project_root)).replace("\\", "/"),
            "raw_sha256": sha256_file(raw_path), "query_url": query_url,
        })

    all_rows = list(seen.values())
    all_rows.sort(key=lambda r: (r.get("origin_time_utc", ""), r.get("event_id", "")))
    catalogue_path = project_root / "metadata" / "event_catalogue.csv"
    write_csv(catalogue_path, EVENT_FIELDS, all_rows)
    catalogue_manifest = make_manifest_record(
        project_root, catalogue_path,
        f"{API_BASE}/query (annual UTC chunks; see reports and raw sidecars)",
        intervals[0][0], intervals[-1][1],
        "USGS ComCat candidate event catalogue CSV",
        "Derived from preserved raw GeoJSON chunks; candidate-only, magnitude type/depth/sequence not finalized."
    )
    manifest_records.append(catalogue_manifest)
    append_manifest(project_root, manifest_records)

    run_metadata = {
        "project": "LAIC-GUARD",
        "catalogue_version": VERSION,
        "provider": "USGS ComCat / FDSN Event Web Service",
        "retrieved_at_utc": utc_iso(datetime.now(timezone.utc)),
        "start_year": args.start_year,
        "end_year_inclusive": args.end_year,
        "minimum_magnitude_query": args.min_magnitude,
        "event_type_filter": "earthquake",
        "magnitude_filter_caveat": "This query is not a strict Mw-only catalogue. Preferred magnitude and magType are preserved; final magnitude-type eligibility must be decided separately.",
        "depth_filter": None,
        "chunks": query_log,
        "count_endpoint_total": count_total,
        "unique_event_rows": len(all_rows),
        "unique_event_ids": len(seen),
        "catalogue_csv": str(catalogue_path.relative_to(project_root)).replace("\\", "/"),
        "catalogue_sha256": sha256_file(catalogue_path),
        "raw_data_policy": "Raw response files are preserved unchanged in data/raw/usgs/.",
        "sequence_policy": "sequence_id intentionally blank until a documented sequence grouping rule is approved.",
        "depth_policy": "No depth exclusion applied; depth_km retained for later screening.",
    }
    metadata_path = report_dir / f"usgs_catalogue_retrieval_metadata_{args.start_year}_{args.end_year}_{VERSION}.json"
    atomic_write(metadata_path, (json.dumps(run_metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    print("\nCATALOGUE BUILD COMPLETE")
    print(f"USGS count endpoint total : {count_total}")
    print(f"Unique event rows         : {len(all_rows)}")
    print(f"Catalogue                 : {catalogue_path.relative_to(project_root)}")
    print(f"Catalogue SHA-256         : {sha256_file(catalogue_path)}")
    print(f"Raw chunks                : {len(chunks)}")
    print(f"Manifest                  : metadata/data_manifest.csv")
    print(f"Retrieval metadata        : {metadata_path.relative_to(project_root)}")
    print("NOTE: This is a candidate catalogue, not the final eligible earthquake sample.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Existing completed raw chunks have been preserved. Re-run to continue.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        logging.exception("Catalogue build failed: %s", exc)
        raise SystemExit(1)
