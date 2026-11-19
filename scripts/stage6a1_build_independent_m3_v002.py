#!/usr/bin/env python3
"""
LAIC-GUARD Stage 6A.1 independent M3 VTEC feature builder v002.

This is a standalone reconstruction of the V004 M3 branch. It does not import
V004, Stage5B, Stage4B, or any legacy processing module. It reads the frozen
Stage4B event population, Stage1D epicentres, IONEX daily cache, OMNI hourly
cache, and the already-frozen Stage6A.1 cohort/component records.

It creates a new package atomically. It never overwrites an existing package.
No statistical inference or model benchmarking is performed.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

S4B_PATH = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
S1D_PATH = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
V004_FEATURES_PATH = ROOT / "reports/stage6a/audit_repaired_v004_regionfix_cachefix_distancefix/analysis/stage6a_v004_event_features.csv"
V004_SCRIPT_PATH = ROOT / "scripts/stage6a_repaired_benchmark_v004_regionfix_cachefix_distancefix.py"
STAGE4B_SCRIPT_PATH = ROOT / "scripts/stage4b_scale_full_tier1_cohort_v001.py"
STAGE5B_SCRIPT_PATH = ROOT / "scripts/stage5b_hardened_audit_v002.py"
IONEX_DIR = ROOT / "data/external/ionosphere/code_ionex_v001"
OMNI_DIR = ROOT / "data/external/space_weather/omniweb_lowres_v001"

TCWV_DIR = ROOT / "reports/stage6a1/strict_tcwv_v001/full_v001"
LEDGER_PATH = TCWV_DIR / "full_event_eligibility_ledger.csv"
MEMBERSHIP_PATH = TCWV_DIR / "full_dependency_component_membership.csv"
SUMMARY_PATH = TCWV_DIR / "full_dependency_population_summary.csv"
TCWV_MANIFEST_PATH = TCWV_DIR / "manifest.json"

PROTOCOL_PATHS = {
    "protocol": ROOT / "protocols/stage6a1_strict_tcwv_v001.md",
    "addendum001": ROOT / "protocols/stage6a1_strict_tcwv_v001_addendum001.md",
    "addendum002": ROOT / "protocols/stage6a1_strict_tcwv_v001_addendum002.md",
}

OUTPUT_DIR = ROOT / "reports/stage6a1/independent_m3_v001/full_v002"
BUILDING_DIR = ROOT / "reports/stage6a1/independent_m3_v001/full_v002.building"

EXPECTED_INPUT_SHA256 = {
    "s4b": "BA1DD886CD2861F32928A039A9308323395EE151DD8CA6EC70FFF6AFB28C578F",
    "s1d": "1BE9B0CC60BF6B36B4C5F38134E58F7B79D93E24705E7178B22F16B1BE0C21BD",
    "v004_features": "8D8182CEBE35D10C0492D2B42E2CD337669BAA4DCB7C8A801771B269A3A98334",
    "v004_script": "4C7DFD199A3C04D82E4850AE487FA5AD1642EE59DF0A51B60948F4B6EE5A68A0",
    "stage4b_script": "91F741C1500FB263F229DDF1D69590B357158CBFB42105F3F992AEA0DA3994B0",
    "stage5b_script": "06BC22ED858D65CB56A0309185E435463817B0F6E8A455F43F6AA7BEE971476C",
    "ledger": "55189838722A7F4BD08C70FCB7C16772B3DE8B860C9508D07B8FEC7D9DD9E851",
    "membership": "C78B08324A4572DD796487A0F9FFBD292117291EFD61AA2C0D927951DF116AC5",
    "summary": "903A9F9DDDC73CC155C8CEDA5CA83FC0776D6381F9681C98FF59BA3E975BEC8F",
    "tcwv_manifest": "D9F43845D3997C03FAE463D3AAD042EC922CBCF309B3443BDADCF23727CEFB53",
    "protocol": "6088588F5CBD1DD29CFBA2B1AF04A1261B25AA91E48FECD08E793A8F8F272538",
    "addendum001": "3BD5E4A4EACD157E90C9C4E5FDE3B8B3F3019F51E17CD2E4AB7281AE863C2368",
    "addendum002": "711062902326CE99268A96A81B9627447A4E726D4305E507B955E4C5CC429D3D",
}

WIN_B0 = (-1080, -792)
WIN_W0 = (-792, -552)
WIN_B1 = (-552, -264)
WIN_W1 = (-264, -24)
WIN_GUARD = (-24, 0)
TIMELINE_OFFSETS = range(-1080, 1)

NUMBER_PATTERN = re.compile(r"[+-]?\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?")
STRUCTURAL_LABELS = {
    "START OF TEC MAP",
    "END OF TEC MAP",
    "EPOCH OF CURRENT MAP",
    "LAT/LON1/LON2/DLON/H",
    "END OF HEADER",
    "END OF FILE",
    "START OF RMS MAP",
    "END OF RMS MAP",
}

COHORT_EXPECTED_COUNTS = {
    "ORIGINAL_TARGETS": 90,
    "STRICT_TARGETS": 88,
    "CONSERVATIVE_TARGETS": 87,
    "STRICT_PHYSICAL_CONTROLS": 19,
}

LEDGER_COMPONENT_FIELDS = {
    "ORIGINAL_TARGETS": "dependency_component_original_target",
    "STRICT_TARGETS": "dependency_component_strict_target",
    "CONSERVATIVE_TARGETS": "dependency_component_conservative_target",
    "STRICT_PHYSICAL_CONTROLS": "dependency_component_strict_control",
}

FEATURE_METRICS = (
    "p_vtec_max", "p_vtec_q95", "t_vtec_max", "t_vtec_q95",
    "p_vpos_max", "p_vpos_q95", "t_vpos_max", "t_vpos_q95",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"Naive UTC timestamp: {value!r}")
    return result.astimezone(timezone.utc)


def event_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def timestamp_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:00:00Z")


def median_and_mad_v004(values: list[float]) -> tuple[float, float]:
    """Exact Stage4B median/MAD: average the central pair when n is even."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median_and_mad_v004 requires at least one value")
    median = (
        ordered[n // 2]
        if n % 2 == 1
        else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
    )
    deviations = sorted(abs(value - median) for value in ordered)
    mad = (
        deviations[n // 2]
        if n % 2 == 1
        else 0.5 * (deviations[n // 2 - 1] + deviations[n // 2])
    )
    return median, max(1e-6, 1.4826 * mad)


def bilinear_vtec_v004(map_tuple: tuple[Any, ...], lat: float, lon: float) -> float:
    """Exact Stage4B/V004 bilinear interpolation and edge-clamping convention."""
    _, lat1, dlat, lon1, dlon, n_lats, n_lons, grid = map_tuple
    fi = (lat - lat1) / dlat
    fj = (lon - lon1) / dlon
    i0 = max(0, min(n_lats - 2, int(math.floor(fi))))
    j0 = max(0, min(n_lons - 2, int(math.floor(fj))))
    wy = max(0.0, min(1.0, fi - i0))
    wx = max(0.0, min(1.0, fj - j0))
    g = grid
    return (
        (1 - wy) * ((1 - wx) * g[i0][j0] + wx * g[i0][j0 + 1])
        + wy * ((1 - wx) * g[i0 + 1][j0] + wx * g[i0 + 1][j0 + 1])
    )


def unlzw_aligned(data: bytes) -> bytes:
    """Independent local copy of the verified Stage5B aligned .Z decoder."""
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Invalid .Z header")
    flags = data[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    if not 9 <= max_bits <= 16:
        raise ValueError(f"Invalid LZW max_bits: {max_bits}")

    pos, n_bytes, block_start = 3, len(data), 3
    bit_buf, bits_in_buf, code_size = 0, 0, 9
    clear_code = 256 if block_mode else -1
    next_code = 257 if block_mode else 256
    max_code = 1 << max_bits
    table = {i: bytes([i]) for i in range(256)}
    output = bytearray()
    previous_sequence = None

    while True:
        while bits_in_buf < code_size and pos < n_bytes:
            bit_buf |= data[pos] << bits_in_buf
            bits_in_buf += 8
            pos += 1
        if bits_in_buf < code_size:
            break

        code = bit_buf & ((1 << code_size) - 1)
        bit_buf >>= code_size
        bits_in_buf -= code_size

        if block_mode and code == clear_code:
            consumed = (pos - block_start) - (bits_in_buf // 8)
            remainder = consumed % code_size
            if remainder:
                pos += code_size - remainder
            block_start = pos
            bit_buf = bits_in_buf = 0
            table = {i: bytes([i]) for i in range(256)}
            code_size = 9
            next_code = 257
            previous_sequence = None
            continue

        if previous_sequence is None:
            if code not in table:
                raise ValueError(f"Invalid first LZW code: {code}")
            sequence = table[code]
            output.extend(sequence)
            previous_sequence = sequence
            continue

        sequence = (
            table[code]
            if code in table
            else previous_sequence + previous_sequence[:1]
        )
        output.extend(sequence)
        if next_code < max_code:
            table[next_code] = previous_sequence + sequence[:1]
            next_code += 1
            if next_code == (1 << code_size) and code_size < max_bits:
                code_size += 1
        previous_sequence = sequence

    return bytes(output)


def record_label(line: str) -> str:
    return line[60:].strip() if len(line) > 60 else ""


def parse_ionex_file(path: Path, requested_day: Any) -> tuple[dict[str, Any], list[tuple[Any, ...]]]:
    raw = path.read_bytes()
    if path.name.endswith(".Z"):
        decoded = unlzw_aligned(raw)
        suffix = ".Z"
    elif path.name.endswith(".gz"):
        decoded = gzip.decompress(raw)
        suffix = ".gz"
    else:
        raise ValueError(f"Unsupported IONEX suffix: {path.name}")

    text = decoded.decode("utf-8", errors="strict")
    lines = text.splitlines()

    lat1, lat2, dlat = 87.5, -87.5, -2.5
    lon1, lon2, dlon = -180.0, 180.0, 5.0
    exponent = -1
    header_end = False
    index = 0

    while index < len(lines):
        label = record_label(lines[index])
        if label == "END OF HEADER":
            header_end = True
            index += 1
            break
        if label == "LAT1 / LAT2 / DLAT":
            parts = lines[index][:60].split()
            if len(parts) != 3:
                raise ValueError("Malformed LAT1 / LAT2 / DLAT header")
            lat1, lat2, dlat = map(float, parts)
        elif label == "LON1 / LON2 / DLON":
            parts = lines[index][:60].split()
            if len(parts) != 3:
                raise ValueError("Malformed LON1 / LON2 / DLON header")
            lon1, lon2, dlon = map(float, parts)
        elif label == "EXPONENT":
            exponent = int(lines[index][:60].strip())
        index += 1

    if not header_end:
        raise ValueError("Missing END OF HEADER")
    if dlat == 0 or dlon == 0:
        raise ValueError("Zero grid increment")

    lat_steps = (lat2 - lat1) / dlat
    lon_steps = (lon2 - lon1) / dlon
    if abs(lat_steps - round(lat_steps)) > 1e-6:
        raise ValueError("Non-integral latitude grid dimensions")
    if abs(lon_steps - round(lon_steps)) > 1e-6:
        raise ValueError("Non-integral longitude grid dimensions")

    n_lats = int(round(lat_steps)) + 1
    n_lons = int(round(lon_steps)) + 1
    if not (2 <= n_lats <= 1000 and 2 <= n_lons <= 2000):
        raise ValueError(f"Implausible grid dimensions {n_lats} x {n_lons}")

    scale = 10.0 ** exponent
    maps: list[tuple[Any, ...]] = []
    map_starts = 0
    invalid_maps = 0
    nan_cells = 0
    total_cells = 0
    row_headers = 0
    data_lines = 0
    day_start = datetime.combine(requested_day, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    while index < len(lines):
        if record_label(lines[index]) != "START OF TEC MAP":
            index += 1
            continue

        map_starts += 1
        index += 1
        epoch = None
        grid: list[list[float]] = []
        map_bad = False
        ended = False

        while index < len(lines):
            label = record_label(lines[index])

            if label == "END OF TEC MAP":
                index += 1
                ended = True
                break

            if label == "EPOCH OF CURRENT MAP":
                parts = [int(x) for x in lines[index][:60].split()]
                if len(parts) < 6 or epoch is not None:
                    map_bad = True
                else:
                    if parts[3] == 24:
                        epoch = (
                            datetime(
                                parts[0], parts[1], parts[2], 0,
                                parts[4], parts[5], tzinfo=timezone.utc
                            ) + timedelta(days=1)
                        )
                    else:
                        epoch = datetime(
                            parts[0], parts[1], parts[2], parts[3],
                            parts[4], parts[5], tzinfo=timezone.utc
                        )
                index += 1
                continue

            if label == "LAT/LON1/LON2/DLON/H":
                numeric = NUMBER_PATTERN.findall(lines[index][:60])
                if len(numeric) != 5:
                    map_bad = True
                    index += 1
                    continue

                row_lat, row_lon1, row_lon2, row_dlon, row_height = (
                    float(value) for value in numeric
                )
                expected_lat = lat1 + len(grid) * dlat
                if (
                    abs(row_lat - expected_lat) > 0.02
                    or abs(row_lon1 - lon1) > 0.02
                    or abs(row_lon2 - lon2) > 0.02
                    or abs(row_dlon - dlon) > 0.02
                    or not math.isfinite(row_height)
                ):
                    map_bad = True

                row_headers += 1
                index += 1
                values: list[float] = []

                while len(values) < n_lons:
                    if index >= len(lines):
                        map_bad = True
                        break
                    data_line = lines[index]
                    if record_label(data_line) in STRUCTURAL_LABELS:
                        map_bad = True
                        break

                    line_values = []
                    for position in range(0, min(80, len(data_line)), 5):
                        token = data_line[position:position + 5].strip()
                        if not token:
                            continue
                        try:
                            value = int(token)
                        except ValueError:
                            map_bad = True
                            continue
                        if value == 9999:
                            values.append(float("nan"))
                            nan_cells += 1
                        else:
                            values.append(value * scale)
                        line_values.append(value)

                    expected_line_count = min(16, n_lons - len(values) + len(line_values))
                    if not line_values or len(line_values) > 16:
                        map_bad = True
                    elif len(line_values) != expected_line_count:
                        map_bad = True

                    total_cells += len(line_values)
                    data_lines += 1
                    index += 1

                if len(values) != n_lons:
                    map_bad = True
                grid.append(values[:n_lons])
                continue

            index += 1

        if not ended or epoch is None or len(grid) != n_lats:
            map_bad = True
        if any(len(row) != n_lons for row in grid):
            map_bad = True
        if epoch is not None and not (day_start <= epoch <= day_end):
            map_bad = True

        if map_bad:
            invalid_maps += 1
        else:
            maps.append((epoch, lat1, dlat, lon1, dlon, n_lats, n_lons, grid))

    if map_starts == 0:
        raise ValueError("No TEC map blocks")
    if invalid_maps:
        raise ValueError(f"{invalid_maps} invalid TEC map block(s)")
    if not maps:
        raise ValueError("No structurally valid TEC maps")

    epochs = [item[0] for item in maps]
    if epochs != sorted(epochs):
        raise ValueError("TEC map epochs are not ordered")
    if len(set(epochs)) != len(epochs):
        raise ValueError("Duplicate TEC map epochs within daily file")

    metadata = {
        "file_name": path.name,
        "format": suffix,
        "compressed_bytes": len(raw),
        "compressed_sha256": sha256_bytes(raw),
        "decompressed_bytes": len(decoded),
        "grid_lat1": lat1,
        "grid_lat2": lat2,
        "grid_dlat": dlat,
        "grid_lon1": lon1,
        "grid_lon2": lon2,
        "grid_dlon": dlon,
        "n_lats": n_lats,
        "n_lons": n_lons,
        "exponent": exponent,
        "scale": scale,
        "map_count": len(maps),
        "invalid_maps": invalid_maps,
        "nan_cells": nan_cells,
        "grid_cells_parsed": total_cells,
        "row_headers_checked": row_headers,
        "data_lines_checked": data_lines,
        "first_epoch": epochs[0].isoformat(),
        "last_epoch": epochs[-1].isoformat(),
    }
    return metadata, maps


def select_ionex_file(day: datetime.date) -> tuple[Path, str]:
    year = day.year
    doy = day.timetuple().tm_yday
    yy = year % 100
    candidates = (
        (IONEX_DIR / f"CODG{doy:03d}0.{yy:02d}I.Z", ".Z"),
        (IONEX_DIR / f"COD0OPSFIN_{year}{doy:03d}0000_01D_01H_GIM.INX.gz", ".gz"),
    )
    for path, suffix in candidates:
        if path.is_file() and path.stat().st_size > 2000:
            return path, suffix
    raise FileNotFoundError(f"No valid IONEX candidate for {day.isoformat()}")


def parse_omni(required_keys: set[str]) -> tuple[dict[str, tuple[float | None, float | None, float | None]], list[dict[str, Any]], dict[str, int]]:
    records: dict[str, tuple[float | None, float | None, float | None]] = {}
    inventory = []
    duplicates = 0
    short_rows = 0
    malformed_rows = 0
    total_source_rows = 0
    required_matches = 0

    files = sorted(OMNI_DIR.glob("omni2_*.dat"))
    if not files:
        raise FileNotFoundError(f"No omni2_*.dat files in {OMNI_DIR}")

    for path in files:
        file_hash = sha256_file(path)
        row_count = 0
        file_short = 0
        file_malformed = 0
        file_required_matches = 0

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                total_source_rows += 1
                parts = line.split()
                if len(parts) < 51:
                    short_rows += 1
                    file_short += 1
                    continue
                try:
                    year = int(parts[0])
                    doy = int(parts[1])
                    hour = int(parts[2])
                    kp10 = int(parts[38])
                    dst = float(parts[40])
                    f107 = float(parts[50])
                    timestamp = (
                        datetime(year, 1, 1, tzinfo=timezone.utc)
                        + timedelta(days=doy - 1, hours=hour)
                    )
                except (ValueError, OverflowError):
                    malformed_rows += 1
                    file_malformed += 1
                    continue

                row_count += 1
                key = timestamp_key(timestamp)
                if key not in required_keys:
                    continue
                if key in records:
                    duplicates += 1
                kp = kp10 / 10.0 if 0 <= kp10 <= 90 else None
                dst_value = dst if -1000 <= dst <= 500 else None
                f107_value = f107 if 50 <= f107 <= 400 else None
                records[key] = (kp, dst_value, f107_value)
                required_matches += 1
                file_required_matches += 1

        inventory.append({
            "file_name": path.name,
            "bytes": path.stat().st_size,
            "sha256": file_hash,
            "parsed_data_rows": row_count,
            "short_rows": file_short,
            "malformed_rows": file_malformed,
            "required_hour_records": file_required_matches,
        })

    missing = required_keys - set(records)
    diagnostics = {
        "files": len(files),
        "source_rows": total_source_rows,
        "short_rows": short_rows,
        "malformed_rows": malformed_rows,
        "required_hour_records": required_matches,
        "unique_required_hours_found": len(records),
        "required_hour_duplicates": duplicates,
        "required_hour_missing": len(missing),
    }
    if missing:
        examples = sorted(missing)[:10]
        raise ValueError(f"OMNI missing {len(missing)} required hours; examples={examples}")
    if duplicates:
        raise ValueError(f"OMNI has {duplicates} duplicate records on required hours")
    return records, inventory, diagnostics


def median_q95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(0.95 * (len(ordered) - 1))]


def window_name(offset: int) -> str:
    if WIN_B0[0] <= offset < WIN_B0[1]:
        return "B0"
    if WIN_W0[0] <= offset < WIN_W0[1]:
        return "W0"
    if WIN_B1[0] <= offset < WIN_B1[1]:
        return "B1"
    if WIN_W1[0] <= offset < WIN_W1[1]:
        return "W1"
    if WIN_GUARD[0] <= offset < WIN_GUARD[1]:
        return "GUARD"
    if offset == 0:
        return "EVENT_HOUR"
    return "OUTSIDE"


def score_window(
    timeline: list[dict[str, Any]],
    baseline_range: tuple[int, int],
    target_range: tuple[int, int],
    baseline_name: str,
    target_name: str,
    baseline_stats_rows: list[dict[str, Any]],
    event_id: str,
) -> tuple[list[float], dict[str, Any]]:
    baseline_pool = [
        row["vtec_adjusted"]
        for row in timeline
        if baseline_range[0] <= row["offset_h"] < baseline_range[1]
        and row["vtec_adjusted"] is not None
        and row["quiet"]
    ]

    diagnostics = {
        "event_id": event_id,
        "baseline_window": baseline_name,
        "target_window": target_name,
        "baseline_pool_n": len(baseline_pool),
        "baseline_status": "PASS" if len(baseline_pool) >= 20 else "FAILED_BASELINE_POOL_LT20",
        "pooled_median": None,
        "pooled_scale": None,
        "target_quiet_score_n": 0,
    }

    if len(baseline_pool) < 20:
        for hour in range(24):
            hour_values = [
                row["vtec_adjusted"]
                for row in timeline
                if baseline_range[0] <= row["offset_h"] < baseline_range[1]
                and row["utc_hour"] == hour
                and row["vtec_adjusted"] is not None
                and row["quiet"]
            ]
            baseline_stats_rows.append({
                "event_id": event_id,
                "baseline_window": baseline_name,
                "hour_of_day_utc": hour,
                "pooled_n": len(baseline_pool),
                "hour_of_day_n": len(hour_values),
                "pooled_median": None,
                "pooled_mad_scaled": None,
                "hour_median": None,
                "hour_mad_scaled": None,
                "hour_of_day_fallback_used": True,
                "baseline_status": "FAILED_BASELINE_POOL_LT20",
            })
        return [], diagnostics

    pooled_median, pooled_scale = median_and_mad_v004(baseline_pool)
    diagnostics["pooled_median"] = pooled_median
    diagnostics["pooled_scale"] = pooled_scale

    hourly_calibration: dict[int, tuple[float, float]] = {}
    for hour in range(24):
        hour_values = [
            row["vtec_adjusted"]
            for row in timeline
            if baseline_range[0] <= row["offset_h"] < baseline_range[1]
            and row["utc_hour"] == hour
            and row["vtec_adjusted"] is not None
            and row["quiet"]
        ]
        fallback = len(hour_values) < 2
        if fallback:
            hourly_calibration[hour] = (pooled_median, pooled_scale)
            hour_median, hour_scale = pooled_median, pooled_scale
        else:
            hour_median, hour_scale = median_and_mad_v004(hour_values)
            hourly_calibration[hour] = (hour_median, hour_scale)

        baseline_stats_rows.append({
            "event_id": event_id,
            "baseline_window": baseline_name,
            "hour_of_day_utc": hour,
            "pooled_n": len(baseline_pool),
            "hour_of_day_n": len(hour_values),
            "pooled_median": pooled_median,
            "pooled_mad_scaled": pooled_scale,
            "hour_median": hour_median,
            "hour_mad_scaled": hour_scale,
            "hour_of_day_fallback_used": fallback,
            "baseline_status": "PASS",
        })

    scores = []
    for row in timeline:
        if (
            target_range[0] <= row["offset_h"] < target_range[1]
            and row["vtec_adjusted"] is not None
            and row["quiet"]
        ):
            center, scale = hourly_calibration[row["utc_hour"]]
            z_score = (row["vtec_adjusted"] - center) / scale
            scores.append(abs(z_score))

    diagnostics["target_quiet_score_n"] = len(scores)
    return scores, diagnostics


def csv_write(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> int:
    if fieldnames is None:
        if rows:
            fieldnames = list(rows[0].keys())
        else:
            raise ValueError(f"Cannot infer CSV columns for empty output {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def verify_inputs() -> dict[str, str]:
    paths = {
        "s4b": S4B_PATH,
        "s1d": S1D_PATH,
        "v004_features": V004_FEATURES_PATH,
        "v004_script": V004_SCRIPT_PATH,
        "stage4b_script": STAGE4B_SCRIPT_PATH,
        "stage5b_script": STAGE5B_SCRIPT_PATH,
        "ledger": LEDGER_PATH,
        "membership": MEMBERSHIP_PATH,
        "summary": SUMMARY_PATH,
        "tcwv_manifest": TCWV_MANIFEST_PATH,
        **PROTOCOL_PATHS,
    }
    verified = {}
    for key, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        expected = EXPECTED_INPUT_SHA256[key]
        if actual != expected:
            raise ValueError(
                f"Protected input hash mismatch for {key}: "
                f"expected {expected}, observed {actual}"
            )
        verified[key] = actual
    if not IONEX_DIR.is_dir():
        raise FileNotFoundError(IONEX_DIR)
    if not OMNI_DIR.is_dir():
        raise FileNotFoundError(OMNI_DIR)
    return verified


def load_and_validate_cohorts() -> tuple[
    list[dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, set[str]],
    list[dict[str, str]],
    dict[str, Any],
]:
    s4b = read_csv(S4B_PATH)
    s1d_rows = read_csv(S1D_PATH)
    v004_rows = read_csv(V004_FEATURES_PATH)
    ledger_rows = read_csv(LEDGER_PATH)
    membership_rows = read_csv(MEMBERSHIP_PATH)
    summary_rows = read_csv(SUMMARY_PATH)

    def unique_index(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
        index: dict[str, dict[str, str]] = {}
        for row in rows:
            event_id = row["event_id"].strip()
            if not event_id or event_id in index:
                raise ValueError(f"{label} has blank or duplicate event_id {event_id!r}")
            index[event_id] = row
        return index

    s4b_index = unique_index(s4b, "Stage4B")
    s1d_index = unique_index(s1d_rows, "Stage1D")
    v004_index = unique_index(v004_rows, "V004 features")
    ledger_index = unique_index(ledger_rows, "TCWV ledger")

    s4b_ids = set(s4b_index)
    if len(s4b_ids) != 111:
        raise ValueError(f"Expected 111 Stage4B events, got {len(s4b_ids)}")
    for name, index in (
        ("Stage1D", s1d_index),
        ("V004", v004_index),
        ("TCWV ledger", ledger_index),
    ):
        missing = s4b_ids - set(index)
        if missing:
            raise ValueError(f"{name} missing Stage4B event IDs: {sorted(missing)}")
    if set(v004_index) != s4b_ids or set(ledger_index) != s4b_ids:
        raise ValueError("V004 / TCWV ledger event populations differ from Stage4B")

    for event_id in s4b_ids:
        event = s4b_index[event_id]
        catalogue = s1d_index[event_id]
        vref = v004_index[event_id]
        ledger = ledger_index[event_id]

        t_s4b = parse_utc(event["origin_time_utc"])
        t_s1d = parse_utc(catalogue["origin_time_utc"])
        t_v004 = parse_utc(vref["origin_time_utc"])
        t_ledger = parse_utc(ledger["origin_time_utc"])
        if not (t_s4b == t_s1d == t_v004):
            raise ValueError(f"{event_id}: Stage4B/Stage1D/V004 UTC timestamps differ")
        if t_s4b.replace(microsecond=0) != t_ledger.replace(microsecond=0):
            raise ValueError(f"{event_id}: TCWV ledger timestamp differs by >=1 second")

        role_values = (
            event["stage1d_analysis_role_v001"].strip(),
            catalogue["stage1d_analysis_role_v001"].strip(),
            vref["role"].strip(),
            ledger["role"].strip(),
        )
        if len(set(role_values)) != 1:
            raise ValueError(f"{event_id}: role mismatch {role_values}")

        lat = float(catalogue["latitude_deg"])
        lon = float(catalogue["longitude_deg"])
        if not math.isfinite(lat) or not math.isfinite(lon):
            raise ValueError(f"{event_id}: non-finite epicentre")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"{event_id}: invalid epicentre coordinates")
        if not (-87.5 <= lat <= 87.5 and -180 <= lon <= 180):
            raise ValueError(f"{event_id}: epicentre outside IONEX grid")

    cohorts: dict[str, set[str]] = defaultdict(set)
    membership_lookup: dict[tuple[str, str], dict[str, str]] = {}
    component_members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in membership_rows:
        cohort = row["cohort"].strip()
        event_id = row["event_id"].strip()
        key = (cohort, event_id)
        if key in membership_lookup:
            raise ValueError(f"Duplicate membership row {key}")
        if event_id not in s4b_ids:
            raise ValueError(f"Membership event outside Stage4B: {key}")
        membership_lookup[key] = row
        cohorts[cohort].add(event_id)
        component_members[(cohort, row["component_id"].strip())].append(event_id)

    expected_roles = {
        "ORIGINAL_TARGETS": "PRIMARY_SHALLOW_TARGET",
        "STRICT_TARGETS": "PRIMARY_SHALLOW_TARGET",
        "CONSERVATIVE_TARGETS": "PRIMARY_SHALLOW_TARGET",
        "STRICT_PHYSICAL_CONTROLS": "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE",
    }
    for cohort, expected_count in COHORT_EXPECTED_COUNTS.items():
        ids = cohorts.get(cohort, set())
        if len(ids) != expected_count:
            raise ValueError(f"{cohort} expected {expected_count}, found {len(ids)}")
        for event_id in ids:
            if s4b_index[event_id]["stage1d_analysis_role_v001"] != expected_roles[cohort]:
                raise ValueError(f"{cohort}: unexpected role for {event_id}")

    targets = {
        eid for eid, row in s4b_index.items()
        if row["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET"
    }
    controls = {
        eid for eid, row in s4b_index.items()
        if row["stage1d_analysis_role_v001"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"
    }
    strict_targets_from_ledger = {
        eid for eid, row in ledger_index.items()
        if row["role"] == "PRIMARY_SHALLOW_TARGET"
        and row["strict_m2c_feature_eligible"].strip().lower() == "true"
    }
    strict_controls_from_ledger = {
        eid for eid, row in ledger_index.items()
        if row["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"
        and row["strict_m2c_feature_eligible"].strip().lower() == "true"
    }
    conservative_from_ledger = {
        eid for eid, row in ledger_index.items()
        if row["role"] == "PRIMARY_SHALLOW_TARGET"
        and row["dependency_component_conservative_target"].strip()
    }
    if cohorts["ORIGINAL_TARGETS"] != targets:
        raise ValueError("ORIGINAL_TARGETS membership differs from Stage4B shallow targets")
    if cohorts["STRICT_TARGETS"] != strict_targets_from_ledger:
        raise ValueError("STRICT_TARGETS membership differs from TCWV ledger eligibility")
    if cohorts["CONSERVATIVE_TARGETS"] != conservative_from_ledger:
        raise ValueError("CONSERVATIVE_TARGETS membership differs from TCWV ledger")
    if cohorts["STRICT_PHYSICAL_CONTROLS"] != strict_controls_from_ledger:
        raise ValueError("STRICT_PHYSICAL_CONTROLS differs from TCWV ledger eligibility")
    if not cohorts["CONSERVATIVE_TARGETS"].issubset(cohorts["STRICT_TARGETS"]):
        raise ValueError("Conservative target cohort is not a subset of strict targets")

    component_field_mismatches = []
    for cohort, field in LEDGER_COMPONENT_FIELDS.items():
        for event_id in cohorts[cohort]:
            member = membership_lookup[(cohort, event_id)]
            declared = member["component_id"].strip()
            ledger_component = ledger_index[event_id][field].strip()
            if declared != ledger_component:
                component_field_mismatches.append((cohort, event_id, declared, ledger_component))
    if component_field_mismatches:
        raise ValueError(f"Membership/ledger component mismatch: {component_field_mismatches[:10]}")

    size_mismatches = []
    component_size_distribution = {}
    component_counts = {}
    for cohort in COHORT_EXPECTED_COUNTS:
        sizes = Counter(len(members) for (coh, _), members in component_members.items() if coh == cohort)
        component_size_distribution[cohort] = {
            str(size): count for size, count in sorted(sizes.items())
        }
        component_counts[cohort] = sum(sizes.values())
        for (coh, component_id), members in component_members.items():
            if coh != cohort:
                continue
            observed_size = len(members)
            declared_sizes = {
                int(membership_lookup[(cohort, eid)]["component_size"])
                for eid in members
            }
            if declared_sizes != {observed_size}:
                size_mismatches.append((cohort, component_id, observed_size, declared_sizes))
    if size_mismatches:
        raise ValueError(f"Frozen component-size mismatch: {size_mismatches[:10]}")

    summary_index = {row["cohort"]: row for row in summary_rows}
    for cohort, expected_count in COHORT_EXPECTED_COUNTS.items():
        summary = summary_index.get(cohort)
        if summary is None:
            raise ValueError(f"Missing dependency summary row {cohort}")
        if int(summary["event_count"]) != expected_count:
            raise ValueError(f"Summary event count mismatch for {cohort}")
        if int(summary["component_count"]) != component_counts[cohort]:
            raise ValueError(f"Summary component count mismatch for {cohort}")
        if json.loads(summary["component_size_distribution"]) != json.loads(
            json.dumps(component_size_distribution[cohort])
        ):
            # JSON object key order is immaterial; values must be exact.
            if {
                str(k): int(v)
                for k, v in json.loads(summary["component_size_distribution"]).items()
            } != {
                str(k): int(v) for k, v in component_size_distribution[cohort].items()
            }:
                raise ValueError(f"Summary component-size distribution mismatch for {cohort}")

    membership_out = []
    for row in membership_rows:
        event_id = row["event_id"].strip()
        membership_out.append({
            "cohort": row["cohort"],
            "event_id": event_id,
            "station_id": row["station_id"],
            "origin_time_utc": row["origin_time_utc"],
            "component_id": row["component_id"],
            "component_size": row["component_size"],
        })

    cohort_summary = {
        "counts": {key: len(cohorts[key]) for key in COHORT_EXPECTED_COUNTS},
        "component_counts": component_counts,
        "component_size_distributions": component_size_distribution,
        "strict_target_exclusions": sorted(targets - cohorts["STRICT_TARGETS"]),
        "conservative_target_exclusions": sorted(targets - cohorts["CONSERVATIVE_TARGETS"]),
        "strict_control_exclusions": sorted(controls - cohorts["STRICT_PHYSICAL_CONTROLS"]),
    }
    return s4b, s1d_index, v004_index, dict(cohorts), membership_out, cohort_summary


def run_unit_tests() -> list[dict[str, Any]]:
    tests = []

    def record(name: str, passed: bool, detail: str) -> None:
        tests.append({"test": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    window_sets = [
        set(range(*WIN_B0)),
        set(range(*WIN_W0)),
        set(range(*WIN_B1)),
        set(range(*WIN_W1)),
        set(range(*WIN_GUARD)),
    ]
    pairwise_disjoint = all(
        not (window_sets[i] & window_sets[j])
        for i in range(len(window_sets))
        for j in range(i + 1, len(window_sets))
    )
    record(
        "window_lengths_and_disjointness",
        (
            len(window_sets[0]) == 288
            and len(window_sets[1]) == 240
            and len(window_sets[2]) == 288
            and len(window_sets[3]) == 240
            and len(window_sets[4]) == 24
            and pairwise_disjoint
        ),
        "B0=288, W0=240, B1=288, W1=240, guard=24 hours; pairwise disjoint",
    )

    median, scale = median_and_mad_v004([1.0, 2.0, 3.0, 100.0])
    odd_median, odd_scale = median_and_mad_v004([1.0, 2.0, 3.0])
    record(
        "stage4b_even_sample_median_and_mad",
        abs(median - 2.5) < 1e-12 and abs(scale - 1.4826) < 1e-12,
        f"even_n_median={median}; even_n_scaled_MAD={scale}",
    )
    record(
        "stage4b_odd_sample_median_and_mad",
        abs(odd_median - 2.0) < 1e-12 and abs(odd_scale - 1.4826) < 1e-12,
        f"odd_n_median={odd_median}; odd_n_scaled_MAD={odd_scale}",
    )

    toy_grid = [[0.0, 10.0], [20.0, 30.0]]
    toy_tuple = (datetime(2000, 1, 1, tzinfo=timezone.utc), 0.0, 1.0, 0.0, 1.0, 2, 2, toy_grid)
    interpolated = bilinear_vtec_v004(toy_tuple, 0.5, 0.5)
    record(
        "bilinear_interpolation_center",
        abs(interpolated - 15.0) < 1e-12,
        f"center interpolation={interpolated}",
    )

    record(
        "q95_order_statistic",
        median_q95(list(range(20))) == 18,
        f"q95 for 0..19={median_q95(list(range(20)))}",
    )

    return tests


def main() -> None:
    print("===== LAIC-GUARD INDEPENDENT M3 BUILDER v002 =====", flush=True)
    print("Repository root:", ROOT, flush=True)
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"Final output already exists; refusing overwrite: {OUTPUT_DIR}")
    if BUILDING_DIR.exists():
        raise FileExistsError(
            f"Previous incomplete build directory exists; inspect it before proceeding: {BUILDING_DIR}"
        )

    verified_input_hashes = verify_inputs()
    print("Protected source hashes: PASS", flush=True)

    unit_tests = run_unit_tests()
    failed_tests = [row for row in unit_tests if row["status"] != "PASS"]
    if failed_tests:
        raise AssertionError(f"Unit tests failed: {failed_tests}")
    print(f"Local unit tests: {len(unit_tests)} PASS", flush=True)

    s4b_rows, s1d_index, v004_index, cohort_sets, membership_out, cohort_summary = (
        load_and_validate_cohorts()
    )
    print(
        "Event/cohort source validation: PASS | "
        f"events={len(s4b_rows)} | strict={cohort_summary['counts']['STRICT_TARGETS']} | "
        f"conservative={cohort_summary['counts']['CONSERVATIVE_TARGETS']}",
        flush=True,
    )

    events = []
    for source in s4b_rows:
        event_id = source["event_id"].strip()
        catalogue = s1d_index[event_id]
        origin = parse_utc(source["origin_time_utc"])
        events.append({
            "event_id": event_id,
            "origin_time_utc": origin,
            "event_hour_utc": event_hour(origin),
            "latitude_deg": float(catalogue["latitude_deg"]),
            "longitude_deg": float(catalogue["longitude_deg"]),
            "role": source["stage1d_analysis_role_v001"].strip(),
            "station_id": source["verified_gnss_station_id"].strip().upper(),
            "region": source["frozen_macro_region_v001"].strip(),
            "source_class": source["stage1c4_final_source_class_v001"].strip(),
            "magnitude": float(source["magnitude"]),
            "depth_km": float(source["depth_km"]),
        })

    # Required IONEX date inventory: exactly the V004 calendar-day range -45..+5.
    date_to_events: dict[datetime.date, list[dict[str, Any]]] = defaultdict(list)
    required_omni_keys: set[str] = set()
    for event in events:
        for day_offset in range(-45, 6):
            requested_day = (event["origin_time_utc"] + timedelta(days=day_offset)).date()
            date_to_events[requested_day].append(event)
        for hour_offset in TIMELINE_OFFSETS:
            timestamp = event["event_hour_utc"] + timedelta(hours=hour_offset)
            required_omni_keys.add(timestamp_key(timestamp))

    print(
        "IONEX required unique dates:", len(date_to_events),
        "| event-date requests:", sum(len(v) for v in date_to_events.values()),
        flush=True,
    )
    print("OMNI required unique hours:", len(required_omni_keys), flush=True)

    omni_records, omni_inventory, omni_diagnostics = parse_omni(required_omni_keys)
    print(
        "OMNI coverage: PASS | found="
        f"{omni_diagnostics['unique_required_hours_found']}/"
        f"{len(required_omni_keys)} | files={omni_diagnostics['files']}",
        flush=True,
    )

    # Date-major extraction: each unique daily IONEX file is read/decompressed once.
    vtec_by_event: dict[str, dict[str, tuple[float, str]]] = {
        event["event_id"]: {} for event in events
    }
    event_day_audit: list[dict[str, Any]] = []
    ionex_inventory: list[dict[str, Any]] = []
    total_map_blocks = 0
    total_grid_cells = 0
    total_nan_cells = 0
    duplicate_hour_assignments = 0
    date_count = len(date_to_events)

    for date_index, requested_day in enumerate(sorted(date_to_events), start=1):
        path, selected_suffix = select_ionex_file(requested_day)
        metadata, maps = parse_ionex_file(path, requested_day)
        if metadata["format"] != selected_suffix:
            raise ValueError(f"{requested_day}: selected suffix mismatch")
        if (metadata["n_lats"], metadata["n_lons"], metadata["exponent"]) != (71, 73, -1):
            raise ValueError(
                f"{requested_day}: unexpected grid/exponent "
                f"{metadata['n_lats']}x{metadata['n_lons']} exp {metadata['exponent']}"
            )

        ionex_inventory.append({
            "requested_date_utc": requested_day.isoformat(),
            **metadata,
        })
        total_map_blocks += metadata["map_count"]
        total_grid_cells += metadata["grid_cells_parsed"]
        total_nan_cells += metadata["nan_cells"]

        active_events = date_to_events[requested_day]
        for event in active_events:
            event_hour_utc = event["event_hour_utc"]
            assigned = 0
            overwritten = 0
            for map_tuple in maps:
                map_epoch = map_tuple[0]
                map_hour = event_hour(map_epoch)
                delta_hours = (map_hour - event_hour_utc).total_seconds() / 3600.0
                if not delta_hours.is_integer():
                    raise ValueError(
                        f"{event['event_id']}: non-integral IONEX hour offset {delta_hours}"
                    )
                offset = int(delta_hours)
                if not (-1080 <= offset <= 0):
                    continue

                value = bilinear_vtec_v004(
                    map_tuple, event["latitude_deg"], event["longitude_deg"]
                )
                if math.isnan(value):
                    continue
                key = timestamp_key(map_epoch)
                if key in vtec_by_event[event["event_id"]]:
                    overwritten += 1
                    duplicate_hour_assignments += 1
                # Same overwrite order as V004: daily files are visited chronologically.
                vtec_by_event[event["event_id"]][key] = (value, path.name)
                assigned += 1

            event_day_audit.append({
                "event_id": event["event_id"],
                "requested_date_utc": requested_day.isoformat(),
                "selected_file": path.name,
                "selected_format": selected_suffix,
                "compressed_bytes": metadata["compressed_bytes"],
                "compressed_sha256": metadata["compressed_sha256"],
                "tec_map_count_in_file": metadata["map_count"],
                "in_timeline_map_assignments": assigned,
                "overwritten_hour_assignments": overwritten,
                "parse_status": "PASS",
            })

        if date_index % 250 == 0 or date_index == date_count:
            print(
                f"IONEX extraction progress {date_index}/{date_count} | "
                f"maps={total_map_blocks} | "
                f"date-event rows={len(event_day_audit)}",
                flush=True,
            )

    expected_date_requests = 111 * 51
    if len(ionex_inventory) != 2959:
        raise ValueError(f"Expected 2959 unique IONEX files, got {len(ionex_inventory)}")
    if len(event_day_audit) != expected_date_requests:
        raise ValueError(
            f"Expected {expected_date_requests} event-date audit rows, "
            f"got {len(event_day_audit)}"
        )
    if total_nan_cells:
        raise ValueError(f"IONEX parser found {total_nan_cells} 9999 cells in required maps")

    # Construct event-hour timelines, solar-flux adjustment, and M3 scores.
    hourly_output: list[dict[str, Any]] = []
    calibration_output: list[dict[str, Any]] = []
    baseline_stats_output: list[dict[str, Any]] = []
    feature_output: list[dict[str, Any]] = []
    eligibility_output: list[dict[str, Any]] = []
    v004_check_output: list[dict[str, Any]] = []
    coverage_output: list[dict[str, Any]] = []

    for event_index, event in enumerate(events, start=1):
        event_id = event["event_id"]
        timeline: list[dict[str, Any]] = []

        for offset in TIMELINE_OFFSETS:
            timestamp = event["event_hour_utc"] + timedelta(hours=offset)
            key = timestamp_key(timestamp)
            kp, dst, f107 = omni_records.get(key, (None, None, None))
            vtec_entry = vtec_by_event[event_id].get(key)
            raw_vtec = vtec_entry[0] if vtec_entry is not None else None
            source_file = vtec_entry[1] if vtec_entry is not None else ""
            quiet = (
                kp is not None
                and dst is not None
                and kp < 3.0
                and dst > -30.0
            )
            timeline.append({
                "offset_h": offset,
                "timestamp_utc": key,
                "utc_hour": timestamp.hour,
                "window": window_name(offset),
                "kp": kp,
                "dst": dst,
                "f107": f107,
                "quiet": quiet,
                "vtec_raw": raw_vtec,
                "vtec_source_file": source_file,
                "vtec_adjusted": None,
            })

        fit_points = [
            (row["f107"], row["vtec_raw"])
            for row in timeline
            if (
                (WIN_B0[0] <= row["offset_h"] < WIN_B0[1])
                or (WIN_B1[0] <= row["offset_h"] < WIN_B1[1])
            )
            and row["quiet"]
            and row["f107"]
            and row["vtec_raw"]
        ]

        fit_n = len(fit_points)
        fit_mx = fit_my = fit_sxx = fit_slope = None
        if fit_n >= 48:
            fit_mx = sum(point[0] for point in fit_points) / fit_n
            fit_my = sum(point[1] for point in fit_points) / fit_n
            fit_sxx = sum((point[0] - fit_mx) ** 2 for point in fit_points)
            if fit_sxx > 1e-6:
                fit_slope = (
                    sum(
                        (point[0] - fit_mx) * (point[1] - fit_my)
                        for point in fit_points
                    ) / fit_sxx
                )
                fit_status = "FIT"
            else:
                fit_slope = 0.0
                fit_status = "ZERO_SLOPE_PREDICTOR_VARIANCE"
        else:
            fit_mx = 0.0
            fit_slope = 0.0
            fit_status = "ZERO_SLOPE_INSUFFICIENT_POINTS"

        for row in timeline:
            if row["vtec_raw"] is not None and row["f107"] is not None:
                row["vtec_adjusted"] = (
                    row["vtec_raw"] - fit_slope * (row["f107"] - fit_mx)
                )
            else:
                row["vtec_adjusted"] = row["vtec_raw"]

        p_scores, p_baseline = score_window(
            timeline, WIN_B0, WIN_W0, "B0", "W0",
            baseline_stats_output, event_id,
        )
        t_scores, t_baseline = score_window(
            timeline, WIN_B1, WIN_W1, "B1", "W1",
            baseline_stats_output, event_id,
        )

        # The positive-only diagnostic is calculated with the same baseline
        # calibration, preserving the V004 signed-positive form.
        def positive_scores(
            base_range: tuple[int, int],
            target_range: tuple[int, int],
        ) -> list[float]:
            pool = [
                row["vtec_adjusted"] for row in timeline
                if base_range[0] <= row["offset_h"] < base_range[1]
                and row["vtec_adjusted"] is not None and row["quiet"]
            ]
            if len(pool) < 20:
                return []
            pooled_median, pooled_scale = median_and_mad_v004(pool)
            calibration = {}
            for hour in range(24):
                subset = [
                    row["vtec_adjusted"] for row in timeline
                    if base_range[0] <= row["offset_h"] < base_range[1]
                    and row["utc_hour"] == hour
                    and row["vtec_adjusted"] is not None and row["quiet"]
                ]
                calibration[hour] = (
                    median_and_mad_v004(subset) if len(subset) >= 2
                    else (pooled_median, pooled_scale)
                )
            return [
                max(
                    0.0,
                    (row["vtec_adjusted"] - calibration[row["utc_hour"]][0])
                    / calibration[row["utc_hour"]][1],
                )
                for row in timeline
                if target_range[0] <= row["offset_h"] < target_range[1]
                and row["vtec_adjusted"] is not None and row["quiet"]
            ]

        p_positive = positive_scores(WIN_B0, WIN_W0)
        t_positive = positive_scores(WIN_B1, WIN_W1)

        p_eligible = (
            p_baseline["baseline_pool_n"] >= 20 and len(p_scores) >= 12
        )
        t_eligible = (
            t_baseline["baseline_pool_n"] >= 20 and len(t_scores) >= 12
        )
        m3_eligible = p_eligible and t_eligible

        if m3_eligible:
            m3_status = "M3_FEATURE_ELIGIBLE"
        else:
            reasons = []
            if p_baseline["baseline_pool_n"] < 20:
                reasons.append("B0_QUIET_VTEC_BASELINE_POOL_LT20")
            if t_baseline["baseline_pool_n"] < 20:
                reasons.append("B1_QUIET_VTEC_BASELINE_POOL_LT20")
            if len(p_scores) < 12:
                reasons.append("W0_QUIET_VTEC_SCORES_LT12")
            if len(t_scores) < 12:
                reasons.append("W1_QUIET_VTEC_SCORES_LT12")
            m3_status = "M3_FEATURE_INELIGIBLE:" + ";".join(reasons)

        def metric(values: list[float], func: str) -> float | None:
            if not values:
                return None
            return max(values) if func == "max" else median_q95(values)

        feature_row = {
            "event_id": event_id,
            "origin_time_utc": event["origin_time_utc"].isoformat().replace("+00:00", "Z"),
            "event_hour_utc": event["event_hour_utc"].isoformat().replace("+00:00", "Z"),
            "latitude_deg": event["latitude_deg"],
            "longitude_deg": event["longitude_deg"],
            "station_id": event["station_id"],
            "region": event["region"],
            "role": event["role"],
            "source_class": event["source_class"],
            "magnitude": event["magnitude"],
            "depth_km": event["depth_km"],
            "m3_feature_status": m3_status,
            "p_vtec_score_n": len(p_scores),
            "t_vtec_score_n": len(t_scores),
            "p_vtec_baseline_n": p_baseline["baseline_pool_n"],
            "t_vtec_baseline_n": t_baseline["baseline_pool_n"],
            "p_vtec_max": metric(p_scores, "max"),
            "p_vtec_q95": metric(p_scores, "q95"),
            "t_vtec_max": metric(t_scores, "max"),
            "t_vtec_q95": metric(t_scores, "q95"),
            "p_vpos_max": metric(p_positive, "max"),
            "p_vpos_q95": metric(p_positive, "q95"),
            "t_vpos_max": metric(t_positive, "max"),
            "t_vpos_q95": metric(t_positive, "q95"),
        }
        feature_output.append(feature_row)

        calibration_output.append({
            "event_id": event_id,
            "origin_time_utc": feature_row["origin_time_utc"],
            "quiet_baseline_f107_vtec_pairs": fit_n,
            "f107_mean": fit_mx,
            "vtec_mean": fit_my,
            "f107_sxx": fit_sxx,
            "f107_slope": fit_slope,
            "fit_status": fit_status,
            "B0_quiet_vtec_baseline_n": p_baseline["baseline_pool_n"],
            "W0_quiet_vtec_score_n": len(p_scores),
            "B1_quiet_vtec_baseline_n": t_baseline["baseline_pool_n"],
            "W1_quiet_vtec_score_n": len(t_scores),
        })

        for row in timeline:
            hourly_output.append({
                "event_id": event_id,
                "origin_time_utc": feature_row["origin_time_utc"],
                "event_hour_utc": feature_row["event_hour_utc"],
                "latitude_deg": event["latitude_deg"],
                "longitude_deg": event["longitude_deg"],
                "offset_h": row["offset_h"],
                "timestamp_utc": row["timestamp_utc"],
                "window": row["window"],
                "utc_hour": row["utc_hour"],
                "vtec_raw": row["vtec_raw"],
                "f107": row["f107"],
                "vtec_f107_adjusted": row["vtec_adjusted"],
                "kp": row["kp"],
                "dst": row["dst"],
                "quiet": row["quiet"],
                "ionex_source_file": row["vtec_source_file"],
            })

        def window_counts(name: str) -> dict[str, int]:
            subset = [row for row in timeline if row["window"] == name]
            return {
                f"{name}_hours_expected": len(subset),
                f"{name}_vtec_hours": sum(row["vtec_raw"] is not None for row in subset),
                f"{name}_quiet_hours": sum(row["quiet"] for row in subset),
                f"{name}_quiet_vtec_hours": sum(
                    row["quiet"] and row["vtec_raw"] is not None for row in subset
                ),
            }

        coverage_row = {
            "event_id": event_id,
            "role": event["role"],
            "requested_ionex_days": 51,
            "available_vtec_hours_full_timeline": sum(
                row["vtec_raw"] is not None for row in timeline
            ),
            "quiet_hours_full_timeline": sum(row["quiet"] for row in timeline),
            "quiet_vtec_hours_full_timeline": sum(
                row["quiet"] and row["vtec_raw"] is not None for row in timeline
            ),
            "F107_adjustment_pairs": fit_n,
            "F107_adjustment_status": fit_status,
            "m3_feature_status": m3_status,
            "m3_feature_eligible": m3_eligible,
            **window_counts("B0"),
            **window_counts("W0"),
            **window_counts("B1"),
            **window_counts("W1"),
            **window_counts("GUARD"),
        }
        coverage_output.append(coverage_row)

        v004_ref = v004_index[event_id]
        check_row = {
            "event_id": event_id,
            "m3_feature_status": m3_status,
        }
        diffs = []
        all_match = True
        for field in FEATURE_METRICS:
            new_value = feature_row[field]
            old_value = float(v004_ref[field])
            difference = (
                abs(new_value - old_value)
                if new_value is not None else None
            )
            check_row[f"v004_{field}"] = old_value
            check_row[f"independent_{field}"] = new_value
            check_row[f"abs_diff_{field}"] = difference
            if difference is None or difference > 1e-7:
                all_match = False
            else:
                diffs.append(difference)
        check_row["all_metrics_match_within_1e-7"] = all_match
        check_row["max_abs_difference"] = max(diffs) if diffs else None
        v004_check_output.append(check_row)

        if event_index % 10 == 0 or event_index == len(events):
            print(
                f"M3 scoring progress {event_index}/{len(events)} | "
                f"event={event_id} | status={m3_status}",
                flush=True,
            )

    # Re-export the already frozen cohort/component assignments without relabelling.
    feature_index = {row["event_id"]: row for row in feature_output}
    cohort_membership_output = []
    for row in membership_out:
        event_id = row["event_id"]
        feature = feature_index[event_id]
        cohort_membership_output.append({
            **row,
            "m3_feature_status": feature["m3_feature_status"],
            "m3_feature_eligible": (
                feature["m3_feature_status"] == "M3_FEATURE_ELIGIBLE"
            ),
            "p_vtec_max": feature["p_vtec_max"],
            "p_vtec_q95": feature["p_vtec_q95"],
            "t_vtec_max": feature["t_vtec_max"],
            "t_vtec_q95": feature["t_vtec_q95"],
        })

    strict_ids = cohort_sets["STRICT_TARGETS"]
    conservative_ids = cohort_sets["CONSERVATIVE_TARGETS"]
    all_strict_eligible = all(
        feature_index[eid]["m3_feature_status"] == "M3_FEATURE_ELIGIBLE"
        for eid in strict_ids
    )
    all_conservative_eligible = all(
        feature_index[eid]["m3_feature_status"] == "M3_FEATURE_ELIGIBLE"
        for eid in conservative_ids
    )
    all_original_targets_eligible = all(
        feature_index[eid]["m3_feature_status"] == "M3_FEATURE_ELIGIBLE"
        for eid in cohort_sets["ORIGINAL_TARGETS"]
    )

    reconstruction_matches = all(
        row["all_metrics_match_within_1e-7"] for row in v004_check_output
    )
    reconstruction_mismatches = [
        row["event_id"] for row in v004_check_output
        if not row["all_metrics_match_within_1e-7"]
    ]

    BUILDING_DIR.mkdir(parents=True, exist_ok=False)

    out_rows = {}
    out_rows["m3_event_feature_scores.csv"] = csv_write(
        BUILDING_DIR / "m3_event_feature_scores.csv", feature_output
    )
    out_rows["m3_event_hourly_features.csv"] = csv_write(
        BUILDING_DIR / "m3_event_hourly_features.csv", hourly_output
    )
    out_rows["m3_event_calibration_diagnostics.csv"] = csv_write(
        BUILDING_DIR / "m3_event_calibration_diagnostics.csv", calibration_output
    )
    out_rows["m3_hourly_baseline_statistics.csv"] = csv_write(
        BUILDING_DIR / "m3_hourly_baseline_statistics.csv", baseline_stats_output
    )
    out_rows["m3_event_coverage_audit.csv"] = csv_write(
        BUILDING_DIR / "m3_event_coverage_audit.csv", coverage_output
    )
    out_rows["m3_event_eligibility_ledger.csv"] = csv_write(
        BUILDING_DIR / "m3_event_eligibility_ledger.csv",
        [
            {
                "event_id": row["event_id"],
                "role": row["role"],
                "m3_feature_status": row["m3_feature_status"],
                "m3_feature_eligible": row["m3_feature_status"] == "M3_FEATURE_ELIGIBLE",
                "p_vtec_score_n": row["p_vtec_score_n"],
                "t_vtec_score_n": row["t_vtec_score_n"],
                "p_vtec_baseline_n": row["p_vtec_baseline_n"],
                "t_vtec_baseline_n": row["t_vtec_baseline_n"],
            }
            for row in feature_output
        ]
    )
    out_rows["m3_ionex_file_inventory.csv"] = csv_write(
        BUILDING_DIR / "m3_ionex_file_inventory.csv", ionex_inventory
    )
    out_rows["m3_ionex_event_date_audit.csv"] = csv_write(
        BUILDING_DIR / "m3_ionex_event_date_audit.csv", event_day_audit
    )
    out_rows["m3_omni_file_inventory.csv"] = csv_write(
        BUILDING_DIR / "m3_omni_file_inventory.csv", omni_inventory
    )
    out_rows["m3_cohort_component_membership.csv"] = csv_write(
        BUILDING_DIR / "m3_cohort_component_membership.csv",
        cohort_membership_output,
    )
    out_rows["m3_v004_reconstruction_check.csv"] = csv_write(
        BUILDING_DIR / "m3_v004_reconstruction_check.csv", v004_check_output
    )
    out_rows["m3_unit_tests.csv"] = csv_write(
        BUILDING_DIR / "m3_unit_tests.csv", unit_tests
    )

    strict_missing = sorted(
        eid for eid in strict_ids
        if feature_index[eid]["m3_feature_status"] != "M3_FEATURE_ELIGIBLE"
    )
    conservative_missing = sorted(
        eid for eid in conservative_ids
        if feature_index[eid]["m3_feature_status"] != "M3_FEATURE_ELIGIBLE"
    )

    qa = {
        "schema": "LAIC_GUARD_INDEPENDENT_M3_QA_v002",
        "supersedes_v001_reason": (
            "v001 incorrectly used the upper-middle order statistic for even-length "
            "median and MAD samples. Stage4B median_and_mad averages the two central "
            "values when n is even. v002 corrects the implementation and unit tests."
        ),
        "all_source_hashes_verified": True,
        "source_event_count": len(events),
        "source_target_count": sum(e["role"] == "PRIMARY_SHALLOW_TARGET" for e in events),
        "source_control_count": sum(e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE" for e in events),
        "required_ionex_unique_dates": len(date_to_events),
        "ionex_event_date_requests": len(event_day_audit),
        "ionex_files_successfully_parsed": len(ionex_inventory),
        "ionex_total_tec_maps": total_map_blocks,
        "ionex_grid_dimensions": sorted({
            f"{row['n_lats']}x{row['n_lons']}"
            for row in ionex_inventory
        }),
        "ionex_exponent_values": sorted({row["exponent"] for row in ionex_inventory}),
        "ionex_nan_cells": total_nan_cells,
        "ionex_grid_cells_parsed": total_grid_cells,
        "duplicate_vtec_hour_assignments_overwritten_in_date_order": duplicate_hour_assignments,
        "omni_diagnostics": omni_diagnostics,
        "hourly_feature_rows": len(hourly_output),
        "expected_hourly_feature_rows": len(events) * 1081,
        "event_m3_feature_eligible_count": sum(
            row["m3_feature_status"] == "M3_FEATURE_ELIGIBLE"
            for row in feature_output
        ),
        "original_target_count": len(cohort_sets["ORIGINAL_TARGETS"]),
        "original_targets_all_m3_eligible": all_original_targets_eligible,
        "strict_target_count": len(strict_ids),
        "strict_targets_all_m3_eligible": all_strict_eligible,
        "strict_target_m3_ineligible_ids": strict_missing,
        "conservative_target_count": len(conservative_ids),
        "conservative_targets_all_m3_eligible": all_conservative_eligible,
        "conservative_target_m3_ineligible_ids": conservative_missing,
        "v004_reconstruction_metrics": list(FEATURE_METRICS),
        "v004_reconstruction_all_111_events_match_within_1e-7": reconstruction_matches,
        "v004_reconstruction_mismatch_ids": reconstruction_mismatches,
        "cohort_summary": cohort_summary,
        "statistical_inference_run": False,
        "benchmark_run": False,
        "interpretation": (
            "Feature extraction and independent V004 reconstruction only. "
            "No ROC/AUC, permutation, bootstrap, paired inference, or claims "
            "of precursor predictability are produced by this builder."
        ),
    }
    (BUILDING_DIR / "m3_qa.json").write_text(
        json.dumps(qa, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )

    output_inventory = {}
    for path in sorted(BUILDING_DIR.iterdir()):
        if path.is_file():
            output_inventory[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": out_rows.get(path.name),
            }

    manifest = {
        "schema": "LAIC_GUARD_INDEPENDENT_M3_FEATURE_MANIFEST_v002",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "builder_file": Path(__file__).name,
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "supersedes_v001_builder_sha256": "4D83E48FFA24A7C19E24444FFF3F1D3F897D96BD682914713D57B3E722A553BE",
        "supersedes_v001_reason": (
            "v001 implemented the median/MAD helper incorrectly for even-length "
            "samples. v002 follows the pinned Stage4B helper exactly."
        ),
        "method": {
            "event_population": "Stage4B paired tier-1 events; 111 exact event IDs",
            "epicentre_source": "Stage1D frozen catalogue latitude_deg/longitude_deg",
            "event_time_source": "Stage4B origin_time_utc, exact-matched to Stage1D and V004",
            "ionex_daily_dates": "event calendar date offsets -45 through +5 inclusive",
            "ionex_candidate_precedence": "CODG*.Z first; COD0OPSFIN*.INX.gz second; selected file must exceed 2000 bytes",
            "ionex_grid": "validated 71x73; exponent -1; grid values multiplied by 10**exponent",
            "interpolation": "independent exact copy of Stage4B bilinear_vtec formula, including edge clamping",
            "timeline": "event origin truncated down to UTC hour; offsets -1080 through 0 inclusive",
            "quiet_condition": "Kp available and <3.0; Dst available and >-30.0",
            "f107_adjustment_fit": "OLS slope fitted on quiet B0 union B1 pairs; >=48 pairs; predictor Sxx >1e-6; adjusted VTEC = VTEC - slope*(F10.7 - mean F10.7)",
            "baseline_windows": {
                "B0": [-1080, -792],
                "W0": [-792, -552],
                "B1": [-552, -264],
                "W1": [-264, -24],
                "GUARD": [-24, 0],
            },
            "scoring": "quiet hours only; baseline pool >=20; hourly-of-day median/MAD when >=2 samples else pooled; exact Stage4B median/MAD using averaged central pair for even n and central value for odd n; 1.4826 scale with 1e-6 floor; absolute z scores",
            "q95": "sorted order statistic at floor(0.95*(n-1))",
            "event_feature_eligibility": "B0 and B1 baseline pools >=20 and W0 and W1 each have >=12 quiet adjusted-VTEC scores",
            "cohort_handling": "frozen Stage6A.1 event IDs and primary dependency component IDs are copied unchanged; no component rebuilding",
            "reconstruction": "V004 M3 feature fields are comparison references only; independent features are calculated from IONEX and OMNI inputs",
        },
        "input_sha256": verified_input_hashes,
        "ionex_file_count": len(ionex_inventory),
        "ionex_file_inventory_sha256": sha256_file(BUILDING_DIR / "m3_ionex_file_inventory.csv"),
        "omni_file_count": len(omni_inventory),
        "omni_file_inventory_sha256": sha256_file(BUILDING_DIR / "m3_omni_file_inventory.csv"),
        "cohort_summary": cohort_summary,
        "qa_file": {
            "name": "m3_qa.json",
            "sha256": sha256_file(BUILDING_DIR / "m3_qa.json"),
        },
        "output_files": output_inventory,
        "statistical_inference_run": False,
        "benchmark_run": False,
    }
    (BUILDING_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )

    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    os.replace(BUILDING_DIR, OUTPUT_DIR)

    print("\n===== M3 FEATURE BUILD COMPLETE =====")
    print("Output:", OUTPUT_DIR)
    print("Events:", len(events))
    print("IONEX unique files:", len(ionex_inventory))
    print("IONEX event-date audit rows:", len(event_day_audit))
    print("Valid TEC maps:", total_map_blocks)
    print("OMNI required unique hours:", len(required_omni_keys))
    print("Hourly feature rows:", len(hourly_output))
    print("M3 eligible events:", qa["event_m3_feature_eligible_count"], "/", len(events))
    print("Strict target M3 eligibility:", all_strict_eligible, f"({len(strict_ids)} events)")
    print("Conservative target M3 eligibility:", all_conservative_eligible, f"({len(conservative_ids)} events)")
    print("V004 reconstruction exact-within-tolerance:", reconstruction_matches)
    print("Statistical inference run: False")
    print("Benchmark run: False")
    print("Output files:", len(output_inventory) + 1)
    print("Manifest SHA256:", sha256_file(OUTPUT_DIR / "manifest.json"))
    print("QA SHA256:", sha256_file(OUTPUT_DIR / "m3_qa.json"))


if __name__ == "__main__":
    main()
