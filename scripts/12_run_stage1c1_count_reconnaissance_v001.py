#!/usr/bin/env python3
"""LAIC-GUARD Stage 1C.1 count-only USGS ComCat reconnaissance.

This script calls ONLY the USGS FDSN Event Web Service /count and /version
methods. It does not call /query and does not download event records.

Outputs are written to reports/stage1c1. The count results are reconnaissance
counts of the preferred numerical magnitude field, not counts of confirmed Mw.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"
COUNT_URL = BASE_URL + "/count"
VERSION_URL = BASE_URL + "/version"
SAFE_QUERY_CEILING = 18_000  # conservative planning ceiling below 20,000
REQUEST_INTERVAL_SECONDS = 0.5
TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 4

ROOT = Path.cwd()
OUTPUT_DIR = ROOT / "reports" / "stage1c1"
RAW_TARGET = ROOT / "metadata" / "event_catalogue_v002.csv"
EXPECTED_TARGET_SHA256 = "0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315"

THRESHOLDS = (4.0, 4.5, 5.0)

# These are coarse operational bounding boxes for reconnaissance, not
# tectonic-region polygons or mutually exclusive partitions. Boxes may overlap.
# Longitude 210 is valid under the USGS API's documented dateline-crossing rule.
REGIONS = [
    {"region_id": "GLOBAL", "label": "Global", "bounds": None},
    {"region_id": "W_NORTH_AMERICA", "label": "Western North America", "bounds": [-170.0, -105.0, 20.0, 72.0]},
    {"region_id": "CENTRAL_AMERICA_CARIBBEAN", "label": "Central America and Caribbean", "bounds": [-115.0, -50.0, 0.0, 32.0]},
    {"region_id": "ANDES", "label": "Andes", "bounds": [-85.0, -55.0, -60.0, 15.0]},
    {"region_id": "ALPINE_MEDITERRANEAN", "label": "Alpine-Mediterranean", "bounds": [-15.0, 45.0, 25.0, 55.0]},
    {"region_id": "EAST_AFRICA_ARABIA", "label": "East African Rift and Arabia", "bounds": [25.0, 60.0, -15.0, 30.0]},
    {"region_id": "HIMALAYA_TIBET", "label": "Himalaya-Tibet", "bounds": [60.0, 105.0, 20.0, 42.0]},
    {"region_id": "JAPAN_KURIL", "label": "Japan-Kuril", "bounds": [125.0, 180.0, 30.0, 60.0]},
    {"region_id": "SUNDA_INDONESIA", "label": "Sunda-Indonesia", "bounds": [90.0, 145.0, -15.0, 25.0]},
    {"region_id": "TONGA_KERMADEC_NZ", "label": "Tonga-Kermadec-New Zealand", "bounds": [160.0, 210.0, -50.0, -10.0]},
]

CSV_FIELDS = [
    "run_id", "request_id", "parent_request_id", "query_level", "region_id",
    "region_label", "minlongitude", "maxlongitude", "minlatitude", "maxlatitude",
    "magnitude_threshold", "magnitude_threshold_semantics", "eventtype",
    "starttime_utc", "endtime_utc", "count", "http_status", "response_state",
    "safe_for_future_query", "subdivision_required", "subdivision_resolution",
    "attempts", "request_url", "response_sha256", "response_bytes", "response_date_header",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_target_catalogue() -> tuple[int, str]:
    if not RAW_TARGET.is_file():
        raise FileNotFoundError(f"Frozen target catalogue not found: {RAW_TARGET}")
    with RAW_TARGET.open("rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with RAW_TARGET.open("r", encoding="utf-8-sig", newline="") as f:
        rows = sum(1 for _ in csv.DictReader(f))
    if rows != 1186:
        raise ValueError(f"Expected frozen v002 target catalogue with 1,186 rows; found {rows}.")
    if digest.lower() != EXPECTED_TARGET_SHA256:
        raise ValueError(
            "Frozen target catalogue SHA-256 differs from Stage 1A v002. "
            "Stop: do not run reconnaissance against a changed target catalogue."
        )
    return rows, digest


def base_periods(cutoff: datetime) -> list[dict[str, Any]]:
    # Half-open UTC intervals [start, end). Requests use end-1 ms to avoid
    # double-counting an event on the next interval boundary.
    periods: list[dict[str, Any]] = []
    definitions = [
        ("1980_1989", datetime(1980, 1, 1, tzinfo=timezone.utc), datetime(1990, 1, 1, tzinfo=timezone.utc)),
        ("1990_1999", datetime(1990, 1, 1, tzinfo=timezone.utc), datetime(2000, 1, 1, tzinfo=timezone.utc)),
        ("2000_2009", datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2010, 1, 1, tzinfo=timezone.utc)),
        ("2010_2019", datetime(2010, 1, 1, tzinfo=timezone.utc), datetime(2020, 1, 1, tzinfo=timezone.utc)),
    ]
    for pid, start, end in definitions:
        periods.append({"period_id": pid, "start": start, "end": end})
    periods.append({
        "period_id": "2020_to_acquisition_cutoff",
        "start": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "end": cutoff + timedelta(milliseconds=1),
    })
    return [p for p in periods if p["end"] > p["start"]]


def query_window(start: datetime, end_exclusive: datetime) -> tuple[str, str]:
    end_inclusive = end_exclusive - timedelta(milliseconds=1)
    return iso_utc(start), iso_utc(end_inclusive)


def params_for(region: dict[str, Any], threshold: float, start: datetime, end: datetime) -> dict[str, str]:
    start_s, end_s = query_window(start, end)
    params = {
        "format": "text",
        "nodata": "204",
        "starttime": start_s,
        "endtime": end_s,
        "minmagnitude": f"{threshold:.1f}",
        "eventtype": "earthquake",
    }
    bounds = region["bounds"]
    if bounds is not None:
        minlon, maxlon, minlat, maxlat = bounds
        params.update({
            "minlongitude": f"{minlon:g}",
            "maxlongitude": f"{maxlon:g}",
            "minlatitude": f"{minlat:g}",
            "maxlatitude": f"{maxlat:g}",
        })
    return params


@dataclass
class CountResult:
    count: int | None
    status: int | None
    state: str
    attempts: int
    body: bytes
    headers: dict[str, str]
    url: str
    error: str | None = None


class Client:
    def __init__(self, pause: float = REQUEST_INTERVAL_SECONDS, timeout: int = TIMEOUT_SECONDS):
        self.pause = pause
        self.timeout = timeout
        self.last_request_at = 0.0
        self.request_counter = 0
        self.request_log: list[dict[str, Any]] = []

    def _pace(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.pause:
            time.sleep(self.pause - elapsed)

    def get_text(self, url: str) -> CountResult:
        """Fetch a small text endpoint while preserving the exact response body."""
        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "LAIC-GUARD-Stage1C1/1.0 (reproducible scientific count reconnaissance)"},
                method="GET",
            )
            self.last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    status = int(response.status)
                    if status == 204 and not body:
                        return CountResult(None, status, "no_content_204", attempt, body, headers, url)
                    if status == 200:
                        return CountResult(None, status, "text_response", attempt, body, headers, url)
                    last_error = f"Unexpected HTTP status {status}"
            except urllib.error.HTTPError as exc:
                body = exc.read() if hasattr(exc, "read") else b""
                headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
                if exc.code == 204 and not body:
                    return CountResult(None, 204, "no_content_204", attempt, body, headers, url)
                last_error = f"HTTP {exc.code}: {body[:300].decode('utf-8', errors='replace')}"
                if exc.code not in (429, 500, 502, 503, 504):
                    return CountResult(None, exc.code, "http_error", attempt, body, headers, url, last_error)
                retry_after = headers.get("retry-after")
                if retry_after:
                    try:
                        wait = max(float(retry_after), 0.0)
                    except ValueError:
                        wait = 2 ** (attempt - 1)
                else:
                    wait = 2 ** (attempt - 1)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(min(wait, 60.0))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"Network error: {exc}"
                if attempt < MAX_ATTEMPTS:
                    time.sleep(2 ** (attempt - 1))
        return CountResult(None, None, "request_failed", MAX_ATTEMPTS, b"", {}, url, last_error)

    def count(self, params: dict[str, str]) -> CountResult:
        url = COUNT_URL + "?" + urllib.parse.urlencode(params)
        raw = self.get_text(url)
        if raw.status == 204 and not raw.body:
            return CountResult(0, 204, "no_data_204_zero", raw.attempts, raw.body, raw.headers, url)
        if raw.status != 200:
            return raw
        text = raw.body.decode("utf-8-sig").strip()
        if not text or not text.isdigit():
            return CountResult(None, raw.status, "invalid_count_response", raw.attempts, raw.body, raw.headers, url,
                               f"Count response was not a plain integer: {text[:200]!r}")
        return CountResult(int(text), raw.status, "ok", raw.attempts, raw.body, raw.headers, url)


def calendar_children(start: datetime, end: datetime) -> tuple[str, list[tuple[datetime, datetime]]]:
    """Split by year, then month, then day; do not go finer than daily."""
    duration = end - start
    boundaries: list[datetime] = []
    if duration > timedelta(days=370):
        kind = "year"
        cursor = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
        while cursor < end:
            if cursor > start:
                boundaries.append(cursor)
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
    elif duration > timedelta(days=32):
        kind = "month"
        year, month = start.year, start.month
        cursor = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
        while cursor < end:
            if cursor > start:
                boundaries.append(cursor)
            year, month = cursor.year, cursor.month
            cursor = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    elif duration > timedelta(days=1):
        kind = "day"
        cursor = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) + timedelta(days=1)
        while cursor < end:
            if cursor > start:
                boundaries.append(cursor)
            cursor += timedelta(days=1)
    else:
        return "daily_floor", []

    points = [start] + boundaries + [end]
    children = [(points[i], points[i + 1]) for i in range(len(points) - 1) if points[i + 1] > points[i]]
    return kind, children


def main() -> int:
    parser = argparse.ArgumentParser(description="Count-only USGS ComCat reconnaissance; no event records downloaded.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned base count grid without network requests.")
    parser.add_argument("--pause", type=float, default=REQUEST_INTERVAL_SECONDS, help="Minimum seconds between requests (default 0.5).")
    args = parser.parse_args()
    if args.pause < 0.25:
        parser.error("--pause must be at least 0.25 seconds for conservative request pacing.")

    cutoff = utc_now().replace(microsecond=(utc_now().microsecond // 1000) * 1000)
    run_id = cutoff.strftime("stage1c1_count_%Y%m%dT%H%M%SZ")
    periods = base_periods(cutoff)
    base_plan = [(region, threshold, period) for region in REGIONS for threshold in THRESHOLDS for period in periods]

    if args.dry_run:
        print("LAIC-GUARD STAGE 1C.1 — DRY RUN (NO NETWORK REQUESTS)")
        print(f"Target catalogue: {RAW_TARGET}")
        print(f"Acquisition cutoff candidate UTC: {iso_utc(cutoff)}")
        print(f"Regions/strata: {len(REGIONS)} (1 global + {len(REGIONS)-1} overlapping exploratory boxes)")
        print(f"Preferred numeric magnitude thresholds: {', '.join(f'{x:.1f}' for x in THRESHOLDS)}")
        print(f"Time periods: {len(periods)}")
        print(f"Planned base count requests: {len(base_plan)}")
        print(f"Subdivision ceiling: {SAFE_QUERY_CEILING}; subdivision hierarchy: year -> month -> day")
        print("IMPORTANT: geographic boxes overlap and are not tectonic-region definitions; do not sum them.")
        print("No /query endpoint is called; no event data is downloaded.")
        return 0

    target_rows, target_hash = load_target_catalogue()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = Client(pause=args.pause)
    rows: list[dict[str, Any]] = []
    request_log_path = OUTPUT_DIR / "reconnaissance_request_log_v001.jsonl"
    request_log_records: list[dict[str, Any]] = []
    errors = 0
    request_seq = 0

    # Record the USGS service version before the count grid.
    version_result = client.get_text(VERSION_URL)
    version_text = version_result.body.decode("utf-8-sig", errors="replace").strip()
    version_payload = {
        "run_id": run_id,
        "request_url": VERSION_URL,
        "http_status": version_result.status,
        "response_state": version_result.state,
        "response_text": version_text,
        "response_sha256": sha256_bytes(version_result.body),
        "retrieved_at_utc": iso_utc(utc_now()),
        "error": version_result.error,
    }

    def do_count(region: dict[str, Any], threshold: float, start: datetime, end: datetime,
                 level: str, parent_id: str | None = None, subdivision_resolution: str = "not_subdivided") -> dict[str, Any]:
        nonlocal request_seq, errors
        request_seq += 1
        request_id = f"R{request_seq:05d}"
        params = params_for(region, threshold, start, end)
        result = client.count(params)
        request_time = iso_utc(utc_now())
        bounds = region["bounds"]
        record = {
            "run_id": run_id,
            "request_id": request_id,
            "parent_request_id": parent_id or "",
            "query_level": level,
            "region_id": region["region_id"],
            "region_label": region["label"],
            "minlongitude": bounds[0] if bounds else "",
            "maxlongitude": bounds[1] if bounds else "",
            "minlatitude": bounds[2] if bounds else "",
            "maxlatitude": bounds[3] if bounds else "",
            "magnitude_threshold": threshold,
            "magnitude_threshold_semantics": "ComCat preferred numerical magnitude field; not a verified Mw-only threshold",
            "eventtype": "earthquake",
            "starttime_utc": iso_utc(start),
            "endtime_utc": iso_utc(end - timedelta(milliseconds=1)),
            "count": result.count if result.count is not None else "",
            "http_status": result.status if result.status is not None else "",
            "response_state": result.state,
            "safe_for_future_query": (result.count is not None and result.count <= SAFE_QUERY_CEILING),
            "subdivision_required": (result.count is not None and result.count > SAFE_QUERY_CEILING),
            "subdivision_resolution": subdivision_resolution,
            "attempts": result.attempts,
            "request_url": result.url,
            "response_sha256": sha256_bytes(result.body),
            "response_bytes": len(result.body),
            "response_date_header": result.headers.get("date", ""),
        }
        rows.append(record)
        request_log_records.append({
            "run_id": run_id,
            "request_id": request_id,
            "parent_request_id": parent_id,
            "retrieved_at_utc": request_time,
            "request_url": result.url,
            "request_parameters": params,
            "http_status": result.status,
            "response_state": result.state,
            "response_body_text": result.body.decode("utf-8", errors="replace"),
            "response_body_sha256": sha256_bytes(result.body),
            "response_bytes": len(result.body),
            "response_headers": result.headers,
            "attempts": result.attempts,
            "error": result.error,
        })
        if result.count is None:
            errors += 1
            print(f"[{request_id}] ERROR {region['region_id']} M>={threshold:.1f} {iso_utc(start)}: {result.error}")
        else:
            print(f"[{request_id}] {result.count:>8} {region['region_id']:<27} M>={threshold:.1f} {level}")
        return record

    # For every base stratum, count first. If above the conservative ceiling,
    # recursively count calendar children down to daily resolution.
    for region, threshold, period in base_plan:
        base = do_count(region, threshold, period["start"], period["end"], "base")
        if base["count"] == "" or int(base["count"]) <= SAFE_QUERY_CEILING:
            continue
        frontier = [(period["start"], period["end"], base["request_id"], 0)]
        while frontier:
            child_start, child_end, parent_id, depth = frontier.pop(0)
            resolution, children = calendar_children(child_start, child_end)
            if not children:
                # Daily count still exceeds the ceiling: preserve as unresolved.
                for prior in rows:
                    if prior["request_id"] == parent_id:
                        prior["subdivision_resolution"] = "daily_floor_exceeded_unresolved_for_future_query"
                        break
                continue
            for cstart, cend in children:
                child = do_count(region, threshold, cstart, cend, resolution, parent_id, resolution)
                if child["count"] != "" and int(child["count"]) > SAFE_QUERY_CEILING:
                    frontier.append((cstart, cend, child["request_id"], depth + 1))

    # Persist outputs, including an incomplete run if any requests failed.
    csv_path = OUTPUT_DIR / "reconnaissance_count_results_v001.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    with request_log_path.open("w", encoding="utf-8", newline="\n") as f:
        for item in request_log_records:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    counts = [int(r["count"]) for r in rows if r["count"] != ""]
    over_limit = [r for r in rows if r["count"] != "" and int(r["count"]) > SAFE_QUERY_CEILING]
    incomplete = [r for r in rows if r["count"] == ""]
    summary = {
        "project": "LAIC-GUARD",
        "stage": "1C.1",
        "run_id": run_id,
        "status": "complete" if not incomplete else "incomplete_request_errors",
        "method": "USGS FDSN Event Web Service count endpoint only",
        "count_endpoint": COUNT_URL,
        "version_endpoint": VERSION_URL,
        "service_version": version_payload,
        "acquisition_cutoff_utc": iso_utc(cutoff),
        "run_completed_at_utc": iso_utc(utc_now()),
        "frozen_target_catalogue": {
            "path": "metadata/event_catalogue_v002.csv",
            "rows": target_rows,
            "sha256": target_hash,
            "modified_by_script": False,
        },
        "thresholds": list(THRESHOLDS),
        "threshold_semantics": "Numerical preferred ComCat magnitude; not confirmed Mw-only counts",
        "periods": [{"period_id": p["period_id"], "start_utc": iso_utc(p["start"]), "end_inclusive_utc": iso_utc(p["end"] - timedelta(milliseconds=1))} for p in periods],
        "regional_strata": REGIONS,
        "regional_strata_caveat": "Exploratory bounding boxes; not tectonic polygons; some overlap; regional counts must not be summed to reproduce global totals.",
        "base_request_count": len(base_plan),
        "total_count_requests_including_subdivisions": len(rows),
        "successful_count_responses": len(rows) - len(incomplete),
        "failed_count_requests": len(incomplete),
        "http_204_zero_count_responses": sum(r["response_state"] == "no_data_204_zero" for r in rows),
        "counts_over_safe_query_ceiling": len(over_limit),
        "safe_query_ceiling": SAFE_QUERY_CEILING,
        "counts_minimum": min(counts) if counts else None,
        "counts_maximum": max(counts) if counts else None,
        "outputs": {
            "count_results_csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
            "request_response_log_jsonl": str(request_log_path.relative_to(ROOT)).replace("\\", "/"),
            "summary_json": "reports/stage1c1/reconnaissance_summary_v001.json",
            "report_markdown": "reports/stage1c1/STAGE1C1_COUNT_RECONNAISSANCE_v001.md",
        },
        "event_records_downloaded": 0,
        "query_endpoint_called": False,
        "target_catalogue_modified": False,
    }
    summary_path = OUTPUT_DIR / "reconnaissance_summary_v001.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = f"""# LAIC-GUARD Stage 1C.1 — Count-only supporting-catalogue reconnaissance

