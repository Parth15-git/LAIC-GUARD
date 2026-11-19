from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_VERSION = "stage6a1_strict_tcwv_v001"
ROOT = Path(__file__).resolve().parents[1]

FEATURE_FILE = (
    ROOT / "reports/stage6a/audit_repaired_v004_regionfix_cachefix_distancefix"
    / "analysis/stage6a_v004_event_features.csv"
)
REGISTRY_FILE = ROOT / "metadata/station_registry.csv"

PROTOCOL_FILE = ROOT / "protocols/stage6a1_strict_tcwv_v001.md"
ADDENDUM_FILE = ROOT / "protocols/stage6a1_strict_tcwv_v001_addendum001.md"

CACHE_DIR = (
    ROOT / "data/external/meteorology/"
    "era5_explicit_era5_station_elevation_v001"
)
MANIFEST_FILE = CACHE_DIR / "manifest.json"

PROTOCOL_SHA256 = (
    "6088588F5CBD1DD29CFBA2B1AF04A1261B25AA91E48FECD08E793A8F8F272538"
)
ADDENDUM_SHA256 = (
    "3BD5E4A4EACD157E90C9C4E5FDE3B8B3F3019F51E17CD2E4AB7281AE863C2368"
)

API_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARIABLES = [
    "surface_pressure",
    "temperature_2m",
    "dew_point_2m",
    "total_column_integrated_water_vapour",
]

EXPECTED_UNITS = {
    "surface_pressure": "hPa",
    "temperature_2m": "\u00b0C",
    "dew_point_2m": "\u00b0C",
    "total_column_integrated_water_vapour": "kg/m\u00b2",
}

PILOT_EVENT_IDS = [
    "usp000ahfr",  # AREQ, 2001
    "us6000nith",  # G088, 2024
    "us7000m9g4",  # SHUL, 2024
    "us7000lsze",  # KMTR, 2024
    "us7000n05d",  # CJNT, 2024
]

EXPECTED_FULL_EVENT_COUNT = 111
EXPECTED_HOURS = 1224
MAX_ATTEMPTS = 4


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_frozen_documents() -> None:
    for path, expected in (
        (PROTOCOL_FILE, PROTOCOL_SHA256),
        (ADDENDUM_FILE, ADDENDUM_SHA256),
    ):
        if not path.is_file():
            raise RuntimeError(f"Required frozen document is missing: {path}")

        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(
                f"FROZEN DOCUMENT HASH MISMATCH: {path}\n"
                f"Expected: {expected}\nActual:   {actual}\n"
                "Stop. Do not retrieve data until the protocol is reconciled."
            )


def load_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_inputs() -> tuple[list[dict], dict[str, dict]]:
    event_rows = load_csv(FEATURE_FILE)
    station_rows = load_csv(REGISTRY_FILE)

    required_event = {"event_id", "station_id", "origin_time_utc"}
    required_station = {
        "station_id", "latitude_deg", "longitude_deg", "elevation_m"
    }

    if not event_rows:
        raise RuntimeError("Event-feature input is empty.")

    if not required_event.issubset(event_rows[0]):
        raise RuntimeError(
            f"Event-feature CSV is missing columns: "
            f"{sorted(required_event - set(event_rows[0]))}"
        )

    if not station_rows or not required_station.issubset(station_rows[0]):
        raise RuntimeError(
            "Station registry is missing one or more required columns."
        )

    event_ids = [r["event_id"].strip() for r in event_rows]
    if len(event_ids) != len(set(event_ids)):
        raise RuntimeError("Duplicate event IDs in event-feature input.")

    stations: dict[str, dict] = {}
    for row in station_rows:
        sid = row.get("station_id", "").strip().upper()
        if sid:
            stations[sid] = row

    return event_rows, stations


def parse_origin(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Event origin lacks a timezone: {value}")
    return dt.astimezone(timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(a))


def make_request_parameters(
    lat: float,
    lon: float,
    elevation_m: float,
    start_date: str,
    end_date: str,
) -> dict[str, str]:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "elevation": f"{elevation_m:.2f}",
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
        "models": "era5",
        "cell_selection": "land",
    }


