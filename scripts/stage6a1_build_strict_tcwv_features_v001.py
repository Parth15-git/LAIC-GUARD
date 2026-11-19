from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import zipfile

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]

SCRIPT_VERSION = "stage6a1_build_strict_tcwv_features_v001"
PILOT_VERSION = "pilot_v001"

V004_FILE = (
    ROOT / "reports/stage6a/audit_repaired_v004_regionfix_cachefix_distancefix"
    / "analysis/stage6a_v004_event_features.csv"
)
STAGE4B_FILE = (
    ROOT / "reports/stage4b/full_tier1_benchmark_v001"
    / "analysis/stage4b_paired_tier1_events_v001.csv"
)
STAGE2C_FILE = (
    ROOT / "reports/stage2c/archive_readiness_v001"
    / "analysis/stage2c_verified_benchmark_cohort_v001.csv"
)
REGISTRY_FILE = ROOT / "metadata/station_registry.csv"

DOWNLOADER_FILE = ROOT / "scripts/stage6a1_strict_tcwv_v001.py"
STAGE5C_FILE = ROOT / "scripts/stage5c_zero_overlap_equallag_v002.py"
STAGE5E_FILE = ROOT / "scripts/stage5e_era5_deconfounded_v002.py"

PROTOCOL_FILES = {
    "protocol": ROOT / "protocols/stage6a1_strict_tcwv_v001.md",
    "addendum001": ROOT / "protocols/stage6a1_strict_tcwv_v001_addendum001.md",
    "addendum002": ROOT / "protocols/stage6a1_strict_tcwv_v001_addendum002.md",
}

CACHE_DIR = (
    ROOT / "data/external/meteorology/"
    "era5_explicit_era5_station_elevation_v001"
)
CACHE_MANIFEST = CACHE_DIR / "manifest.json"

GNSS_ZIP_DIR = ROOT / "data/external/gnss/unr_trop_zips_v001"

OUTPUT_DIR = ROOT / "reports/stage6a1/strict_tcwv_v001/pilot_v001"
TEMP_OUTPUT_DIR = OUTPUT_DIR.with_name(OUTPUT_DIR.name + ".tmp")

PILOT_EVENT_IDS = [
    "usp000ahfr",  # AREQ
    "us6000nith",  # G088
    "us7000lsze",  # KMTR
    "us7000m9g4",  # SHUL
    "us7000n05d",  # CJNT physical control
]

EXPECTED_FULL_EVENTS = 111
EXPECTED_STAGE2C_ROWS = 363
EXPECTED_CACHE_HOURS = 1224

EXPECTED_HASHES = {
    "v004": (
        "8D8182CEBE35D10C0492D2B42E2CD337669BAA4DCB7C8A801771B269A3A98334"
    ),
    "v004_script": (
        "4C7DFD199A3C04D82E4850AE487FA5AD1642EE59DF0A51B60948F4B6EE5A68A0"
    ),
    "stage4b": (
        "BA1DD886CD2861F32928A039A9308323395EE151DD8CA6EC70FFF6AFB28C578F"
    ),
    "registry": (
        "5C948A29DDCC8AD602A2BDE0573A45A6AE532C957544052156198F62DC198B50"
    ),
    "downloader": (
        "D59C4444175F6E77AC491E8860B6468118473C512A464EB8AB680446D827695B"
    ),
    "cache_manifest": (
        "776A619820785457A8B2A9DD2918E16866A99E446876BE3264140DEBF8088107"
    ),
    "protocol": (
        "6088588F5CBD1DD29CFBA2B1AF04A1261B25AA91E48FECD08E793A8F8F272538"
    ),
    "addendum001": (
        "3BD5E4A4EACD157E90C9C4E5FDE3B8B3F3019F51E17CD2E4AB7281AE863C2368"
    ),
    "addendum002": (
        "711062902326CE99268A96A81B9627447A4E726D4305E507B955E4C5CC429D3D"
    ),
}

EXPECTED_UNITS = {
    "surface_pressure": "hPa",
    "temperature_2m": "°C",
    "dew_point_2m": "°C",
    "total_column_integrated_water_vapour": "kg/m²",
}

HOURLY_VARIABLES = list(EXPECTED_UNITS)

WINDOWS = {
    "B0": (-1080, -792),
    "W0": (-792, -552),
    "B1": (-552, -264),
    "W1": (-264, -24),
    "GUARD": (-24, 0),
}

