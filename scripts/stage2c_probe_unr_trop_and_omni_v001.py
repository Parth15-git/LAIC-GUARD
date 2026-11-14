import csv
import hashlib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
ANCHORS_CSV = ROOT / "reports/stage2b/coverage_matrix_v001/analysis/event_primary_gnss_anchors_v001.csv"
DIST_CSV = ROOT / "reports/stage2a/gnss_station_pairing_v001/analysis/station_event_distances_v001.csv"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
OUT_DIR = ROOT / "reports/stage2c/archive_readiness_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"

OMNI_CACHE.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage2C-ArchiveProbe/1.0 (academic-research)"


def required_years(origin_utc: str) -> list[int]:
    dt = datetime.fromisoformat(origin_utc.replace("Z", "+00:00"))
    y0 = (dt - timedelta(days=45)).year
    y1 = (dt + timedelta(days=5)).year
    return sorted({y0, y1})


def probe_unr_trop_station_years(sta: str, years: list[int]) -> tuple[bool, list[str]]:
    urls_checked = []
    for yr in years:
        found_yr = False
        for base in (
            f"https://geodesy.unr.edu/gps_timeseries/IGS20/trop/{sta}/{sta}.{yr}.trop.zip",
            f"https://geodesy.unr.edu/gps_timeseries/trop/{sta}/{sta}.{yr}.trop.zip",
        ):
            try:
                req = urllib.request.Request(base, method="HEAD", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        urls_checked.append(base)
                        found_yr = True
                        break
            except Exception:
                continue
        if not found_yr:
            return False, urls_checked
    return True, urls_checked


def fetch_omni_year(yr: int) -> Path:
    dest = OMNI_CACHE / f"omni2_{yr}.dat"
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    url = f"https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_{yr}.dat"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())
    return dest


def load_omni_daily_stats(years: set[int]) -> dict[str, tuple[float | None, float | None]]:
    # Download required years in parallel
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(fetch_omni_year, sorted(years)))

    daily_kp: dict[str, list[float]] = {}
    daily_dst: dict[str, list[float]] = {}

    for yr in sorted(years):
        fp = OMNI_CACHE / f"omni2_{yr}.dat"
        with fp.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 41:
                    continue
                try:
                    y = int(parts[0])
                    doy = int(parts[1])
                    kp10 = int(parts[38])
                    dst = float(parts[40])
                except ValueError:
                    continue
                date_str = (datetime(y, 1, 1) + timedelta(days=doy - 1)).strftime("%Y-%m-%d")
                if 0 <= kp10 <= 90:
                    daily_kp.setdefault(date_str, []).append(kp10 / 10.0)
                if -1000.0 <= dst <= 500.0:
                    daily_dst.setdefault(date_str, []).append(dst)

    all_days = set(daily_kp.keys()) | set(daily_dst.keys())
    out = {}
    for d in all_days:
        kp_max = max(daily_kp[d]) if d in daily_kp else None
        dst_min = min(daily_dst[d]) if d in daily_dst else None
        out[d] = (kp_max, dst_min)
    return out