def expected_timestamps(start_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    return [
        (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
        for i in range(EXPECTED_HOURS)
    ]


def is_valid_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_response(
    payload: dict,
    params: dict[str, str],
    station_lat: float,
    station_lon: float,
    station_elevation: float,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("API response is not a JSON object.")

    if payload.get("error"):
        raise ValueError(
            f"API returned an error: {payload.get('reason', payload)}"
        )

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("API response has no hourly data object.")

    units = payload.get("hourly_units", {})
    for variable, expected_unit in EXPECTED_UNITS.items():
        actual_unit = units.get(variable)
        if actual_unit != expected_unit:
            raise ValueError(
                f"Wrong or missing unit for {variable}: "
                f"{actual_unit!r}; expected {expected_unit!r}"
            )

    times = hourly.get("time")
    if not isinstance(times, list):
        raise ValueError("Hourly time array is missing.")

    expected = expected_timestamps(params["start_date"])
    if len(times) != EXPECTED_HOURS:
        raise ValueError(
            f"Expected {EXPECTED_HOURS} timestamps, received {len(times)}."
        )

    if times != expected:
        first_mismatch = next(
            (
                i for i, (actual, wanted) in enumerate(zip(times, expected))
                if actual != wanted
            ),
            None,
        )
        raise ValueError(
            "Timestamp sequence does not exactly match the requested "
            f"continuous UTC sequence. First mismatch: {first_mismatch}"
        )

    utc_offset = payload.get("utc_offset_seconds")
    if utc_offset != 0:
        raise ValueError(
            f"Expected zero UTC offset; received {utc_offset!r}."
        )

    quality = {}
    for variable in HOURLY_VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != EXPECTED_HOURS:
            raise ValueError(
                f"{variable} array is missing or has the wrong length."
            )

        null_count = 0
        invalid_count = 0
        valid_count = 0

        for value in values:
            if value is None:
                null_count += 1
            elif is_valid_number(value):
                valid_count += 1
            else:
                invalid_count += 1

        if invalid_count:
            raise ValueError(
                f"{variable} contains {invalid_count} invalid/non-finite values."
            )

        quality[variable] = {
            "valid_count": valid_count,
            "null_count": null_count,
            "invalid_count": invalid_count,
            "unit": units[variable],
        }

    returned_lat = payload.get("latitude")
    returned_lon = payload.get("longitude")

    if not is_valid_number(returned_lat) or not is_valid_number(returned_lon):
        raise ValueError("Returned grid-cell coordinates are missing or invalid.")

    grid_offset = haversine_km(
        station_lat, station_lon, float(returned_lat), float(returned_lon)
    )

    returned_elevation = payload.get("elevation")
    if returned_elevation is not None and not is_valid_number(returned_elevation):
        raise ValueError("Returned elevation is not numeric.")

    response_timezone = payload.get("timezone", "NOT_RETURNED")
    model_metadata = payload.get(
        "models", payload.get("model", "NOT_RETURNED")
    )

    return {
        "timestamp_count": len(times),
        "first_timestamp_utc": times[0],
        "last_timestamp_utc": times[-1],
        "utc_offset_seconds": utc_offset,
        "response_timezone": response_timezone,
        "hourly_units": units,
        "variable_quality": quality,
        "returned_grid_latitude": float(returned_lat),
        "returned_grid_longitude": float(returned_lon),
        "station_to_grid_distance_km": round(grid_offset, 6),
        "requested_station_elevation_m": station_elevation,
        "response_elevation_m": returned_elevation,
        "response_elevation_note": (
            "The request explicitly supplied station elevation. "
            "Do not treat returned elevation as an independent DEM measurement."
        ),
        "response_generationtime_ms": payload.get("generationtime_ms"),
        "response_model_metadata": model_metadata,
        "response_model_metadata_status": (
            "RETURNED" if model_metadata != "NOT_RETURNED" else "NOT_RETURNED"
        ),
    }


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MANIFEST_FILE.with_name("manifest.json.tmp")

    temp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, MANIFEST_FILE)


def load_or_create_manifest() -> dict:
    if MANIFEST_FILE.exists():
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        if manifest.get("protocol_sha256") != PROTOCOL_SHA256:
            raise RuntimeError("Existing manifest has a different protocol hash.")
        if manifest.get("addendum_sha256") != ADDENDUM_SHA256:
            raise RuntimeError("Existing manifest has a different addendum hash.")
        if manifest.get("script_version") != SCRIPT_VERSION:
            raise RuntimeError("Existing manifest belongs to a different script version.")
        manifest.setdefault("records", {})
        manifest.setdefault("runs", [])
        return manifest

    return {
        "manifest_schema": "LAIC_GUARD_ERA5_CACHE_MANIFEST_v001",
        "script_version": SCRIPT_VERSION,
        "created_at_utc": utc_now(),
        "protocol_path": str(PROTOCOL_FILE.relative_to(ROOT)),
        "protocol_sha256": PROTOCOL_SHA256,
        "addendum_path": str(ADDENDUM_FILE.relative_to(ROOT)),
        "addendum_sha256": ADDENDUM_SHA256,
        "api_endpoint": API_ENDPOINT,
        "cache_policy": (
            "New explicit ERA5 cache only. No old-cache fallback. "
            "Raw response bytes preserved and SHA256 recorded."
        ),
        "records": {},
        "runs": [],
    }


def fetch_response(params: dict[str, str]) -> tuple[bytes, int, str]:
    url = API_ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LAIC-GUARD-Stage6A1-Strict-TCWV/1.0"
        },
    )

    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                status = response.getcode()
                content_type = response.headers.get(
                    "Content-Type", "NOT_RETURNED"
                )

            if status != 200:
                raise RuntimeError(f"Unexpected HTTP status: {status}")

            return raw, status, content_type

        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt == MAX_ATTEMPTS:
                raise

            retry_after = exc.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 1.5 * attempt
            except ValueError:
                delay = 1.5 * attempt

            print(
                f"HTTP {exc.code}; retry {attempt}/{MAX_ATTEMPTS} "
                f"after {delay:.1f}s"
            )
            time.sleep(min(delay, 30.0))

        except Exception as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                raise
            delay = 1.5 * attempt
            print(
                f"Request error; retry {attempt}/{MAX_ATTEMPTS} "
                f"after {delay:.1f}s: {exc}"
            )
            time.sleep(delay)

    raise RuntimeError(f"Request failed: {last_error}")