UTC = timezone.utc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_csv(path: Path) -> list[dict]:
    require(path.is_file(), f"Required input is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    require(dt.tzinfo is not None, f"Timestamp has no timezone: {value}")
    return dt.astimezone(UTC)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def numeric(value, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid numeric value for {label}: {value!r}")
    require(math.isfinite(result), f"Non-finite number for {label}")
    return result


def median_and_mad(values: list[float]) -> tuple[float, float, float, bool]:
    require(bool(values), "Cannot calculate median/MAD on an empty list.")
    med = float(median(values))
    mad = float(median([abs(x - med) for x in values]))
    raw_scale = 1.4826 * mad
    floor_used = raw_scale < 1e-6
    scale = max(1e-6, raw_scale)
    return med, mad, scale, floor_used


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def calculate_era5_ztd(
    pressure_hpa: float,
    temperature_c: float,
    tcwv_kg_m2: float,
    latitude_deg: float,
    elevation_m: float,
) -> dict:
    require(pressure_hpa > 0, "Surface pressure must be positive.")
    require(temperature_c + 273.15 > 0, "Absolute temperature invalid.")
    require(tcwv_kg_m2 >= 0, "TCWV cannot be negative.")

    phi = math.radians(latitude_deg)
    denominator = (
        1.0
        - 0.00266 * math.cos(2.0 * phi)
        - 0.00028 * (elevation_m / 1000.0)
    )
    require(denominator > 0, "Invalid ZHD denominator.")

    zhd = (2.2768 * pressure_hpa) / denominator

    mean_temperature = 70.2 + 0.72 * (temperature_c + 273.15)
    pi_inverse = 1e-5 * 461.5 * (
        3.739e5 / mean_temperature + 22.1
    )
    zwd = pi_inverse * tcwv_kg_m2
    ztd = zhd + zwd

    require(
        all(math.isfinite(x) for x in (zhd, zwd, ztd, pi_inverse)),
        "Non-finite ZTD calculation.",
    )
    return {
        "zhd_mm": zhd,
        "zwd_mm": zwd,
        "ztd_mm": ztd,
        "mean_temperature_k": mean_temperature,
        "pi_inverse_mm_per_kg_m2": pi_inverse,
    }


def run_unit_tests() -> list[dict]:
    tests = []

    result = calculate_era5_ztd(
        pressure_hpa=950.0,
        temperature_c=20.0,
        tcwv_kg_m2=25.0,
        latitude_deg=30.0,
        elevation_m=500.0,
    )

    tests.append({
        "test": "ZHD_positive_and_finite",
        "status": (
            "PASS" if 1500 < result["zhd_mm"] < 2500 else "FAIL"
        ),
        "observed": result["zhd_mm"],
        "expected_rule": "finite positive hydrostatic delay",
    })
    tests.append({
        "test": "Pi_inverse_physical_range",
        "status": (
            "PASS"
            if 5.0 < result["pi_inverse_mm_per_kg_m2"] < 8.0
            else "FAIL"
        ),
        "observed": result["pi_inverse_mm_per_kg_m2"],
        "expected_rule": "approximately 6-7 mm per kg/m2",
    })
    tests.append({
        "test": "ZWD_direct_TCWV",
        "status": (
            "PASS"
            if abs(result["zwd_mm"] -
                   result["pi_inverse_mm_per_kg_m2"] * 25.0) < 1e-10
            else "FAIL"
        ),
        "observed": result["zwd_mm"],
        "expected_rule": "Pi_inverse multiplied by direct TCWV",
    })
    tests.append({
        "test": "ZTD_additivity",
        "status": (
            "PASS"
            if abs(result["ztd_mm"] -
                   result["zhd_mm"] - result["zwd_mm"]) < 1e-10
            else "FAIL"
        ),
        "observed": result["ztd_mm"],
        "expected_rule": "ZTD equals ZHD plus ZWD",
    })

    require(
        all(x["status"] == "PASS" for x in tests),
        "One or more independent physical unit tests failed.",
    )
    return tests


def expected_timestamps(start_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    return [
        (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
        for i in range(EXPECTED_CACHE_HOURS)
    ]


def load_and_verify_inputs() -> tuple[dict, dict]:
    paths = {
        "v004": V004_FILE,
        "v004_script": (
            ROOT / "scripts/"
            "stage6a_repaired_benchmark_v004_regionfix_cachefix_distancefix.py"
        ),
        "stage4b": STAGE4B_FILE,
        "stage2c": STAGE2C_FILE,
        "registry": REGISTRY_FILE,
        "downloader": DOWNLOADER_FILE,
        "stage5c_parser": STAGE5C_FILE,
        "stage5e_reference": STAGE5E_FILE,
        "cache_manifest": CACHE_MANIFEST,
    }
    for key, path in paths.items():
        require(path.is_file(), f"Missing {key} input: {path}")

    actual_hashes = {
        key: sha256_file(path) for key, path in paths.items()
    }
    for key, expected in EXPECTED_HASHES.items():
        if key in actual_hashes:
            require(
                actual_hashes[key] == expected,
                f"{key} SHA256 mismatch: {actual_hashes[key]}",
            )

    protocol_hashes = {}
    for key, path in PROTOCOL_FILES.items():
        require(path.is_file(), f"Missing protocol file: {path}")
        actual = sha256_file(path)
        require(
            actual == EXPECTED_HASHES[key],
            f"{key} SHA256 mismatch: {actual}",
        )
        protocol_hashes[key] = actual

    actual_hashes.update({
        f"protocol_{k}": v for k, v in protocol_hashes.items()
    })

    v004 = read_csv(V004_FILE)
    stage4b = read_csv(STAGE4B_FILE)
    stage2c = read_csv(STAGE2C_FILE)
    registry_rows = read_csv(REGISTRY_FILE)

    require(len(v004) == EXPECTED_FULL_EVENTS,
            f"V004 row count expected 111; got {len(v004)}")
    require(len(stage4b) == EXPECTED_FULL_EVENTS,
            f"Stage 4B row count expected 111; got {len(stage4b)}")
    require(len(stage2c) == EXPECTED_STAGE2C_ROWS,
            f"Stage 2C row count expected 363; got {len(stage2c)}")

    v004_by_id = {r["event_id"].strip(): r for r in v004}
    stage4b_by_id = {r["event_id"].strip(): r for r in stage4b}
    stage2c_by_id = {r["event_id"].strip(): r for r in stage2c}

    require(len(v004_by_id) == len(v004), "Duplicate V004 event IDs.")
    require(len(stage4b_by_id) == len(stage4b), "Duplicate Stage 4B IDs.")
    require(len(stage2c_by_id) == len(stage2c), "Duplicate Stage 2C IDs.")
    require(set(v004_by_id) == set(stage4b_by_id),
            "V004 and Stage 4B event populations differ.")

    registry_by_station = defaultdict(list)
    for row in registry_rows:
        sid = row.get("station_id", "").strip().upper()
        if sid:
            registry_by_station[sid].append(row)

    for eid, row in v004_by_id.items():
        require(eid in stage2c_by_id, f"Stage 2C missing {eid}")

        station = row["station_id"].strip().upper()
        origin = parse_utc(row["origin_time_utc"])

        b = stage4b_by_id[eid]
        c = stage2c_by_id[eid]

        require(
            station == b["verified_gnss_station_id"].strip().upper(),
            f"V004/Stage 4B station mismatch for {eid}",
        )
        require(
            station == c["verified_gnss_station_id"].strip().upper(),
            f"V004/Stage 2C station mismatch for {eid}",
        )
        require(
            origin == parse_utc(b["origin_time_utc"]),
            f"V004/Stage 4B origin mismatch for {eid}",
        )
        require(
            origin == parse_utc(c["origin_time_utc"]),
            f"V004/Stage 2C origin mismatch for {eid}",
        )

        matches = registry_by_station.get(station, [])
        require(
            len(matches) == 1,
            f"Expected one registry row for {station}; found {len(matches)}",
        )

        registry = matches[0]
        lat = numeric(registry["latitude_deg"], f"{station} latitude")
        lon = numeric(registry["longitude_deg"], f"{station} longitude")
        elev = numeric(registry["elevation_m"], f"{station} elevation")

        require(-90 <= lat <= 90, f"Invalid latitude for {station}")
        require(-180 <= lon <= 180, f"Invalid longitude for {station}")

        urls = c.get("unr_trop_urls", "").strip()
        require(bool(urls), f"No GNSS URLs for {eid}")

    roles = defaultdict(int)
    for row in v004:
        roles[row["role"].strip()] += 1

    require(roles["PRIMARY_SHALLOW_TARGET"] == 90,
            "V004 primary-target count is not 90.")
    require(
        roles["PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"] == 21,
        "V004 physical-control count is not 21.",
    )

    manifest = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    require(
        manifest.get("protocol_sha256") == EXPECTED_HASHES["protocol"],
        "ERA5 manifest protocol hash mismatch.",
    )
    require(
        manifest.get("addendum_sha256") == EXPECTED_HASHES["addendum001"],
        "ERA5 manifest Addendum 001 hash mismatch.",
    )
    require(
        manifest.get("script_version") == "stage6a1_strict_tcwv_v001",
        "Unexpected ERA5 cache manifest script version.",
    )
    require(isinstance(manifest.get("records"), dict),
            "ERA5 manifest records object is missing.")

    data = {
        "v004": v004_by_id,
        "stage4b": stage4b_by_id,
        "stage2c": stage2c_by_id,
        "registry": registry_by_station,
        "manifest": manifest,
        "registry_rows": len(registry_rows),
    }
    return data, actual_hashes


def validate_era5_cache(
    event: dict,
    station_row: dict,
    manifest: dict,
) -> dict:
    eid = event["event_id"].strip()
    sid = event["station_id"].strip().upper()
    record_key = f"{eid}|{sid}"

    record = manifest["records"].get(record_key)
    require(record is not None, f"Manifest record missing: {record_key}")
    require(record.get("event_id") == eid, f"Manifest event mismatch: {eid}")
    require(
        record.get("station_id", "").upper() == sid,
        f"Manifest station mismatch: {eid}",
    )

    relative = Path(record["raw_response_file"])
    cache_path = (ROOT / relative).resolve()
    try:
        cache_path.relative_to(CACHE_DIR.resolve())
    except ValueError:
        raise RuntimeError(
            f"Manifest cache path escapes pinned cache directory: {cache_path}"
        )

    require(cache_path.is_file(), f"Missing pinned ERA5 cache: {cache_path}")

    raw = cache_path.read_bytes()
    actual_hash = sha256_bytes(raw)
    require(
        actual_hash == record["raw_response_sha256"].upper(),
        f"Cache SHA256 mismatch for {eid}",
    )
    require(
        len(raw) == int(record["raw_response_bytes"]),
        f"Cache byte-count mismatch for {eid}",
    )

    payload = json.loads(raw.decode("utf-8"))
    origin = parse_utc(event["origin_time_utc"])
    lat = numeric(station_row["latitude_deg"], f"{sid} latitude")
    lon = numeric(station_row["longitude_deg"], f"{sid} longitude")
    elev = numeric(station_row["elevation_m"], f"{sid} elevation")

    params = record["request_parameters"]
    start_date = (origin - timedelta(days=45)).date().isoformat()
    end_date = (origin + timedelta(days=5)).date().isoformat()

    require(params.get("start_date") == start_date,
            f"ERA5 request start-date mismatch for {eid}")
    require(params.get("end_date") == end_date,
            f"ERA5 request end-date mismatch for {eid}")
    require(params.get("timezone") == "UTC", f"ERA5 timezone request mismatch: {eid}")
    require(params.get("models") == "era5", f"ERA5 model request mismatch: {eid}")
    require(params.get("cell_selection") == "land",
            f"ERA5 cell-selection mismatch: {eid}")
    require(params.get("latitude") == f"{lat:.4f}",
            f"ERA5 request latitude mismatch: {eid}")
    require(params.get("longitude") == f"{lon:.4f}",
            f"ERA5 request longitude mismatch: {eid}")
    require(params.get("elevation") == f"{elev:.2f}",
            f"ERA5 request elevation mismatch: {eid}")

    hourly = payload.get("hourly")
    require(isinstance(hourly, dict), f"ERA5 hourly object missing: {eid}")

    units = payload.get("hourly_units", {})
    for variable, expected in EXPECTED_UNITS.items():
        require(
            units.get(variable) == expected,
            f"ERA5 unit mismatch for {eid}/{variable}: {units.get(variable)!r}",
        )

    times = hourly.get("time")
    wanted = expected_timestamps(start_date)
    require(isinstance(times, list), f"ERA5 times missing: {eid}")
    require(len(times) == EXPECTED_CACHE_HOURS,
            f"ERA5 timestamp count mismatch: {eid}")
    require(times == wanted, f"ERA5 hourly UTC sequence mismatch: {eid}")
    require(payload.get("utc_offset_seconds") == 0,
            f"ERA5 UTC offset is not zero: {eid}")

    arrays = {}
    quality = {}
    for variable in HOURLY_VARIABLES:
        values = hourly.get(variable)
        require(
            isinstance(values, list) and len(values) == EXPECTED_CACHE_HOURS,
            f"ERA5 array length mismatch: {eid}/{variable}",
        )

        valid = 0
        nulls = 0
        for value in values:
            if value is None:
                nulls += 1
            else:
                require(
                    is_number(value),
                    f"Invalid/non-finite ERA5 value: {eid}/{variable}",
                )
                valid += 1

        arrays[variable] = values
        quality[variable] = {
            "valid_count": valid,
            "null_count": nulls,
            "unit": units[variable],
        }

    returned_lat = payload.get("latitude")
    returned_lon = payload.get("longitude")
    require(is_number(returned_lat) and is_number(returned_lon),
            f"ERA5 returned grid coordinates invalid: {eid}")

    grid_distance = haversine_km(
        lat, lon, float(returned_lat), float(returned_lon)
    )

    returned_elevation = payload.get("elevation")
    if returned_elevation is not None:
        require(is_number(returned_elevation),
                f"ERA5 returned elevation invalid: {eid}")

    hourly_map = {}
    for i, stamp in enumerate(times):
        dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
        ps = arrays["surface_pressure"][i]
        t2 = arrays["temperature_2m"][i]
        dew = arrays["dew_point_2m"][i]
        tcwv = arrays["total_column_integrated_water_vapour"][i]

        ztd = None
        zhd = None
        zwd = None
        pi_inverse = None

        # Strict rule: direct TCWV, pressure and temperature are all required.
        # Dew point is retained only as a diagnostic; it is never a fallback.
        if ps is not None and t2 is not None and tcwv is not None:
            require(float(ps) > 0, f"Non-positive surface pressure: {eid}")
            require(float(tcwv) >= 0, f"Negative direct TCWV: {eid}")
            calculation = calculate_era5_ztd(
                float(ps), float(t2), float(tcwv), lat, elev
            )
            ztd = calculation["ztd_mm"]
            zhd = calculation["zhd_mm"]
            zwd = calculation["zwd_mm"]
            pi_inverse = calculation["pi_inverse_mm_per_kg_m2"]

        hourly_map[dt] = {
            "surface_pressure_hpa": ps,
            "temperature_2m_c": t2,
            "dew_point_2m_c_diagnostic_only": dew,
            "direct_tcwv_kg_m2": tcwv,
            "era5_zhd_mm": zhd,
            "era5_zwd_mm": zwd,
            "era5_ztd_mm": ztd,
            "pi_inverse_mm_per_kg_m2": pi_inverse,
        }

    model_metadata = payload.get("models", payload.get("model", "NOT_RETURNED"))

    return {
        "hourly": hourly_map,
        "cache_path": str(cache_path.relative_to(ROOT)),
        "cache_sha256": actual_hash,
        "cache_bytes": len(raw),
        "request_parameters": params,
        "variable_quality": quality,
        "tcwv_valid_count": quality[
            "total_column_integrated_water_vapour"
        ]["valid_count"],
        "tcwv_null_count": quality[
            "total_column_integrated_water_vapour"
        ]["null_count"],
        "returned_grid_latitude": float(returned_lat),
        "returned_grid_longitude": float(returned_lon),
        "station_to_grid_distance_km": grid_distance,
        "requested_station_elevation_m": elev,
        "response_elevation_m": returned_elevation,
        "response_timezone": payload.get("timezone", "NOT_RETURNED"),
        "response_model_metadata": model_metadata,
        "response_model_metadata_status": (
            "RETURNED" if model_metadata != "NOT_RETURNED" else "NOT_RETURNED"
        ),
        "quality": quality,
    }


def parse_member_date(member_name: str, station: str):
    base = member_name.replace("\\", "/").split("/")[-1]
    parts = base.split(".")
    if len(parts) < 4 or parts[0].upper() != station:
        return None
    if not parts[1].isdigit() or not parts[2].isdigit():
        return None
    year = int(parts[1])
    doy = int(parts[2])
    try:
        date = datetime(year, 1, 1).date() + timedelta(days=doy - 1)
    except ValueError:
        return None
    if date.year != year or not 1 <= doy <= (366 if is_leap(year) else 365):
        return None
    return date


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def parse_sinex_epoch(token: str) -> datetime:
    parts = token.split(":")
    if len(parts) != 3:
        raise ValueError("Epoch must contain YY:DDD:SSSSS")

    yy, doy, seconds = (int(x) for x in parts)
    if yy >= 1000:
        year = yy
    elif yy < 80:
        year = 2000 + yy
    else:
        year = 1900 + yy

    max_doy = 366 if is_leap(year) else 365
    require(1 <= doy <= max_doy, f"Invalid day of year: {token}")
    require(0 <= seconds < 86400, f"Invalid seconds of day: {token}")

    return (
        datetime(year, 1, 1, tzinfo=UTC)
        + timedelta(days=doy - 1, seconds=seconds)
    )


def parse_gnss_archives(
    event_id: str,
    station: str,
    urls_field: str,
    start_dt: datetime,
    end_dt: datetime,
) -> dict:
    hourly_values = defaultdict(list)
    seen_timestamps = set()
    archive_records = []
    found_dates = set()
    headers_seen = set()

    counters = defaultdict(int)

    urls = [x.strip() for x in urls_field.split(";") if x.strip()]
    require(bool(urls), f"No GNSS archive URL for {event_id}")

    for url in urls:
        parsed = urlparse(url)
        require(parsed.scheme == "https", f"Non-HTTPS GNSS URL: {url}")
        require(parsed.netloc.lower() == "geodesy.unr.edu",
                f"Unexpected GNSS archive host: {url}")

        base = parsed.path.rstrip("/").split("/")[-1]
        segments = parsed.path.strip("/").split("/")
        require(station in segments, f"Station missing from URL path: {url}")
        require(base.upper().startswith(station + "."),
                f"Archive filename/station mismatch: {url}")

        zip_path = GNSS_ZIP_DIR / base
        require(zip_path.is_file(), f"Local GNSS ZIP missing: {zip_path}")

        archive_hash = sha256_file(zip_path)
        archive_records.append({
            "url": url,
            "filename": base,
            "bytes": zip_path.stat().st_size,
            "sha256": archive_hash,
        })

        with zipfile.ZipFile(zip_path, "r") as zf:
            members = sorted(zf.namelist())

            for member in members:
                member_date = parse_member_date(member, station)
                if member_date is None:
                    continue
                if not start_dt.date() <= member_date <= end_dt.date():
                    continue

                found_dates.add(member_date)
                counters["daily_members_selected"] += 1

                raw = zf.read(member)
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)

                text = raw.decode("utf-8", errors="replace")
                in_solution = False
                columns = None
                site_index = None
                epoch_index = None
                trotot_index = None
                found_solution_block = False

                for line in text.splitlines():
                    if line.startswith("+TROP/SOLUTION"):
                        in_solution = True
                        found_solution_block = True
                        continue
                    if line.startswith("-TROP/SOLUTION"):
                        break
                    if not in_solution or not line.strip():
                        continue

                    if line.startswith("*"):
                        header = line.lstrip("*").strip().split()
                        if "TROTOT" in header:
                            require(
                                "SITE" in header,
                                f"SITE header absent in {member}",
                            )
                            epoch_candidates = [
                                x for x in ("___EPOCH____", "EPOCH")
                                if x in header
                            ]
                            require(
                                bool(epoch_candidates),
                                f"Epoch header absent in {member}",
                            )
                            columns = header
                            site_index = header.index("SITE")
                            epoch_index = header.index(epoch_candidates[0])
                            trotot_index = header.index("TROTOT")
                            headers_seen.add(" ".join(header))
                        continue

                    counters["solution_rows_seen"] += 1
                    if columns is None:
                        counters["rows_before_valid_header"] += 1
                        continue

                    max_index = max(site_index, epoch_index, trotot_index)
                    fields = line.split()
                    if len(fields) <= max_index:
                        counters["malformed_field_count"] += 1
                        continue

                    if fields[site_index].strip().upper() != station:
                        counters["wrong_station_rows"] += 1
                        continue

                    try:
                        dt = parse_sinex_epoch(fields[epoch_index])
                    except Exception:
                        counters["malformed_epochs"] += 1
                        continue

                    if dt.date() != member_date:
                        counters["wrong_member_day_rows"] += 1
                        continue

                    if dt < start_dt or dt > end_dt:
                        counters["outside_requested_time_range"] += 1
                        continue

                    try:
                        value = float(fields[trotot_index])
                    except (ValueError, IndexError):
                        counters["nonnumeric_trotot"] += 1
                        continue

                    if not math.isfinite(value):
                        counters["nonfinite_trotot"] += 1
                        continue

                    if not 1000.0 <= value <= 3500.0:
                        counters["out_of_range_trotot"] += 1
                        continue

                    if dt in seen_timestamps:
                        counters["duplicate_timestamps"] += 1
                        continue

                    seen_timestamps.add(dt)
                    hour = dt.replace(minute=0, second=0, microsecond=0)
                    hourly_values[hour].append(value)
                    counters["accepted_5minute_observations"] += 1

                if not found_solution_block:
                    counters["members_without_solution_block"] += 1

    all_dates = []
    day = start_dt.date()
    while day <= end_dt.date():
        all_dates.append(day)
        day += timedelta(days=1)

    missing_dates = sorted(d.isoformat() for d in all_dates if d not in found_dates)

    hourly = {
        dt: sum(values) / len(values)
        for dt, values in hourly_values.items()
    }
    sample_counts = {
        dt: len(values) for dt, values in hourly_values.items()
    }

    return {
        "hourly": hourly,
        "sample_counts": sample_counts,
        "archive_records": archive_records,
        "headers_seen": sorted(headers_seen),
        "counters": dict(counters),
        "daily_members_found": len(found_dates),
        "daily_members_expected": len(all_dates),
        "missing_daily_dates": missing_dates,
        "missing_daily_member_count": len(missing_dates),
        "accepted_hour_count": len(hourly),
        "time_scale_status": "LEGACY_SINEX_UTC_INFERRED",
        "trotot_unit_interpretation": (
            "mm_assumed_from_legacy_SINEX_TRO_product_convention; "
            "not independently declared in this member header"
        ),
    }


def ols_calibration(
    pairs: list[tuple[float, float]],
    baseline_name: str,
) -> dict:
    n = len(pairs)
    result = {
        "baseline": baseline_name,
        "n_pairs": n,
        "intercept_alpha": None,
        "slope_beta": None,
        "predictor_variance_population": None,
        "predictor_sxx": None,
        "correlation": None,
        "residual_rmse_mm": None,
        "status": None,
        "failure_reason": "",
        "minimum_pairs": 24,
        "degenerate_sxx_threshold": 1e-6,
    }

    if n < 24:
        result["status"] = "FAILED_LT24_MATCHED_PAIRS"
        result["failure_reason"] = "Fewer than 24 matched baseline hours"
        return result

    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    result["predictor_sxx"] = sxx
    result["predictor_variance_population"] = sxx / n

    if sxx < 1e-6:
        result["status"] = "FAILED_DEGENERATE_PREDICTOR_VARIANCE"
        result["failure_reason"] = "ERA5 predictor Sxx below 1e-6"
        return result

    covariance = sum(
        (x - mx) * (y - my) for x, y in pairs
    )
    beta = covariance / sxx
    alpha = my - beta * mx

    syy = sum((y - my) ** 2 for y in ys)
    if syy > 0:
        corr = covariance / math.sqrt(sxx * syy)
    else:
        corr = None

    residuals = [
        y - (alpha + beta * x) for x, y in pairs
    ]
    rmse = math.sqrt(sum(r * r for r in residuals) / n)

    result.update({
        "intercept_alpha": alpha,
        "slope_beta": beta,
        "correlation": corr,
        "residual_rmse_mm": rmse,
        "status": "PASS",
    })
    return result


def window_rows(rows: list[dict], window_name: str) -> list[dict]:
    start, end = WINDOWS[window_name]
    return [r for r in rows if start <= r["hour_offset"] < end]


def window_counts(rows: list[dict]) -> dict:
    return {
        "gnss_hours": sum(r["gnss_ztd_mm"] is not None for r in rows),
        "direct_tcwv_hours": sum(
            r["direct_tcwv_kg_m2"] is not None for r in rows
        ),
        "era5_ztd_hours": sum(r["era5_ztd_mm"] is not None for r in rows),
        "matched_tcwv_gnss_era5_hours": sum(
            r["gnss_ztd_mm"] is not None and
            r["era5_ztd_mm"] is not None
            for r in rows
        ),
    }


def score_window(
    rows: list[dict],
    baseline_name: str,
    target_name: str,
    field: str,
    event_id: str,
    feature_name: str,
) -> tuple[dict, list[dict]]:
    baseline_range = WINDOWS[baseline_name]
    target_range = WINDOWS[target_name]

    baseline = [
        r[field] for r in rows
        if baseline_range[0] <= r["hour_offset"] < baseline_range[1]
        and r.get(field) is not None
    ]
    target = [
        r for r in rows
        if target_range[0] <= r["hour_offset"] < target_range[1]
        and r.get(field) is not None
    ]

    result = {
        "event_id": event_id,
        "feature": feature_name,
        "baseline": baseline_name,
        "target_window": target_name,
        "baseline_field": field,
        "target_field": field,
        "n_baseline_pool": len(baseline),
        "n_target_values": len(target),
        "baseline_median": None,
        "baseline_mad_raw": None,
        "baseline_scale": None,
        "pooled_scale_floor_used": None,
        "target_hour_specific_count": 0,
        "target_pooled_fallback_count": 0,
        "feature_max_abs_robust_z": None,
        "feature_q95_abs_robust_z": None,
        "status": None,
        "failure_reason": "",
        "q95_definition": "sorted_values[floor(0.95*(n-1))]",
    }
    hour_stats = []

    if len(baseline) < 20:
        result["status"] = "FAILED_BASELINE_POOL_LT20"
        result["failure_reason"] = "Fewer than 20 valid baseline values"
        return result, hour_stats

    pooled_med, pooled_mad, pooled_scale, pooled_floor = median_and_mad(
        baseline
    )
    result.update({
        "baseline_median": pooled_med,
        "baseline_mad_raw": pooled_mad,
        "baseline_scale": pooled_scale,
        "pooled_scale_floor_used": pooled_floor,
    })

    by_hour = {}
    for hour in range(24):
        vals = [
            r[field] for r in rows
            if baseline_range[0] <= r["hour_offset"] < baseline_range[1]
            and r.get(field) is not None
            and r["timestamp"].hour == hour
        ]
        if len(vals) >= 2:
            med, mad, scale, floor_used = median_and_mad(vals)
            source = "HOUR_SPECIFIC"
        else:
            med, mad, scale = pooled_med, pooled_mad, pooled_scale
            floor_used = pooled_floor
            source = "POOLED_FALLBACK"

        by_hour[hour] = (med, scale, source)
        hour_stats.append({
            "event_id": event_id,
            "feature": feature_name,
            "baseline": baseline_name,
            "utc_hour_of_day": hour,
            "baseline_sample_count": len(vals),
            "median": med,
            "mad_raw": mad,
            "scale": scale,
            "scale_floor_used": floor_used,
            "source": source,
        })

    scores = []
    n_hour_specific = 0
    n_fallback = 0
    for row in target:
        med, scale, source = by_hour[row["timestamp"].hour]
        scores.append(abs((row[field] - med) / scale))
        if source == "HOUR_SPECIFIC":
            n_hour_specific += 1
        else:
            n_fallback += 1

    result["target_hour_specific_count"] = n_hour_specific
    result["target_pooled_fallback_count"] = n_fallback

    if not scores:
        result["status"] = "FAILED_NO_TARGET_VALUES"
        result["failure_reason"] = "No target-window values to score"
        return result, hour_stats

    ordered = sorted(scores)
    q_index = int(0.95 * (len(ordered) - 1))
    result["feature_max_abs_robust_z"] = max(ordered)
    result["feature_q95_abs_robust_z"] = ordered[q_index]
    result["status"] = "PASS"
    return result, hour_stats


def max_consecutive_true(values: list[bool]) -> int:
    best = 0
    current = 0
    for value in values:
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def daily_coverage_for_event(
    event_id: str,
    rows: list[dict],
) -> tuple[list[dict], dict]:
    output = []
    window_gap_summary = {}

    for window_name, (start, end) in WINDOWS.items():
        selected = [
            r for r in rows
            if start <= r["hour_offset"] < end
        ]

        dates = sorted({r["timestamp"].date() for r in selected})
        zero_flags = []

        for date_index, calendar_date in enumerate(dates):
            day_rows = [
                r for r in selected
                if r["timestamp"].date() == calendar_date
            ]

            matched = sum(
                r["gnss_ztd_mm"] is not None
                and r["era5_ztd_mm"] is not None
                for r in day_rows
            )
            gnss = sum(r["gnss_ztd_mm"] is not None for r in day_rows)
            tcwv = sum(r["direct_tcwv_kg_m2"] is not None for r in day_rows)
            era_ztd = sum(r["era5_ztd_mm"] is not None for r in day_rows)
            zero = matched == 0
            zero_flags.append(zero)

            output.append({
                "event_id": event_id,
                "window": window_name,
                "calendar_date_index_in_window": date_index,
                "calendar_date": calendar_date.isoformat(),
                "hours_in_day_bin": len(day_rows),
                "gnss_valid_hours": gnss,
                "direct_tcwv_valid_hours": tcwv,
                "era5_ztd_valid_hours": era_ztd,
                "matched_gnss_era5_hours": matched,
                "zero_matched_hours_day": zero,
            })

        window_gap_summary[window_name] = max_consecutive_true(zero_flags)

    return output, window_gap_summary


def process_pilot_event(
    event: dict,
    station_row: dict,
    stage2c_row: dict,
    manifest: dict,
) -> dict:
    eid = event["event_id"]
    sid = event["station_id"].strip().upper()
    origin = parse_utc(event["origin_time_utc"])
    event_hour = origin.replace(minute=0, second=0, microsecond=0)

    parse_start = origin - timedelta(days=45)
    parse_end = origin + timedelta(days=5)

    era = validate_era5_cache(event, station_row, manifest)
    gnss = parse_gnss_archives(
        eid, sid, stage2c_row["unr_trop_urls"], parse_start, parse_end
    )

    rows = []
    for offset in range(-1080, 1):
        stamp = event_hour + timedelta(hours=offset)
        era_row = era["hourly"].get(stamp, {})
        gnss_value = gnss["hourly"].get(stamp)
        gnss_n = gnss["sample_counts"].get(stamp, 0)

        tcwv = era_row.get("direct_tcwv_kg_m2")
        ze = era_row.get("era5_ztd_mm")

        raw_residual = None
        if gnss_value is not None and ze is not None:
            raw_residual = gnss_value - ze

        rows.append({
            "event_id": eid,
            "station_id": sid,
            "timestamp": stamp,
            "timestamp_utc": iso_utc(stamp),
            "hour_offset": offset,
            "hour_of_day_utc": stamp.hour,
            "gnss_ztd_mm": gnss_value,
            "gnss_5minute_sample_count": gnss_n,
            "surface_pressure_hpa": era_row.get("surface_pressure_hpa"),
            "temperature_2m_c": era_row.get("temperature_2m_c"),
            "dew_point_2m_c_diagnostic_only":
                era_row.get("dew_point_2m_c_diagnostic_only"),
            "direct_tcwv_kg_m2": tcwv,
            "era5_zhd_mm": era_row.get("era5_zhd_mm"),
            "era5_zwd_mm": era_row.get("era5_zwd_mm"),
            "era5_ztd_mm": ze,
            "pi_inverse_mm_per_kg_m2":
                era_row.get("pi_inverse_mm_per_kg_m2"),
            "raw_gnss_minus_era5_mm": raw_residual,
            "calibrated_residual_b0_mm": None,
            "calibrated_residual_b1_mm": None,
        })

    calibration_rows = []
    calibrations = {}

    for baseline_name in ("B0", "B1"):
        start, end = WINDOWS[baseline_name]
        pairs = [
            (r["era5_ztd_mm"], r["gnss_ztd_mm"])
            for r in rows
            if start <= r["hour_offset"] < end
            and r["era5_ztd_mm"] is not None
            and r["gnss_ztd_mm"] is not None
        ]
        calibration = ols_calibration(pairs, baseline_name)
        calibrations[baseline_name] = calibration
        calibration_rows.append({
            "event_id": eid,
            "station_id": sid,
            **calibration,
        })

        if calibration["status"] == "PASS":
            alpha = calibration["intercept_alpha"]
            beta = calibration["slope_beta"]
            for row in rows:
                if (
                    row["era5_ztd_mm"] is not None
                    and row["gnss_ztd_mm"] is not None
                ):
                    residual = (
                        row["gnss_ztd_mm"]
                        - (alpha + beta * row["era5_ztd_mm"])
                    )
                    key = (
                        "calibrated_residual_b0_mm"
                        if baseline_name == "B0"
                        else "calibrated_residual_b1_mm"
                    )
                    row[key] = residual

    metrics = {
        name: window_counts(window_rows(rows, name))
        for name in ("B0", "W0", "B1", "W1")
    }

    scores = []
    hour_stats = []

    score_specs = [
        ("M2a_raw_GNSS_ZTD", "gnss_ztd_mm"),
        ("M2b_raw_GNSS_minus_ERA5", "raw_gnss_minus_era5_mm"),
        ("M2c_B0_calibrated_residual", "calibrated_residual_b0_mm"),
    ]

    for feature_name, field in score_specs:
        score, stats = score_window(
            rows, "B0", "W0", field, eid, feature_name
        )
        scores.append(score)
        hour_stats.extend(stats)

    score_specs_b1 = [
        ("M2a_raw_GNSS_ZTD", "gnss_ztd_mm"),
        ("M2b_raw_GNSS_minus_ERA5", "raw_gnss_minus_era5_mm"),
        ("M2c_B1_calibrated_residual", "calibrated_residual_b1_mm"),
    ]

    for feature_name, field in score_specs_b1:
        score, stats = score_window(
            rows, "B1", "W1", field, eid, feature_name
        )
        scores.append(score)
        hour_stats.extend(stats)

    daily_rows, gap_summary = daily_coverage_for_event(eid, rows)

    reasons = []
    for baseline_name in ("B0", "B1"):
        if calibrations[baseline_name]["status"] != "PASS":
            reasons.append(
                f"{baseline_name}_CALIBRATION:"
                f"{calibrations[baseline_name]['status']}"
            )

    if metrics["W0"]["matched_tcwv_gnss_era5_hours"] < 12:
        reasons.append("W0_MATCHED_HOURS_LT12")
    if metrics["W1"]["matched_tcwv_gnss_era5_hours"] < 12:
        reasons.append("W1_MATCHED_HOURS_LT12")

    m2c_scores = [
        x for x in scores
        if x["feature"].startswith("M2c_")
    ]
    for score in m2c_scores:
        if score["status"] != "PASS":
            reasons.append(
                f"{score['feature']}_{score['target_window']}:"
                f"{score['status']}"
            )

    max_gap = max(gap_summary.values()) if gap_summary else 0
    warning_windows = [
        name for name, count in gap_summary.items() if count >= 3
    ]

    role = event["role"]
    reference_notes = {
        "us6000nith": (
            "Addendum 002 reference: B0/W0/B1/W1 matched hours "
            "127/240/288/240; B0 has seven consecutive zero-match days"
        ),
        "us7000lsze": (
            "Addendum 002 reference: B1=30 and W1=0 matched hours"
        ),
        "us7000m9g4": (
            "Addendum 002 reference: no matched hours in B0/W0/B1/W1"
        ),
        "us7000n05d": (
            "Addendum 002 reference: B0=0 and W0=0 matched hours"
        ),
        "usp000ahfr": "No pilot-specific numerical reference count frozen",
    }

    ledger = {
        "event_id": eid,
        "station_id": sid,
        "role": role,
        "origin_time_utc": iso_utc(origin),
        "region": event.get("region", ""),
        "strict_m2c_feature_eligible": not reasons,
        "eligibility_status": (
            "STRICT_NUMERICAL_ELIGIBLE"
            if not reasons else "STRICT_NUMERICAL_INELIGIBLE"
        ),
        "exclusion_reasons": ";".join(reasons),
        "B0_calibration_status": calibrations["B0"]["status"],
        "B0_calibration_pairs": calibrations["B0"]["n_pairs"],
        "B1_calibration_status": calibrations["B1"]["status"],
        "B1_calibration_pairs": calibrations["B1"]["n_pairs"],
        "B0_matched_hours": metrics["B0"]["matched_tcwv_gnss_era5_hours"],
        "W0_matched_hours": metrics["W0"]["matched_tcwv_gnss_era5_hours"],
        "B1_matched_hours": metrics["B1"]["matched_tcwv_gnss_era5_hours"],
        "W1_matched_hours": metrics["W1"]["matched_tcwv_gnss_era5_hours"],
        "B0_gnss_hours": metrics["B0"]["gnss_hours"],
        "W0_gnss_hours": metrics["W0"]["gnss_hours"],
        "B1_gnss_hours": metrics["B1"]["gnss_hours"],
        "W1_gnss_hours": metrics["W1"]["gnss_hours"],
        "B0_direct_tcwv_hours": metrics["B0"]["direct_tcwv_hours"],
        "W0_direct_tcwv_hours": metrics["W0"]["direct_tcwv_hours"],
        "B1_direct_tcwv_hours": metrics["B1"]["direct_tcwv_hours"],
        "W1_direct_tcwv_hours": metrics["W1"]["direct_tcwv_hours"],
        "tcwv_valid_hours_full_cache": era["tcwv_valid_count"],
        "tcwv_null_hours_full_cache": era["tcwv_null_count"],
        "grid_latitude": era["returned_grid_latitude"],
        "grid_longitude": era["returned_grid_longitude"],
        "station_to_grid_distance_km": era["station_to_grid_distance_km"],
        "requested_station_elevation_m": era["requested_station_elevation_m"],
        "response_elevation_m": era["response_elevation_m"],
        "response_elevation_is_independent_dem": False,
        "response_model_metadata": str(era["response_model_metadata"]),
        "response_model_metadata_status":
            era["response_model_metadata_status"],
        "gnss_daily_members_expected": gnss["daily_members_expected"],
        "gnss_daily_members_found": gnss["daily_members_found"],
        "gnss_missing_daily_member_count":
            gnss["missing_daily_member_count"],
        "max_consecutive_zero_match_days": max_gap,
        "temporal_coverage_warning": bool(warning_windows),
        "temporal_coverage_warning_windows": ";".join(warning_windows),
        "gnss_time_scale_status": gnss["time_scale_status"],
        "trotot_unit_interpretation": gnss["trotot_unit_interpretation"],
        "reference_note_addendum002": reference_notes[eid],
        "era5_cache_sha256": era["cache_sha256"],
    }

    hourly_output = []
    for row in rows:
        hourly_output.append({
            **row,
            "timestamp": iso_utc(row["timestamp"]),
        })

    parser_audit = {
        "event_id": eid,
        "station_id": sid,
        "time_scale_status": gnss["time_scale_status"],
        "trotot_unit_interpretation": gnss["trotot_unit_interpretation"],
        "daily_members_expected": gnss["daily_members_expected"],
        "daily_members_found": gnss["daily_members_found"],
        "missing_daily_member_count": gnss["missing_daily_member_count"],
        "missing_daily_dates": ";".join(gnss["missing_daily_dates"]),
        "headers_seen": json.dumps(gnss["headers_seen"]),
        "archive_records": json.dumps(gnss["archive_records"], sort_keys=True),
        **gnss["counters"],
    }

    return {
        "ledger": ledger,
        "hourly": hourly_output,
        "calibrations": calibration_rows,
        "scores": scores,
        "hour_stats": hour_stats,
        "daily": daily_rows,
        "parser_audit": parser_audit,
        "era5": era,
        "gnss": gnss,
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    require(not OUTPUT_DIR.exists(),
            f"Output already exists; refusing overwrite: {OUTPUT_DIR}")
    require(not TEMP_OUTPUT_DIR.exists(),
            f"Temporary output already exists; inspect it: {TEMP_OUTPUT_DIR}")

    unit_tests = run_unit_tests()
    inputs, input_hashes = load_and_verify_inputs()

    results = []
    for eid in PILOT_EVENT_IDS:
        event = inputs["v004"][eid]
        sid = event["station_id"].strip().upper()
        matches = inputs["registry"][sid]
        result = process_pilot_event(
            event, matches[0], inputs["stage2c"][eid], inputs["manifest"]
        )
        results.append(result)
        print(
            f"Processed pilot event {eid}/{sid}: "
            f"{result['ledger']['eligibility_status']}"
        )

    ledger_rows = [r["ledger"] for r in results]
    hourly_rows = [x for r in results for x in r["hourly"]]
    calibration_rows = [x for r in results for x in r["calibrations"]]
    score_rows = [x for r in results for x in r["scores"]]
    hour_stats = [x for r in results for x in r["hour_stats"]]
    daily_rows = [x for r in results for x in r["daily"]]
    parser_rows = [r["parser_audit"] for r in results]

    # The pilot is a diagnostic software validation, not a benchmark.
    # It deliberately does not calculate AUCs, permutations or inferential tests.
    qa = {
        "script_version": SCRIPT_VERSION,
        "pilot_version": PILOT_VERSION,
        "status": "PILOT_FEATURE_GENERATION_COMPLETED",
        "purpose": "Five-event implementation and provenance diagnostic only",
        "events_processed": len(results),
        "event_ids": PILOT_EVENT_IDS,
        "unit_tests_passed": len(unit_tests),
        "unit_tests_failed": sum(x["status"] != "PASS" for x in unit_tests),
        "input_crosswalk_events_verified": EXPECTED_FULL_EVENTS,
        "stage2c_rows_verified": EXPECTED_STAGE2C_ROWS,
        "pinned_era5_cache_manifest_sha256":
            sha256_file(CACHE_MANIFEST),
        "all_pilot_cache_hashes_verified": True,
        "all_pilot_archive_files_verified": True,
        "strict_eligibility_counts": {
            "eligible": sum(
                bool(r["strict_m2c_feature_eligible"]) for r in ledger_rows
            ),
            "ineligible": sum(
                not bool(r["strict_m2c_feature_eligible"]) for r in ledger_rows
            ),
        },
        "warnings": [
            "Pilot results are not inferential results.",
            "No AUC, cross-validation, permutation or model comparison was run.",
            "The five-event pilot cannot verify the full 88/36, 87/35 or 19/15 cohort counts.",
            "ERA5 model was explicitly requested; response metadata may not independently attest it.",
            "NGL TRO 1.00 UTC time scale is recorded as LEGACY_SINEX_UTC_INFERRED.",
            "TROTOT mm is an explicit legacy product interpretation, not a unit printed in the sample header.",
            "Dew point is diagnostic only and never substitutes for TCWV.",
            "Partial five-minute hourly GNSS means are retained; sample counts are exported.",
            "Temporal zero-match gaps do not identify which source caused the missing pair.",
        ],
    }

    # Create a temporary output package. The final path is created only after
    # every calculation and file write succeeds. Existing output is never replaced.
    TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=False)

    try:
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_event_eligibility_ledger.csv",
            ledger_rows,
            list(ledger_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_hourly_features.csv",
            hourly_rows,
            list(hourly_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_calibration_diagnostics.csv",
            calibration_rows,
            list(calibration_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_feature_scores.csv",
            score_rows,
            list(score_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_hourly_baseline_stats.csv",
            hour_stats,
            list(hour_stats[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_daily_coverage.csv",
            daily_rows,
            list(daily_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_gnss_parser_audit.csv",
            parser_rows,
            list(parser_rows[0].keys()),
        )
        write_csv(
            TEMP_OUTPUT_DIR / "pilot_unit_tests.csv",
            unit_tests,
            list(unit_tests[0].keys()),
        )
        write_json(TEMP_OUTPUT_DIR / "pilot_qa.json", qa)

        output_hashes = {}
        for path in sorted(TEMP_OUTPUT_DIR.iterdir()):
            if path.is_file():
                output_hashes[path.name] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }

        manifest = {
            "schema": "LAIC_GUARD_STAGE6A1_STRICT_TCWV_PILOT_MANIFEST_v001",
            "script_version": SCRIPT_VERSION,
            "pilot_version": PILOT_VERSION,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "root": str(ROOT),
            "output_directory": str(OUTPUT_DIR.relative_to(ROOT)),
            "input_sha256": input_hashes,
            "expected_pinned_sha256": EXPECTED_HASHES,
            "pilot_event_ids": PILOT_EVENT_IDS,
            "pilot_cache_records": {
                r["ledger"]["event_id"]: {
                    "era5_cache_sha256": r["era5"]["cache_sha256"],
                    "gnss_archives": r["gnss"]["archive_records"],
                }
                for r in results
            },
            "formula": {
                "zhd": (
                    "2.2768*Ps / "
                    "[1 - 0.00266*cos(2*phi) - 0.00028*(h/1000)]"
                ),
                "mean_temperature": "70.2 + 0.72*(T2_C + 273.15)",
                "pi_inverse": (
                    "1e-5*461.5*(3.739e5/Tmean + 22.1)"
                ),
                "zwd": "Pi_inverse * direct_TCWV_kg_m2",
                "ztd": "ZHD + ZWD",
                "calibration": "GNSS_ZTD = alpha + beta*ERA5_ZTD + residual",
                "calibrated_residual": (
                    "GNSS_ZTD - (alpha + beta*ERA5_ZTD)"
                ),
            },
            "calibration_rules": {
                "separate_baselines": True,
                "minimum_matched_pairs": 24,
                "degenerate_predictor_sxx_threshold": 1e-6,
                "silent_fallback_prohibited": True,
            },
            "feature_rules": {
                "minimum_baseline_pool": 20,
                "hour_of_day_minimum": 2,
                "mad_scale_factor": 1.4826,
                "minimum_scale": 1e-6,
                "minimum_target_matched_hours": 12,
                "q95": "sorted_values[floor(0.95*(n-1))]",
            },
            "gnss_parser": {
                "column_selection": "Header-driven TROTOT",
                "trotot_acceptance_range_mm": [1000, 3500],
                "hourly_aggregation": "Mean of accepted five-minute records",
                "partial_hours_retained": True,
                "duplicate_policy": "First valid timestamp retained; duplicates counted",
                "time_scale": "LEGACY_SINEX_UTC_INFERRED",
            },
            "era5_provenance": {
                "requested_model": "era5",
                "model_independently_attested": False,
                "cell_selection": "land",
                "timezone": "UTC",
                "dew_point_fallback": False,
                "tcwv_imputation": False,
                "station_elevation_used_in_zhd": True,
                "returned_elevation_is_independent_dem": False,
            },
            "statistical_inference_run": False,
            "output_files": output_hashes,
        }

        write_json(TEMP_OUTPUT_DIR / "manifest.json", manifest)

        # Atomic rename to the final destination; no overwrite is permitted.
        require(not OUTPUT_DIR.exists(),
                f"Output appeared during run; refusing overwrite: {OUTPUT_DIR}")
        os.replace(TEMP_OUTPUT_DIR, OUTPUT_DIR)

    except Exception:
        print(
            f"Output staging directory retained for inspection: "
            f"{TEMP_OUTPUT_DIR}",
            file=sys.stderr,
        )
        raise

    print("\n===== STAGE 6A.1 PILOT COMPLETE =====")
    print("Output:", OUTPUT_DIR)
    print("Events:", len(ledger_rows))
    print("Eligible:", qa["strict_eligibility_counts"]["eligible"])
    print("Ineligible:", qa["strict_eligibility_counts"]["ineligible"])
    print("Unit tests:", len(unit_tests), "PASS")
    print("Statistical inference: NOT RUN")
    print("Original scripts, caches and V004 reports were read-only.")


if __name__ == "__main__":
    main()
