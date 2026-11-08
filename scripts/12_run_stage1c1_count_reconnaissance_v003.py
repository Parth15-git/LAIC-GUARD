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
COUNT_AREA_TIME_BUDGET = 90_000_000  # conservative below USGS documented 100,000,000 guidance
GLOBAL_FRAGMENT_YEARS = 3  # keeps whole-world time x area well below the guidance
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
    "region_label", "logical_cell_id", "logical_period_id", "area_square_degrees",
    "time_area_product_days_sqdeg", "area_time_partition_index", "area_time_partition_count",
    "minlongitude", "maxlongitude", "minlatitude", "maxlatitude",
    "magnitude_threshold", "magnitude_threshold_semantics", "eventtype",
    "starttime_utc", "endtime_utc", "count", "http_status", "response_state",
    "safe_for_future_query", "subdivision_required", "subdivision_resolution",
    "direct_child_count", "direct_child_count_sum", "count_reconciliation_status",
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


def area_square_degrees(region: dict[str, Any]) -> float:
    """Return the rectangular API search area in square degrees; global = 360 x 180."""
    bounds = region["bounds"]
    if bounds is None:
        return 360.0 * 180.0
    minlon, maxlon, minlat, maxlat = bounds
    return (maxlon - minlon) * (maxlat - minlat)


def time_area_product(region: dict[str, Any], start: datetime, end: datetime) -> float:
    days = (end - start).total_seconds() / 86400.0
    return days * area_square_degrees(region)