def atomic_save_raw(path: Path, raw: bytes) -> None:
    if path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing cache file: {path}"
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".part",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())

        if path.exists():
            raise FileExistsError(
                f"Cache appeared during download; refusing overwrite: {path}"
            )

        os.replace(temp_path, path)

    finally:
        if temp_path.exists():
            temp_path.unlink()


def select_events(event_rows: list[dict], full_mode: bool) -> list[dict]:
    by_id = {r["event_id"].strip(): r for r in event_rows}

    if full_mode:
        if len(event_rows) != EXPECTED_FULL_EVENT_COUNT:
            raise RuntimeError(
                f"Expected exactly {EXPECTED_FULL_EVENT_COUNT} event rows; "
                f"found {len(event_rows)}."
            )
        return event_rows

    missing = [eid for eid in PILOT_EVENT_IDS if eid not in by_id]
    if missing:
        raise RuntimeError(f"Pilot event IDs not found: {missing}")

    return [by_id[eid] for eid in PILOT_EVENT_IDS]


def process_event(
    event: dict,
    stations: dict[str, dict],
    manifest: dict,
    run: dict,
) -> str:
    eid = event["event_id"].strip()
    sid = event["station_id"].strip().upper()
    record_key = f"{eid}|{sid}"
    cache_path = CACHE_DIR / f"{eid}_{sid}_era5.json"

    if sid not in stations:
        raise RuntimeError(f"Station {sid} not found in station registry.")

    station = stations[sid]

    lat = float(station["latitude_deg"])
    lon = float(station["longitude_deg"])
    elevation = float(station["elevation_m"])

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"Invalid coordinates for station {sid}.")
    if not math.isfinite(elevation):
        raise ValueError(f"Invalid station elevation for {sid}.")

    origin = parse_origin(event["origin_time_utc"])
    start_date = (origin - timedelta(days=45)).date().isoformat()
    end_date = (origin + timedelta(days=5)).date().isoformat()

    params = make_request_parameters(
        lat, lon, elevation, start_date, end_date
    )

    # Never silently replace or overwrite an existing file.
    if cache_path.exists():
        previous = manifest["records"].get(record_key)
        if not previous:
            raise RuntimeError(
                f"Existing cache has no matching manifest record: {cache_path}"
            )

        actual_sha = sha256_file(cache_path)
        if actual_sha != previous.get("raw_response_sha256"):
            raise RuntimeError(
                f"Existing cache SHA256 mismatch: {cache_path}"
            )

        raw = cache_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        quality = validate_response(payload, params, lat, lon, elevation)

        run["skipped_existing"].append(eid)
        print(f"SKIP verified existing cache: {eid} / {sid}")
        return "SKIPPED"

    print(f"\nRequesting {eid} / {sid}")
    print(f"  Dates: {start_date} to {end_date}")
    print(f"  Station coordinates: {lat:.6f}, {lon:.6f}")
    print(f"  Station elevation: {elevation:.2f} m")
    print("  Model: ERA5 | Cell selection: land | Timezone: UTC")

    raw, http_status, content_type = fetch_response(params)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Response is not valid UTF-8 JSON: {exc}") from exc

    quality = validate_response(payload, params, lat, lon, elevation)
    response_sha = sha256_bytes(raw)

    atomic_save_raw(cache_path, raw)

    record = {
        "event_id": eid,
        "station_id": sid,
        "origin_time_utc": event["origin_time_utc"],
        "request_timestamp_utc": utc_now(),
        "api_endpoint": API_ENDPOINT,
        "request_parameters": params,
        "http_status": http_status,
        "content_type": content_type,
        "raw_response_file": str(cache_path.relative_to(ROOT)),
        "raw_response_bytes": len(raw),
        "raw_response_sha256": response_sha,
        "quality": quality,
        "cache_status": "VALIDATED_RAW_RESPONSE",
        "run_number": run["run_number"],
    }

    manifest["records"][record_key] = record
    run["successful_event_ids"].append(eid)
    save_manifest(manifest)

    print(f"  Validated timestamps: {quality['timestamp_count']}")
    print(
        "  TCWV valid/null:",
        quality["variable_quality"][
            "total_column_integrated_water_vapour"
        ]["valid_count"],
        "/",
        quality["variable_quality"][
            "total_column_integrated_water_vapour"
        ]["null_count"],
    )
    print(
        "  Station-to-grid offset:",
        f"{quality['station_to_grid_distance_km']:.3f} km",
    )
    print("  Response model metadata:", quality["response_model_metadata"])
    print("  SHA256:", response_sha)
    print("  Saved:", cache_path.name)

    return "DOWNLOADED"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LAIC-GUARD Stage 6A.1 explicit ERA5 cache downloader. "
            "Default mode is the five-event pilot."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Select all 111 event-station records; requires explicit confirmation.",
    )
    parser.add_argument(
        "--confirm-full",
        default=None,
        help="Required confirmation phrase for full retrieval: DOWNLOAD_111",
    )
    args = parser.parse_args()

    if args.all and args.confirm_full != "DOWNLOAD_111":
        parser.error(
            "Full retrieval requires --all --confirm-full DOWNLOAD_111"
        )
    if not args.all and args.confirm_full is not None:
        parser.error("--confirm-full is only valid together with --all")

    print("===== LAIC-GUARD STAGE 6A.1 ERA5 DOWNLOADER =====")
    print("Script version:", SCRIPT_VERSION)
    print("Mode:", "FULL 111-EVENT RETRIEVAL" if args.all else "FIVE-EVENT PILOT")
    print("Cache directory:", CACHE_DIR)
    print("No old-cache fallback is permitted.")
    print("")

    verify_frozen_documents()
    print("Frozen protocol SHA256: verified")
    print("Frozen addendum SHA256: verified")

    event_rows, stations = load_inputs()
    selected = select_events(event_rows, args.all)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_or_create_manifest()

    run_number = len(manifest["runs"]) + 1
    run = {
        "run_number": run_number,
        "mode": "FULL" if args.all else "PILOT",
        "started_at_utc": utc_now(),
        "status": "IN_PROGRESS",
        "requested_event_count": len(selected),
        "successful_event_ids": [],
        "skipped_existing": [],
        "failed_events": [],
    }
    manifest["runs"].append(run)
    save_manifest(manifest)

    for index, event in enumerate(selected, 1):
        print(f"\n--- Event {index}/{len(selected)} ---")
        try:
            result = process_event(event, stations, manifest, run)
            print("Result:", result)
        except Exception as exc:
            eid = event.get("event_id", "UNKNOWN")
            error = {
                "event_id": eid,
                "error": repr(exc),
                "timestamp_utc": utc_now(),
            }
            run["failed_events"].append(error)
            print("FAILED:", eid, repr(exc))

        save_manifest(manifest)

        if index < len(selected):
            time.sleep(0.6)

    run["completed_at_utc"] = utc_now()
    run["downloaded_count"] = len(run["successful_event_ids"])
    run["skipped_count"] = len(run["skipped_existing"])
    run["failed_count"] = len(run["failed_events"])
    run["status"] = (
        "COMPLETED"
        if run["failed_count"] == 0
        else "COMPLETED_WITH_ERRORS"
    )
    save_manifest(manifest)

    print("\n===== RUN SUMMARY =====")
    print("Mode:", run["mode"])
    print("Requested:", run["requested_event_count"])
    print("Newly downloaded:", run["downloaded_count"])
    print("Verified existing/skipped:", run["skipped_count"])
    print("Failed:", run["failed_count"])
    print("Run status:", run["status"])
    print("Manifest:", MANIFEST_FILE)
    print("")

    if MANIFEST_FILE.exists():
        print("Manifest SHA256:", sha256_file(MANIFEST_FILE))

    return 0 if run["failed_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