- Run ID: `{run_id}`
- Acquisition cutoff (UTC): `{iso_utc(cutoff)}`
- Status: **{summary['status']}**
- Count requests: **{len(rows)}** ({len(base_plan)} base; {len(rows)-len(base_plan)} subdivision)
- Successful responses: **{len(rows)-len(incomplete)}**
- Failed requests: **{len(incomplete)}**
- Safe future-query ceiling: **{SAFE_QUERY_CEILING} events**
- Supporting event records downloaded: **0**

## Scope

Counts use the USGS ComCat preferred numerical magnitude field with `minmagnitude` values 4.0, 4.5 and 5.0. They are **not confirmed Mw-only counts**. Event type is `earthquake`. The intervals begin on 1980-01-01 UTC to support the approved 20-year pre-context sensitivity design and end at the recorded acquisition cutoff.

## Geographic strata

The regional strata are coarse operational bounding boxes for reconnaissance, not tectonic-region polygons. Some overlap; do not sum regional counts to reproduce the global count. See the CSV for exact bounds and every request URL.

## Query-limit handling

Base counts above {SAFE_QUERY_CEILING} were subdivided using calendar years, then months, then days. Any daily interval remaining above the ceiling is unresolved for future event retrieval and requires a finer or additional partitioning plan before data acquisition.