def split_for_count_area_time(region: dict[str, Any], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Pre-split logical count cells so every /count request stays under the conservative area-time budget."""
    if time_area_product(region, start, end) <= COUNT_AREA_TIME_BUDGET:
        return [(start, end)]
    parts: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        # Three-calendar-year chunks are comfortably below 90M even globally
        # (maximum about 71.1M square-degree-days, including leap days).
        boundary = datetime(cursor.year + GLOBAL_FRAGMENT_YEARS, 1, 1, tzinfo=timezone.utc)
        nxt = min(boundary, end)
        if nxt <= cursor or time_area_product(region, cursor, nxt) > COUNT_AREA_TIME_BUDGET:
            # Defensive fallback for a non-year-aligned interval or changed bounds.
            max_days = COUNT_AREA_TIME_BUDGET / area_square_degrees(region)
            nxt = min(end, cursor + timedelta(days=max(1, int(max_days * 0.95))))
        if nxt <= cursor or time_area_product(region, cursor, nxt) > COUNT_AREA_TIME_BUDGET:
            raise ValueError("Unable to partition count request below the service area-time budget.")
        parts.append((cursor, nxt))
        cursor = nxt
    return parts


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


def reconcile_parent_child_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Add direct-child sums/statuses and summarize exact partition reconciliation."""
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        parent_id = row.get("parent_request_id")
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(row)

    for row in rows:
        children = children_by_parent.get(row["request_id"], [])
        row["direct_child_count"] = len(children)
        row["direct_child_count_sum"] = ""
        if row.get("count") == "":
            row["count_reconciliation_status"] = "parent_or_leaf_count_failed"
        elif children:
            if any(child.get("count") == "" for child in children):
                row["count_reconciliation_status"] = "child_count_failed_incomplete"
            else:
                child_sum = sum(int(child["count"]) for child in children)
                row["direct_child_count_sum"] = child_sum
                row["count_reconciliation_status"] = (
                    "sum_matches_parent" if child_sum == int(row["count"]) else "sum_mismatch"
                )
        elif row.get("subdivision_resolution") == "daily_floor_exceeded_unresolved_for_future_query":
            row["count_reconciliation_status"] = "daily_leaf_above_safe_ceiling_unresolved"
        elif row.get("subdivision_required"):
            row["count_reconciliation_status"] = "above_ceiling_without_child_partition"
        else:
            row["count_reconciliation_status"] = "leaf_not_subdivided"

    parent_rows = [r for r in rows if children_by_parent.get(r["request_id"])]
    mismatch_rows = [r for r in parent_rows if r["count_reconciliation_status"] == "sum_mismatch"]
    incomplete_parent_rows = [r for r in parent_rows if r["count_reconciliation_status"] == "child_count_failed_incomplete"]
    leaf_rows = [r for r in rows if not children_by_parent.get(r["request_id"])]
    leaf_over_ceiling = [
        r for r in leaf_rows
        if r.get("count") != "" and int(r["count"]) > SAFE_QUERY_CEILING
    ]
    leaf_failed = [r for r in leaf_rows if r.get("count") == ""]
    return {
        "subdivided_parent_count": len(parent_rows),
        "parent_child_partitions_checked": len(parent_rows) - len(incomplete_parent_rows),
        "partition_sum_matches": sum(r["count_reconciliation_status"] == "sum_matches_parent" for r in parent_rows),
        "partition_sum_mismatches": len(mismatch_rows),
        "partition_reconciliations_incomplete": len(incomplete_parent_rows),
        "leaf_partition_count": len(leaf_rows),
        "leaf_partitions_over_safe_query_ceiling": len(leaf_over_ceiling),
        "leaf_partitions_with_failed_counts": len(leaf_failed),
        "all_leaf_partitions_safe_for_future_query": not leaf_over_ceiling and not leaf_failed,
        "mismatch_request_ids": [r["request_id"] for r in mismatch_rows],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Count-only USGS ComCat reconnaissance; no event records downloaded.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned base count grid without network requests.")
    parser.add_argument("--pause", type=float, default=REQUEST_INTERVAL_SECONDS, help="Minimum seconds between requests (default 0.5).")
    args = parser.parse_args()
    if args.pause < 0.25:
        parser.error("--pause must be at least 0.25 seconds for conservative request pacing.")

    cutoff_now = utc_now()
    cutoff = cutoff_now.replace(microsecond=(cutoff_now.microsecond // 1000) * 1000)
    run_id = cutoff.strftime("stage1c1_count_v003_%Y%m%dT%H%M%SZ")
    periods = base_periods(cutoff)
    base_plan = [(region, threshold, period) for region in REGIONS for threshold in THRESHOLDS for period in periods]
    execution_plan: list[dict[str, Any]] = []
    for cell_index, (region, threshold, period) in enumerate(base_plan, start=1):
        fragments = split_for_count_area_time(region, period["start"], period["end"])
        logical_cell_id = f"C{cell_index:04d}"
        for fragment_index, (fragment_start, fragment_end) in enumerate(fragments, start=1):
            execution_plan.append({
                "region": region, "threshold": threshold, "period": period,
                "logical_cell_id": logical_cell_id,
                "fragment_start": fragment_start, "fragment_end": fragment_end,
                "fragment_index": fragment_index, "fragment_count": len(fragments),
            })
    max_area_time = max(
        time_area_product(x["region"], x["fragment_start"], x["fragment_end"])
        for x in execution_plan
    )
    target_rows, target_hash = load_target_catalogue()

    if args.dry_run:
        print("LAIC-GUARD STAGE 1C.1 — DRY RUN v003 (NO NETWORK REQUESTS)")
        print(f"Target catalogue: {RAW_TARGET}")
        print(f"Target catalogue rows / SHA-256 verified: {target_rows} / {target_hash}")
        print(f"Count endpoint: {COUNT_URL}")
        print(f"Acquisition cutoff candidate UTC: {iso_utc(cutoff)}")
        print(f"Regions/strata: {len(REGIONS)} (1 global + {len(REGIONS)-1} overlapping exploratory boxes)")
        print(f"Preferred numeric magnitude thresholds: {', '.join(f'{x:.1f}' for x in THRESHOLDS)}")
        print(f"Logical time periods: {len(periods)}")
        print(f"Logical count cells: {len(base_plan)}")
        print(f"Initial /count windows after area-time partitioning: {len(execution_plan)}")
        print(f"Planned service-version metadata requests: 1 (/version)")
        print(f"Maximum planned time x area: {max_area_time:,.0f} square-degree-days")
        print(f"Conservative count-service time x area budget: {COUNT_AREA_TIME_BUDGET:,} square-degree-days")
        print(f"Subdivision ceiling: {SAFE_QUERY_CEILING}; count-based subdivision: year -> month -> day")
        print("Whole-world logical periods are pre-partitioned into <=3-calendar-year windows.")
        print("IMPORTANT: geographic boxes overlap and are not tectonic-region definitions; do not sum them.")
        print("No /query endpoint is called; no event data is downloaded.")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_output_dir = OUTPUT_DIR / "runs" / run_id
    if run_output_dir.exists():
        raise FileExistsError(
            f"Output directory already exists; refusing to overwrite prior run: {run_output_dir}"
        )
    run_output_dir.mkdir(parents=True, exist_ok=False)
    client = Client(pause=args.pause)
    rows: list[dict[str, Any]] = []
    csv_path = run_output_dir / "reconnaissance_count_results_v003.csv"
    request_log_path = run_output_dir / "reconnaissance_request_log_v003.jsonl"
    run_metadata_path = run_output_dir / "run_metadata_v003.json"
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
    run_metadata_path.write_text(json.dumps({
        "project": "LAIC-GUARD",
        "stage": "1C.1",
        "script_version": "v003",
        "run_id": run_id,
        "acquisition_cutoff_utc": iso_utc(cutoff),
        "frozen_target_catalogue": {
            "path": "metadata/event_catalogue_v002.csv",
            "rows": target_rows,
            "sha256": target_hash,
            "modified_by_script": False,
        },
        "service_version": version_payload,
        "thresholds": list(THRESHOLDS),
        "threshold_semantics": "Numerical preferred ComCat magnitude; not confirmed Mw-only counts",
        "regional_strata": REGIONS,
        "logical_count_cell_count": len(base_plan),
        "initial_count_window_count_after_area_time_partitioning": len(execution_plan),
        "count_area_time_budget_square_degree_days": COUNT_AREA_TIME_BUDGET,
        "global_fragment_years": GLOBAL_FRAGMENT_YEARS,
        "safe_query_ceiling": SAFE_QUERY_CEILING,
        "request_interval_seconds": args.pause,
        "started_at_utc": iso_utc(utc_now()),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Stream each result to disk immediately. An interrupted run therefore
    # retains the requests completed so far rather than losing in-memory rows.
    csv_handle = csv_path.open("w", encoding="utf-8-sig", newline="")
    csv_writer = csv.DictWriter(csv_handle, fieldnames=CSV_FIELDS)
    csv_writer.writeheader()
    csv_handle.flush()
    request_log_handle = request_log_path.open("w", encoding="utf-8", newline="\n")

    def do_count(region: dict[str, Any], threshold: float, start: datetime, end: datetime,
                 level: str, parent_id: str | None = None, subdivision_resolution: str = "not_subdivided",
                 logical_cell_id: str = "", logical_period_id: str = "",
                 area_time_partition_index: int = 1, area_time_partition_count: int = 1) -> dict[str, Any]:
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
            "logical_cell_id": logical_cell_id,
            "logical_period_id": logical_period_id,
            "area_square_degrees": area_square_degrees(region),
            "time_area_product_days_sqdeg": round(time_area_product(region, start, end), 3),
            "area_time_partition_index": area_time_partition_index,
            "area_time_partition_count": area_time_partition_count,
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
        csv_writer.writerow(record)
        csv_handle.flush()
        log_record = {
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
        }
        request_log_handle.write(json.dumps(log_record, ensure_ascii=False, sort_keys=True) + "\n")
        request_log_handle.flush()
        if result.count is None:
            errors += 1
            print(f"[{request_id}] ERROR {region['region_id']} M>={threshold:.1f} {iso_utc(start)}: {result.error}")
        else:
            print(f"[{request_id}] {result.count:>8} {region['region_id']:<27} M>={threshold:.1f} {level}")
        return record

    # For every base stratum, count first. If above the conservative ceiling,
    # recursively count calendar children down to daily resolution.
    try:
        for planned in execution_plan:
            region = planned["region"]
            threshold = planned["threshold"]
            period = planned["period"]
            start = planned["fragment_start"]
            end = planned["fragment_end"]
            cell_id = planned["logical_cell_id"]
            part_index = planned["fragment_index"]
            part_count = planned["fragment_count"]
            level = "area_time_partition" if part_count > 1 else "base"
            base = do_count(
                region, threshold, start, end, level, None,
                "prepartitioned_for_area_time_budget" if part_count > 1 else "not_subdivided",
                cell_id, period["period_id"], part_index, part_count,
            )
            if base["count"] == "" or int(base["count"]) <= SAFE_QUERY_CEILING:
                continue
            frontier = [(start, end, base["request_id"], 0)]
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
                    child = do_count(
                        region, threshold, cstart, cend, resolution, parent_id, resolution,
                        cell_id, period["period_id"], part_index, part_count,
                    )
                    if child["count"] != "" and int(child["count"]) > SAFE_QUERY_CEILING:
                        frontier.append((cstart, cend, child["request_id"], depth + 1))
    finally:
        csv_handle.close()
        request_log_handle.close()

    # Reconcile every subdivided parent against the exact sum of its direct
    # calendar children. Discrepancies remain explicit; they are never repaired
    # by silently changing a count.
    reconciliation = reconcile_parent_child_counts(rows)

    # Aggregate leaf counts back to the 150 logical region/threshold/period cells.
    child_parent_ids = {r["parent_request_id"] for r in rows if r.get("parent_request_id")}
    logical_cell_summaries: list[dict[str, Any]] = []
    for region, threshold, period in base_plan:
        cell_index = base_plan.index((region, threshold, period)) + 1
        cell_id = f"C{cell_index:04d}"
        cell_rows = [r for r in rows if r["logical_cell_id"] == cell_id]
        leaves = [r for r in cell_rows if r["request_id"] not in child_parent_ids]
        failed_leaves = [r for r in leaves if r["count"] == ""]
        leaf_counts = [int(r["count"]) for r in leaves if r["count"] != ""]
        over_ceiling_leaves = [r for r in leaves if r["count"] != "" and int(r["count"]) > SAFE_QUERY_CEILING]
        complete = not failed_leaves and bool(leaves)
        logical_cell_summaries.append({
            "run_id": run_id,
            "logical_cell_id": cell_id,
            "region_id": region["region_id"],
            "region_label": region["label"],
            "period_id": period["period_id"],
            "starttime_utc": iso_utc(period["start"]),
            "endtime_utc": iso_utc(period["end"] - timedelta(milliseconds=1)),
            "magnitude_threshold": threshold,
            "threshold_semantics": "ComCat preferred numerical magnitude; not confirmed Mw-only",
            "area_time_partition_count": max((r["area_time_partition_count"] for r in cell_rows), default=0),
            "leaf_request_count": len(leaves),
            "leaf_count_sum": sum(leaf_counts) if complete else "",
            "logical_cell_status": "complete_sum_of_disjoint_leaf_counts" if complete else "incomplete_leaf_count_requests",
            "leaf_partitions_over_safe_query_ceiling": len(over_ceiling_leaves),
            "safe_for_future_event_query_partitioning": complete and not over_ceiling_leaves,
            "parent_count_requested": False if any(r["area_time_partition_count"] > 1 for r in cell_rows) else True,
            "parent_count_note": "No oversized global parent count requested; sum is derived from disjoint time partitions." if any(r["area_time_partition_count"] > 1 for r in cell_rows) else "Logical cell has a direct base count or recursively subdivided count.",
        })

    logical_summary_path = run_output_dir / "reconnaissance_logical_cell_summary_v003.csv"
    with logical_summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = list(logical_cell_summaries[0].keys())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(logical_cell_summaries)

    # Finalize the count CSV with the direct-child reconciliation fields. The
    # incrementally streamed request log and initial count rows remain on disk
    # if the process is interrupted before this finalization point.
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    counts = [int(r["count"]) for r in rows if r["count"] != ""]
    over_limit = [r for r in rows if r["count"] != "" and int(r["count"]) > SAFE_QUERY_CEILING]
    incomplete = [r for r in rows if r["count"] == ""]
    summary = {
        "project": "LAIC-GUARD",
        "stage": "1C.1",
        "script_version": "v003",
        "run_id": run_id,
        "status": (
            "incomplete_request_errors" if incomplete or any(r["logical_cell_status"] != "complete_sum_of_disjoint_leaf_counts" for r in logical_cell_summaries) else
            "partition_count_mismatch" if reconciliation["partition_sum_mismatches"] else
            "complete_with_unresolved_daily_partitions" if not reconciliation["all_leaf_partitions_safe_for_future_query"] else
            "complete"
        ),
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
        "logical_count_cell_count": len(base_plan),
        "initial_count_window_count_after_area_time_partitioning": len(execution_plan),
        "total_count_requests_including_count_based_subdivisions": len(rows),
        "count_area_time_budget_square_degree_days": COUNT_AREA_TIME_BUDGET,
        "global_fragment_years": GLOBAL_FRAGMENT_YEARS,
        "maximum_initial_window_time_area_product_days_sqdeg": round(max_area_time, 3),
        "logical_cells_complete": sum(r["logical_cell_status"] == "complete_sum_of_disjoint_leaf_counts" for r in logical_cell_summaries),
        "logical_cells_incomplete": sum(r["logical_cell_status"] != "complete_sum_of_disjoint_leaf_counts" for r in logical_cell_summaries),
        "successful_count_responses": len(rows) - len(incomplete),
        "failed_count_requests": len(incomplete),
        "http_204_zero_count_responses": sum(r["response_state"] == "no_data_204_zero" for r in rows),
        "all_request_rows_over_safe_query_ceiling_including_parent_totals": len(over_limit),
        "safe_query_ceiling": SAFE_QUERY_CEILING,
        "partition_reconciliation": reconciliation,
        "counts_minimum": min(counts) if counts else None,
        "counts_maximum": max(counts) if counts else None,
        "outputs": {
            "count_results_csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
            "request_response_log_jsonl": str(request_log_path.relative_to(ROOT)).replace("\\", "/"),
            "run_metadata_json": str(run_metadata_path.relative_to(ROOT)).replace("\\", "/"),
            "summary_json": str((run_output_dir / "reconnaissance_summary_v003.json").relative_to(ROOT)).replace("\\", "/"),
            "report_markdown": str((run_output_dir / "STAGE1C1_COUNT_RECONNAISSANCE_v003.md").relative_to(ROOT)).replace("\\", "/"),
            "logical_cell_summary_csv": str(logical_summary_path.relative_to(ROOT)).replace("\\", "/"),
        },
        "event_records_downloaded": 0,
        "query_endpoint_called": False,
        "target_catalogue_modified": False,
    }
    summary_path = run_output_dir / "reconnaissance_summary_v003.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = f"""# LAIC-GUARD Stage 1C.1 — Count-only supporting-catalogue reconnaissance v003

- Run ID: `{run_id}`
- Acquisition cutoff (UTC): `{iso_utc(cutoff)}`
- Status: **{summary['status']}**
- Logical region/threshold/period cells: **{len(base_plan)}**
- Initial count windows after area-time partitioning: **{len(execution_plan)}**
- Total count requests including count-based subdivision: **{len(rows)}**
- Logical cells with complete leaf counts: **{summary["logical_cells_complete"]} / {len(base_plan)}**
- Successful responses: **{len(rows)-len(incomplete)}**
- Failed requests: **{len(incomplete)}**
- Parent-child count sums matching: **{reconciliation['partition_sum_matches']}**
- Parent-child count mismatches: **{reconciliation['partition_sum_mismatches']}**
- Leaf partitions over safe-query ceiling: **{reconciliation['leaf_partitions_over_safe_query_ceiling']}**
- Safe future-query ceiling: **{SAFE_QUERY_CEILING} events**
- Supporting event records downloaded: **0**

## Scope

Counts use the USGS ComCat preferred numerical magnitude field with `minmagnitude` values 4.0, 4.5 and 5.0. They are **not confirmed Mw-only counts**. Event type is `earthquake`. The intervals begin on 1980-01-01 UTC to support the approved 20-year pre-context sensitivity design and end at the recorded acquisition cutoff.

## Geographic strata

The regional strata are coarse operational bounding boxes for reconnaissance, not tectonic-region polygons. Some overlap; do not sum regional counts to reproduce the global count. See the CSV for exact bounds and every request URL.

## Query-limit handling

Base counts above {SAFE_QUERY_CEILING} were subdivided using calendar years, then months, then days. Any daily interval remaining above the ceiling is unresolved for future event retrieval and requires a finer or additional partitioning plan before data acquisition. Every subdivided parent count is reconciled against the sum of its direct children; mismatches are retained and flagged, never silently corrected.

## Count partition reconciliation

For every subdivided parent interval, the reported parent count is compared with the exact sum of its direct child interval counts. The request timestamps are preserved because ComCat is a maintained catalogue and counts can change while the reconnaissance is running. A mismatch is a flagged discrepancy, not something to correct silently. Failed child requests make that partition reconciliation incomplete.

## Decision boundary

This run calls only `/count` and `/version`. It does not call `/query`, download event records, modify the frozen 1,186-row target catalogue, or assign sequence labels. A count is reconnaissance evidence, not a catalogue-completeness determination or an Mw threshold count.

## Outputs

- `reconnaissance_count_results_v003.csv`
- `reconnaissance_logical_cell_summary_v003.csv`
- `reconnaissance_request_log_v003.jsonl`
- `run_metadata_v003.json`
- `reconnaissance_summary_v003.json`
"""
    report_path = run_output_dir / "STAGE1C1_COUNT_RECONNAISSANCE_v003.md"
    report_path.write_text(md, encoding="utf-8")

    print("\nSTAGE 1C.1 COUNT-ONLY RECONNAISSANCE FINISHED")
    print(f"Logical region/threshold/period cells        : {len(base_plan)}")
    print(f"Initial count windows after area-time split  : {len(execution_plan)}")
    print(f"Total count requests with count subdivisions : {len(rows)}")
    print(f"Complete logical cells                       : {summary['logical_cells_complete']} / {len(base_plan)}")
    print(f"Successful responses                        : {len(rows) - len(incomplete)}")
    print(f"Failed requests                              : {len(incomplete)}")
    print(f"Count partitions reconciled                  : {reconciliation['partition_sum_matches']}")
    print(f"Parent-child count mismatches                : {reconciliation['partition_sum_mismatches']}")
    print(f"Leaf partitions above safe ceiling           : {reconciliation['leaf_partitions_over_safe_query_ceiling']}")
    print(f"All leaf partitions safe for future queries  : {reconciliation['all_leaf_partitions_safe_for_future_query']}")
    print("Event records downloaded                     : 0")
    print("/query endpoint called                       : NO")
    print("Target catalogue modified                    : NO")
    print(f"Acquisition cutoff UTC                       : {iso_utc(cutoff)}")
    print(f"Outputs                                      : {run_output_dir}")
    if incomplete or reconciliation["partition_sum_mismatches"]:
        if incomplete:
            print("WARNING: one or more count requests failed; do not interpret missing counts as zero.")
        if reconciliation["partition_sum_mismatches"]:
            print("WARNING: one or more child-count sums do not match parent counts; preserve and investigate.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)