def main() -> None:
    with ANCHORS_CSV.open("r", encoding="utf-8-sig") as f:
        anchors = list(csv.DictReader(f))

    near_reg = [a for a in anchors if a["stage2b_near_regional_eligible_le_300km"] == "True"]
    print(f"Stage 2C probing {len(near_reg)} near-regional (<= 300 km) events...")

    # Load all active <=300km candidate stations per event so we can promote backup if primary lacks .trop.zip
    cands_by_event: dict[str, list[dict]] = {}
    with DIST_CSV.open("r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["station_active_minus45_plus5d"] == "True" and float(r["distance_km"]) <= 300.0:
                cands_by_event.setdefault(r["event_id"], []).append(r)
    for eid in cands_by_event:
        cands_by_event[eid].sort(key=lambda x: float(x["distance_km"]))

    # Collect unique (station_id, year) pairs for top-2 candidate stations per event
    probe_tasks = set()
    needed_years = set()
    for ev in near_reg:
        yrs = required_years(ev["origin_time_utc"])
        needed_years.update(yrs)
        for cand in cands_by_event.get(ev["event_id"], [])[:2]:
            for y in yrs:
                probe_tasks.add((cand["station_id"], y))

    print(f"Probing {len(probe_tasks)} unique (station, year) UNR .trop.zip URLs...")
    sta_yr_ok: dict[tuple[str, int], str] = {}

    def _check_one(item: tuple[str, int]) -> tuple[tuple[str, int], str]:
        sta, yr = item
        for base in (
            f"https://geodesy.unr.edu/gps_timeseries/IGS20/trop/{sta}/{sta}.{yr}.trop.zip",
            f"https://geodesy.unr.edu/gps_timeseries/trop/{sta}/{sta}.{yr}.trop.zip",
        ):
            try:
                req = urllib.request.Request(base, method="HEAD", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        return item, base
            except Exception:
                continue
        return item, ""

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(_check_one, t) for t in sorted(probe_tasks)]
        for i, fut in enumerate(as_completed(futures), 1):
            k, url = fut.result()
            sta_yr_ok[k] = url
            if i % 150 == 0 or i == len(futures):
                ok_so_far = sum(1 for v in sta_yr_ok.values() if v)
                print(f"  UNR probe progress: {i}/{len(futures)} (HTTP 200 confirmed: {ok_so_far})")

    print(f"Loading NASA OMNIWeb daily Kp/Dst statistics across {len(needed_years)} years...")
    omni_daily = load_omni_daily_stats(needed_years)

    readiness_rows = []
    status_counts = {}

    for ev in near_reg:
        eid = ev["event_id"]
        yrs = required_years(ev["origin_time_utc"])
        ev_date = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00")).date()

        # Quiet-day count in [-45d, -1d] and storm check in [-10d, 0d]
        quiet_days_45 = 0
        valid_omni_45 = 0
        storm_days_10 = 0
        min_dst_10 = 999.0
        max_kp_10 = -1.0

        for offset in range(-45, 0):
            d_str = (ev_date + timedelta(days=offset)).strftime("%Y-%m-%d")
            kp_m, dst_m = omni_daily.get(d_str, (None, None))
            if kp_m is not None and dst_m is not None:
                valid_omni_45 += 1
                if kp_m < 3.0 and dst_m > -30.0:
                    quiet_days_45 += 1
                if offset >= -10:
                    max_kp_10 = max(max_kp_10, kp_m)
                    min_dst_10 = min(min_dst_10, dst_m)
                    if kp_m >= 5.0 or dst_m <= -50.0:
                        storm_days_10 += 1

        # Select verified station (Primary first, else Backup <=300km)
        cands = cands_by_event.get(eid, [])[:2]
        chosen_cand = None
        chosen_urls = []
        trop_status = "NO_UNR_TROP_ZIP_IN_TOP2"

        for idx, cand in enumerate(cands):
            urls = [sta_yr_ok.get((cand["station_id"], y), "") for y in yrs]
            if all(urls):
                chosen_cand = cand
                chosen_urls = urls
                trop_status = "PRIMARY_TROP_ZIP_CONFIRMED" if idx == 0 else "BACKUP_TROP_ZIP_PROMOTED"
                break

        quiet_ok = quiet_days_45 >= 15
        ready_stage3 = (chosen_cand is not None) and quiet_ok

        overall_status = (
            "READY_FOR_STAGE3_MULTILAYER_INGEST"
            if ready_stage3
            else ("UNR_TROP_MISSING" if chosen_cand is None else "INSUFFICIENT_QUIET_DAYS_LT_15")
        )
        status_counts[overall_status] = status_counts.get(overall_status, 0) + 1

        readiness_rows.append({
            "event_id": eid,
            "origin_time_utc": ev["origin_time_utc"],
            "magnitude": ev["magnitude"],
            "depth_km": ev["depth_km"],
            "frozen_macro_region_v001": ev["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": ev["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": ev["stage1d_analysis_role_v001"],
            "stage2b_coupling_eligibility_tier": ev["stage2b_coupling_eligibility_tier"],
            "verified_gnss_station_id": chosen_cand["station_id"] if chosen_cand else "",
            "verified_gnss_distance_km": chosen_cand["distance_km"] if chosen_cand else "",
            "unr_trop_archive_status": trop_status,
            "unr_trop_urls": ";".join(chosen_urls),
            "omni_valid_days_minus45_minus1": valid_omni_45,
            "omni_quiet_days_kp_lt3_dst_gt_m30": quiet_days_45,
            "omni_storm_days_minus10_0d": storm_days_10,
            "omni_max_kp_minus10_0d": f"{max_kp_10:.1f}" if max_kp_10 >= 0 else "",
            "omni_min_dst_minus10_0d": f"{min_dst_10:.0f}" if min_dst_10 < 900 else "",
            "stage2c_benchmark_ready_v001": str(ready_stage3),
            "stage2c_readiness_status_v001": overall_status,
        })

    out_csv = ANALYSIS_DIR / "stage2c_verified_benchmark_cohort_v001.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(readiness_rows[0].keys()))
        w.writeheader()
        w.writerows(readiness_rows)

    md_out = OUT_DIR / "STAGE2C_ARCHIVE_READINESS_v001.md"
    md_out.write_text(
        "# Stage 2C - UNR Troposphere Archive & OMNIWeb Quiet-Day Readiness (v001)\n\n"
        f"**Near-Regional Cohort Probed (<= 300 km):** {len(near_reg)}\n"
        f"**Benchmark-Ready Events (Confirmed UNR .trop.zip + >=15 Quiet Baseline Days):** "
        f"{status_counts.get('READY_FOR_STAGE3_MULTILAYER_INGEST', 0)} / {len(near_reg)}\n",
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
        '$rows = Import-Csv (Join-Path $PackageRoot "analysis\\stage2c_verified_benchmark_cohort_v001.csv")\n'
        'if ($rows.Count -ne 361) { throw "Expected 361 rows, got $($rows.Count)" }\n'
        'Write-Host "ALL CHECKS PASSED (361 near-regional events audited and SHA-256 verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE2C_ARCHIVE_READINESS_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage2c_verified_benchmark_cohort_v001.csv",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print("\nStage 2C Readiness Summary (361 Near-Regional Events):")
    for k, v in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {k:40s} : {v}")


if __name__ == "__main__":
    main()