## Decision boundary

This run calls only `/count` and `/version`. It does not call `/query`, download event records, modify the frozen 1,186-row target catalogue, or assign sequence labels. A count is reconnaissance evidence, not a catalogue-completeness determination or an Mw threshold count.

## Outputs

- `reconnaissance_count_results_v001.csv`
- `reconnaissance_request_log_v001.jsonl`
- `reconnaissance_summary_v001.json`
"""
    report_path = OUTPUT_DIR / "STAGE1C1_COUNT_RECONNAISSANCE_v001.md"
    report_path.write_text(md, encoding="utf-8")

    print("\nSTAGE 1C.1 COUNT-ONLY RECONNAISSANCE FINISHED")
    print(f"Base count requests                         : {len(base_plan)}")
    print(f"Total count requests with subdivisions      : {len(rows)}")
    print(f"Successful responses                        : {len(rows) - len(incomplete)}")
    print(f"Failed requests                              : {len(incomplete)}")
    print(f"Counts above safe query ceiling              : {len(over_limit)}")
    print("Event records downloaded                     : 0")
    print("/query endpoint called                       : NO")
    print("Target catalogue modified                    : NO")
    print(f"Acquisition cutoff UTC                       : {iso_utc(cutoff)}")
    print(f"Outputs                                      : {OUTPUT_DIR}")
    if incomplete:
        print("WARNING: one or more count requests failed; do not interpret missing counts as zero.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)
