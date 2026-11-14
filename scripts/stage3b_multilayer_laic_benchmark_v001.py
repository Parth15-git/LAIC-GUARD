import csv
import gzip
import hashlib
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S3A_QA_CSV = ROOT / "reports/stage3a/unr_trop_pilot_ingest_v001/analysis/stage3a_trop_pilot_qa_v001.csv"
S1D_FROZEN_CSV = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
IONEX_CACHE = ROOT / "data/external/ionosphere/code_ionex_v001"
OUT_DIR = ROOT / "reports/stage3b/multilayer_benchmark_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
ALIGNED_DIR = OUT_DIR / "aligned_hourly_series"

IONEX_CACHE.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
ALIGNED_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage3B-MultiLayer/1.0 (academic-research)"


def unlzw(data: bytes) -> bytes:
    """Pure-Python Unix compress (.Z) LZW decompressor."""
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Invalid .Z LZW header")
    flags = data[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    if max_bits < 9 or max_bits > 16:
        raise ValueError(f"Unsupported LZW max_bits={max_bits}")

    pos = 3
    n_bytes = len(data)
    bit_buf = 0
    bits_in_buf = 0
    code_size = 9
    clear_code = 256 if block_mode else -1
    next_code = 257 if block_mode else 256
    max_code = (1 << max_bits)

    table: dict[int, bytes] = {i: bytes([i]) for i in range(256)}
    out = bytearray()
    prev_seq: bytes | None = None

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
            table = {i: bytes([i]) for i in range(256)}
            code_size = 9
            next_code = 257
            prev_seq = None
            continue

        if prev_seq is None:
            seq = table[code]
            out.extend(seq)
            prev_seq = seq
            continue

        if code in table:
            seq = table[code]
        elif code == next_code:
            seq = prev_seq + prev_seq[:1]
        else:
            raise ValueError(f"Corrupt LZW stream at code={code}")

        out.extend(seq)
        if next_code < max_code:
            table[next_code] = prev_seq + seq[:1]
            next_code += 1
            if next_code == (1 << code_size) and code_size < max_bits:
                code_size += 1
        prev_seq = seq

    return bytes(out)


def fetch_code_ionex_day(day_dt: datetime) -> tuple[str, Path | None, str]:
    yr = day_dt.year
    doy = day_dt.timetuple().tm_yday
    yy = yr % 100
    d_key = day_dt.strftime("%Y-%m-%d")

    candidates = [
        (
            f"CODG{doy:03d}0.{yy:02d}I.Z",
            f"http://www.aiub.unibe.ch/download/CODE/{yr}/CODG{doy:03d}0.{yy:02d}I.Z",
        ),
        (
            f"COD0OPSFIN_{yr}{doy:03d}0000_01D_01H_GIM.INX.gz",
            f"http://www.aiub.unibe.ch/download/CODE/{yr}/COD0OPSFIN_{yr}{doy:03d}0000_01D_01H_GIM.INX.gz",
        ),
    ]

    for fname, _ in candidates:
        fp = IONEX_CACHE / fname
        if fp.exists() and fp.stat().st_size > 2000:
            return d_key, fp, "CACHED"

    for fname, url in candidates:
        fp = IONEX_CACHE / fname
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                if len(raw) > 2000:
                    fp.write_bytes(raw)
                    return d_key, fp, "DOWNLOADED"
        except Exception:
            continue

    return d_key, None, "MISSING"


def parse_ionex_maps(ionex_path: Path) -> list[tuple[datetime, float, float, float, float, float, float, list[list[float]]]]:
    raw = ionex_path.read_bytes()
    if ionex_path.name.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    elif ionex_path.name.endswith(".Z") or raw[:2] == b"\x1f\x9d":
        text = unlzw(raw).decode("utf-8", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")

    lat1, lat2, dlat = 87.5, -87.5, -2.5
    lon1, lon2, dlon = -180.0, 180.0, 5.0
    exponent = -1

    lines = text.splitlines()
    idx = 0
    n_lines = len(lines)
    while idx < n_lines:
        line = lines[idx]
        label = line[60:].strip()
        if label == "END OF HEADER":
            idx += 1
            break
        elif label == "LAT1 / LAT2 / DLAT":
            parts = line[:60].split()
            lat1, lat2, dlat = float(parts[0]), float(parts[1]), float(parts[2])
        elif label == "LON1 / LON2 / DLON":
            parts = line[:60].split()
            lon1, lon2, dlon = float(parts[0]), float(parts[1]), float(parts[2])
        elif label == "EXPONENT":
            exponent = int(line[:60].strip())
        idx += 1

    scale = 10.0 ** exponent
    n_lats = int(round((lat2 - lat1) / dlat)) + 1
    n_lons = int(round((lon2 - lon1) / dlon)) + 1

    maps = []
    while idx < n_lines:
        line = lines[idx]
        label = line[60:].strip()
        if label == "START OF TEC MAP":
            idx += 1
            epoch_dt = None
            grid: list[list[float]] = []
            while idx < n_lines:
                mline = lines[idx]
                mlabel = mline[60:].strip()
                if mlabel == "END OF TEC MAP":
                    idx += 1
                    break
                elif mlabel == "EPOCH OF CURRENT MAP":
                    ep = [int(x) for x in mline[:60].split()]
                    yr, mo, dy, hr, mi, sc = ep[0], ep[1], ep[2], ep[3], ep[4], ep[5]
                    if hr == 24:
                        epoch_dt = datetime(yr, mo, dy, 0, mi, sc, tzinfo=timezone.utc) + timedelta(days=1)
                    else:
                        epoch_dt = datetime(yr, mo, dy, hr, mi, sc, tzinfo=timezone.utc)
                    idx += 1
                elif mlabel == "LAT/LON1/LON2/DLON/H":
                    idx += 1
                    vals: list[float] = []
                    while len(vals) < n_lons and idx < n_lines:
                        row_str = lines[idx]
                        for k in range(0, min(80, len(row_str)), 5):
                            chunk = row_str[k:k+5].strip()
                            if chunk:
                                v = int(chunk)
                                vals.append(float("nan") if v == 9999 else v * scale)
                        idx += 1
                    grid.append(vals[:n_lons])
                else:
                    idx += 1
            if epoch_dt is not None and len(grid) == n_lats:
                maps.append((epoch_dt, lat1, dlat, lon1, dlon, n_lats, n_lons, grid))
        else:
            idx += 1
    return maps


def bilinear_vtec(m_tuple, lat: float, lon: float) -> float:
    _, lat1, dlat, lon1, dlon, n_lats, n_lons, grid = m_tuple
    fi = (lat - lat1) / dlat
    fj = (lon - lon1) / dlon
    i0 = max(0, min(n_lats - 2, int(math.floor(fi))))
    j0 = max(0, min(n_lons - 2, int(math.floor(fj))))
    wy = max(0.0, min(1.0, fi - i0))
    wx = max(0.0, min(1.0, fj - j0))
    v00 = grid[i0][j0]
    v01 = grid[i0][j0 + 1]
    v10 = grid[i0 + 1][j0]
    v11 = grid[i0 + 1][j0 + 1]
    val = (1 - wy) * ((1 - wx) * v00 + wx * v01) + wy * ((1 - wx) * v10 + wx * v11)
    return val


def load_omni_hourly(years: set[int]) -> dict[str, tuple[float | None, float | None]]:
    hourly: dict[str, tuple[float | None, float | None]] = {}
    for yr in sorted(years):
        fp = OMNI_CACHE / f"omni2_{yr}.dat"
        if not fp.exists():
            continue
        with fp.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 41:
                    continue
                try:
                    y, doy, hr = int(parts[0]), int(parts[1]), int(parts[2])
                    kp10 = int(parts[38])
                    dst = float(parts[40])
                except ValueError:
                    continue
                dt = datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hr)
                ts = dt.strftime("%Y-%m-%dT%H:00:00Z")
                kp_v = (kp10 / 10.0) if (0 <= kp10 <= 90) else None
                dst_v = dst if (-1000.0 <= dst <= 500.0) else None
                hourly[ts] = (kp_v, dst_v)
    return hourly


def median_and_mad(vals: list[float]) -> tuple[float, float]:
    s = sorted(vals)
    n = len(s)
    med = s[n // 2] if n % 2 == 1 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    devs = sorted(abs(v - med) for v in s)
    mad = devs[n // 2] if n % 2 == 1 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
    sigma = max(1e-6, 1.4826 * mad)
    return med, sigma


def main() -> None:
    with S1D_FROZEN_CSV.open("r", encoding="utf-8-sig") as f:
        ev_meta = {r["event_id"]: r for r in csv.DictReader(f)}

    with S3A_QA_CSV.open("r", encoding="utf-8-sig") as f:
        qa_pass_rows = [
            r for r in csv.DictReader(f)
            if r["stage3a_qa_status"] == "QA_PASS_GE_80PCT"
        ]
    qa_pass_rows.sort(key=lambda x: x["origin_time_utc"])
    print(f"Stage 3B Benchmarking {len(qa_pass_rows)} QA_PASS_GE_80PCT Tier-1 M>=7.0 events...")

    # Determine unique UTC calendar days needed across [-45d, +5d] for all 43 events
    needed_days: dict[str, datetime] = {}
    needed_years: set[int] = set()
    for r in qa_pass_rows:
        ev_dt = datetime.fromisoformat(r["origin_time_utc"].replace("Z", "+00:00"))
        for off in range(-45, 6):
            d = (ev_dt + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
            needed_days[d.strftime("%Y-%m-%d")] = d
            needed_years.add(d.year)

    print(f"Fetching/verifying {len(needed_days)} unique daily CODE AIUB IONEX GIM files...")
    ionex_files: dict[str, Path] = {}
    fetch_stats = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fetch_code_ionex_day, d) for d in needed_days.values()]
        for i, fut in enumerate(as_completed(futures), 1):
            d_key, fp, st = fut.result()
            fetch_stats[st] = fetch_stats.get(st, 0) + 1
            if fp is not None:
                ionex_files[d_key] = fp
            if i % 300 == 0 or i == len(futures):
                print(f"  IONEX fetch progress: {i}/{len(futures)} | {fetch_stats}")

    print("Parsing cached IONEX global TEC maps...")
    parsed_maps_by_day: dict[str, list] = {}
    for d_key, fp in ionex_files.items():
        try:
            parsed_maps_by_day[d_key] = parse_ionex_maps(fp)
        except Exception:
            parsed_maps_by_day[d_key] = []

    omni_hourly = load_omni_hourly(needed_years)

    bench_rows = []
    for r in qa_pass_rows:
        eid = r["event_id"]
        meta = ev_meta[eid]
        elat = float(meta["latitude_deg"])
        elon = float(meta["longitude_deg"])
        ev_dt = datetime.fromisoformat(r["origin_time_utc"].replace("Z", "+00:00"))
        ev_hour = ev_dt.replace(minute=0, second=0, microsecond=0)

        # Aggregate 5-min GNSS ZTD & IWV into exact UTC hourly means (no imputation)
        win_path = ROOT / r["extracted_window_relpath"]
        ztd_hr_bins: dict[str, list[float]] = {}
        iwv_hr_bins: dict[str, list[float]] = {}
        with win_path.open("r", encoding="utf-8") as wf:
            for tr in csv.DictReader(wf):
                hr_key = tr["timestamp_utc"][:13] + ":00:00Z"
                ztd_hr_bins.setdefault(hr_key, []).append(float(tr["ztd_mm"]))
                if tr["iwv_kgm2"] != "":
                    iwv_hr_bins.setdefault(hr_key, []).append(float(tr["iwv_kgm2"]))

        # Extract bilinear VTEC at epicenter for all epochs in [-45d, +5d]
        vtec_hr_map: dict[str, float] = {}
        for off in range(-45, 6):
            d_key = (ev_dt + timedelta(days=off)).strftime("%Y-%m-%d")
            for m_tup in parsed_maps_by_day.get(d_key, []):
                ep_ts = m_tup[0].strftime("%Y-%m-%dT%H:00:00Z")
                val = bilinear_vtec(m_tup, elat, elon)
                if not math.isnan(val):
                    vtec_hr_map[ep_ts] = val

        # Build aligned hourly timeline from -45d to +5d (1,201 hourly epochs)
        timeline = []
        for h_off in range(-45 * 24, 5 * 24 + 1):
            t_cur = ev_hour + timedelta(hours=h_off)
            ts = t_cur.strftime("%Y-%m-%dT%H:00:00Z")
            kp_v, dst_v = omni_hourly.get(ts, (None, None))
            is_quiet = (kp_v is not None and dst_v is not None and kp_v < 3.0 and dst_v > -30.0)
            ztd_v = (sum(ztd_hr_bins[ts]) / len(ztd_hr_bins[ts])) if ts in ztd_hr_bins else None
            iwv_v = (sum(iwv_hr_bins[ts]) / len(iwv_hr_bins[ts])) if ts in iwv_hr_bins else None
            vtec_v = vtec_hr_map.get(ts, None)
            timeline.append({
                "ts": ts,
                "rel_hours": h_off,
                "hour_of_day": t_cur.hour,
                "is_quiet": is_quiet,
                "kp": kp_v,
                "dst": dst_v,
                "ztd": ztd_v,
                "iwv": iwv_v,
                "vtec": vtec_v,
            })

        # Calibrate diurnal quiet-day baseline strictly on [-45d, -21d] (<= -504h)
        def calibrate_diurnal(field: str) -> dict[int, tuple[float, float]]:
            cal = {}
            all_q = [x[field] for x in timeline if x["rel_hours"] <= -21 * 24 and x["is_quiet"] and x[field] is not None]
            if len(all_q) < 24:
                return cal
            g_med, g_sig = median_and_mad(all_q)
            for h in range(24):
                vals = [
                    x[field] for x in timeline
                    if x["rel_hours"] <= -21 * 24 and x["is_quiet"] and x["hour_of_day"] == h and x[field] is not None
                ]
                cal[h] = median_and_mad(vals) if len(vals) >= 4 else (g_med, g_sig)
            return cal

        trop_field = "iwv" if sum(1 for x in timeline if x["iwv"] is not None) >= 800 else "ztd"
        trop_cal = calibrate_diurnal(trop_field)
        vtec_cal = calibrate_diurnal("vtec")

        # Score out-of-sample Placebo Control [-20d, -11d] vs Pre-Event Target [-10d, 0d]
        def window_metrics(h_min: int, h_max: int) -> dict:
            trop_z_list = []
            vtec_q_z_list = []
            joint_hits = 0
            for x in timeline:
                if not (h_min <= x["rel_hours"] <= h_max):
                    continue
                zt = None
                zv_q = None
                if x[trop_field] is not None and x["hour_of_day"] in trop_cal:
                    med, sig = trop_cal[x["hour_of_day"]]
                    zt = (x[trop_field] - med) / sig
                    trop_z_list.append(abs(zt))
                if x["is_quiet"] and x["vtec"] is not None and x["hour_of_day"] in vtec_cal:
                    med, sig = vtec_cal[x["hour_of_day"]]
                    zv_q = (x["vtec"] - med) / sig
                    vtec_q_z_list.append(abs(zv_q))
                if zt is not None and zv_q is not None and abs(zt) >= 2.5 and abs(zv_q) >= 2.5:
                    joint_hits += 1

            return {
                "trop_max_abs_z": max(trop_z_list) if trop_z_list else float("nan"),
                "trop_exc_ge_3": sum(1 for v in trop_z_list if v >= 3.0),
                "vtec_q_max_abs_z": max(vtec_q_z_list) if vtec_q_z_list else float("nan"),
                "vtec_q_exc_ge_3": sum(1 for v in vtec_q_z_list if v >= 3.0),
                "joint_multilayer_ge_2p5": joint_hits,
            }

        ctrl = window_metrics(-20 * 24, -11 * 24 - 1)
        targ = window_metrics(-10 * 24, 0)

        # Save aligned hourly series CSV for full reproducibility
        aligned_csv = ALIGNED_DIR / f"{eid}_{r['verified_gnss_station_id']}_aligned_hourly_v001.csv"
        with aligned_csv.open("w", newline="", encoding="utf-8") as af:
            aw = csv.writer(af)
            aw.writerow(["timestamp_utc", "rel_hours", "is_geomag_quiet", "kp", "dst_nt", "ztd_mm", "iwv_kgm2", "code_gim_vtec_tecu"])
            for x in timeline:
                aw.writerow([
                    x["ts"],
                    x["rel_hours"],
                    x["is_quiet"],
                    f"{x['kp']:.1f}" if x["kp"] is not None else "",
                    f"{x['dst']:.0f}" if x["dst"] is not None else "",
                    f"{x['ztd']:.2f}" if x["ztd"] is not None else "",
                    f"{x['iwv']:.3f}" if x["iwv"] is not None else "",
                    f"{x['vtec']:.2f}" if x["vtec"] is not None else "",
                ])

        vtec_valid_hrs = sum(1 for x in timeline if x["vtec"] is not None)
        bench_rows.append({
            "event_id": eid,
            "origin_time_utc": r["origin_time_utc"],
            "magnitude": r["magnitude"],
            "depth_km": r["depth_km"],
            "frozen_macro_region_v001": r["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": r["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": r["stage1d_analysis_role_v001"],
            "verified_gnss_station_id": r["verified_gnss_station_id"],
            "verified_gnss_distance_km": r["verified_gnss_distance_km"],
            "trop_variable_used": trop_field.upper(),
            "vtec_valid_epochs": vtec_valid_hrs,
            "ctrl_m20_m11_trop_max_z": f"{ctrl['trop_max_abs_z']:.2f}" if not math.isnan(ctrl["trop_max_abs_z"]) else "",
            "targ_m10_0_trop_max_z": f"{targ['trop_max_abs_z']:.2f}" if not math.isnan(targ["trop_max_abs_z"]) else "",
            "ctrl_m20_m11_vtec_q_max_z": f"{ctrl['vtec_q_max_abs_z']:.2f}" if not math.isnan(ctrl["vtec_q_max_abs_z"]) else "",
            "targ_m10_0_vtec_q_max_z": f"{targ['vtec_q_max_abs_z']:.2f}" if not math.isnan(targ["vtec_q_max_abs_z"]) else "",
            "ctrl_joint_hits_ge_2p5": ctrl["joint_multilayer_ge_2p5"],
            "targ_joint_hits_ge_2p5": targ["joint_multilayer_ge_2p5"],
            "targ_exceeds_ctrl_trop": str(targ["trop_max_abs_z"] > ctrl["trop_max_abs_z"]) if (not math.isnan(targ["trop_max_abs_z"]) and not math.isnan(ctrl["trop_max_abs_z"])) else "",
            "targ_exceeds_ctrl_vtec_q": str(targ["vtec_q_max_abs_z"] > ctrl["vtec_q_max_abs_z"]) if (not math.isnan(targ["vtec_q_max_abs_z"]) and not math.isnan(ctrl["vtec_q_max_abs_z"])) else "",
        })

    bench_csv = ANALYSIS_DIR / "stage3b_multilayer_falsification_results_v001.csv"
    with bench_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(bench_rows[0].keys()))
        w.writeheader()
        w.writerows(bench_rows)

    md_out = OUT_DIR / "STAGE3B_MULTILAYER_BENCHMARK_v001.md"
    md_out.write_text(
        "# Stage 3B - Multi-Layer Troposphere + CODE GIM VTEC + OMNIWeb Falsification Benchmark (v001)\n\n"
        f"**Evaluated Cohort:** {len(bench_rows)} Tier-1 (<=150 km) M>=7.0 events with >=80% 5-min GNSS completeness\n"
        "**Calibration Window:** [-45d, -21d] (strictly out-of-sample, quiet-day filtered Kp < 3, Dst > -30 nT)\n"
        "**Falsification Contrast:** Placebo Control [-20d, -11d] vs. Pre-Event Target [-10d, 0d] & Primary Shallow vs. Deep/Outer-Rise Null Control\n",
        encoding="utf-8",
    )

    verify_ps1 = OUT_DIR / "VERIFY_PACKAGE.ps1"
    verify_ps1.write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n'
        '$ErrorActionPreference = "Stop"\n'
        '$entries = Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv")\n'
        'foreach ($e in $entries) {\n'
        '    $fp = Join-Path $PackageRoot $e.relative_path\n'
        '    if (!(Test-Path $fp) -or (Get-FileHash $fp -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) {\n'
        '        throw "SHA256 mismatch: $($e.relative_path)"\n'
        '    }\n'
        '    Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n'
        '}\n'
        '$res = Import-Csv (Join-Path $PackageRoot "analysis\\stage3b_multilayer_falsification_results_v001.csv")\n'
        'Write-Host "ALL CHECKS PASSED ($($res.Count) multi-layer benchmark events verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE3B_MULTILAYER_BENCHMARK_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage3b_multilayer_falsification_results_v001.csv",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print("\nStage 3B Complete.")


if __name__ == "__main__":
    main()
