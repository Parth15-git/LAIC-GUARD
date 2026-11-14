import csv
import hashlib
import io
import math
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S2C_CSV = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
OUT_DIR = ROOT / "reports/stage3a/unr_trop_pilot_ingest_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
SERIES_DIR = OUT_DIR / "extracted_windows"

ZIP_CACHE.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
SERIES_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage3A-TropIngest/1.0 (academic-research)"


def download_zip(url: str) -> tuple[str, Path | None, str, str]:
    fname = url.rstrip("/").split("/")[-1]
    dest = ZIP_CACHE / fname
    if dest.exists() and dest.stat().st_size > 500:
        digest = hashlib.sha256(dest.read_bytes()).hexdigest().lower()
        return url, dest, digest, "CACHED"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if len(raw) > 500:
                    dest.write_bytes(raw)
                    digest = hashlib.sha256(raw).hexdigest().lower()
                    return url, dest, digest, "DOWNLOADED"
        except Exception:
            pass
    return url, None, "", "FAILED"


def parse_sinex_trop_zip(zip_path: Path, t_start: datetime, t_end: datetime) -> list[dict]:
    import gzip
    records = []
    d_min = t_start.date()
    d_max = t_end.date()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if ".trop" not in member.lower():
                continue
            # Filter daily members (e.g. AB01.2013.050.trop.gz) by date before decompressing
            base_name = member.split("/")[-1]
            m_parts = base_name.split(".")
            if len(m_parts) >= 4 and m_parts[1].isdigit() and m_parts[2].isdigit():
                try:
                    m_date = (datetime(int(m_parts[1]), 1, 1) + timedelta(days=int(m_parts[2]) - 1)).date()
                    if m_date < d_min or m_date > d_max:
                        continue
                except ValueError:
                    pass

            raw_bytes = zf.read(member)
            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)

            in_sol = False
            col_names: list[str] = []
            for raw_line in io.BytesIO(raw_bytes):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("+TROP/SOLUTION"):
                    in_sol = True
                    continue
                if line.startswith("-TROP/SOLUTION"):
                    break
                if not in_sol or not line.strip():
                    continue
                if line.startswith("*"):
                    hdr = line.lstrip("*").strip().split()
                    if "TROTOT" in hdr:
                        col_names = hdr
                    continue

                parts = line.split()
                if len(parts) < 4:
                    continue

                ts_parts = parts[1].split(":")
                if len(ts_parts) != 3:
                    continue
                try:
                    yy = int(ts_parts[0])
                    doy = int(ts_parts[1])
                    sec = int(ts_parts[2])
                    yr = yy if yy >= 1900 else (2000 + yy if yy < 80 else 1900 + yy)
                    dt = datetime(yr, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, seconds=sec)
                except ValueError:
                    continue

                if dt < t_start or dt > t_end:
                    continue

                try:
                    trotot = float(parts[2])
                    trotot_std = float(parts[3])
                except ValueError:
                    continue

                if not (1000.0 <= trotot <= 3500.0):
                    continue

                iwv_val = ""
                if col_names and "IWV" in col_names:
                    idx = col_names.index("IWV")
                    if idx < len(parts):
                        try:
                            v = float(parts[idx])
                            if 0.0 <= v <= 120.0:
                                iwv_val = f"{v:.3f}"
                        except ValueError:
                            pass
                elif len(parts) >= 10:
                    try:
                        v = float(parts[8])
                        if 0.0 <= v <= 120.0:
                            iwv_val = f"{v:.3f}"
                    except ValueError:
                        pass

                records.append({
                    "timestamp_utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ztd_mm": f"{trotot:.2f}",
                    "ztd_std_mm": f"{trotot_std:.2f}",
                    "iwv_kgm2": iwv_val,
                })
    return records


def main() -> None:
    with S2C_CSV.open("r", encoding="utf-8-sig") as f:
        s2c_rows = list(csv.DictReader(f))

    cohort = [
        r for r in s2c_rows
        if r["stage2c_benchmark_ready_v001"] == "True"
        and r["stage2b_coupling_eligibility_tier"] == "TIER1_NEAR_FIELD_ELIGIBLE_LE_150KM"
        and float(r["magnitude"]) >= 7.0
    ]
    cohort.sort(key=lambda x: x["origin_time_utc"])
    print(f"Stage 3A Tier-1 (<=150 km) M>=7.0 Benchmark-Ready Cohort: {len(cohort)} events")

    unique_urls = sorted({
        u.strip()
        for r in cohort
        for u in r["unr_trop_urls"].split(";")
        if u.strip()
    })
    print(f"Downloading/verifying {len(unique_urls)} unique UNR .trop.zip files...")

    url_map: dict[str, tuple[Path | None, str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(download_zip, u) for u in unique_urls]
        for i, fut in enumerate(as_completed(futures), 1):
            u, p, sha, st = fut.result()
            url_map[u] = (p, sha, st)
            if i % 20 == 0 or i == len(futures):
                print(f"  ZIP fetch progress: {i}/{len(futures)}")

    qa_rows = []
    manifest_rows = []
    seen_manifest = set()

    for ev in cohort:
        eid = ev["event_id"]
        sta = ev["verified_gnss_station_id"]
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        w_start = ev_dt - timedelta(days=45)
        w_end = ev_dt + timedelta(days=5)

        urls = [u.strip() for u in ev["unr_trop_urls"].split(";") if u.strip()]
        merged_by_ts: dict[str, dict] = {}
        zip_shas = []

        for u in urls:
            zpath, zsha, zst = url_map.get(u, (None, "", "MISSING"))
            if zpath and zpath.exists():
                zip_shas.append(f"{zpath.name}:{zsha[:12]}")
                if zpath.name not in seen_manifest:
                    seen_manifest.add(zpath.name)
                    manifest_rows.append({
                        "file_name": zpath.name,
                        "relative_path": f"data/external/gnss/unr_trop_zips_v001/{zpath.name}",
                        "source_url": u,
                        "size_bytes": zpath.stat().st_size,
                        "sha256": zsha,
                        "fetch_status": zst,
                    })
                for rec in parse_sinex_trop_zip(zpath, w_start, w_end):
                    merged_by_ts[rec["timestamp_utc"]] = rec

        sorted_recs = [merged_by_ts[k] for k in sorted(merged_by_ts.keys())]
        expected_samples = 14400  # 50 days * 288 epochs/day
        valid_samples = len(sorted_recs)
        cov_frac = min(1.0, valid_samples / expected_samples)

        iwv_samples = sum(1 for r in sorted_recs if r["iwv_kgm2"] != "")
        ztd_vals = [float(r["ztd_mm"]) for r in sorted_recs]
        ztd_mean = sum(ztd_vals) / len(ztd_vals) if ztd_vals else float("nan")
        ztd_std = (
            math.sqrt(sum((v - ztd_mean) ** 2 for v in ztd_vals) / len(ztd_vals))
            if ztd_vals else float("nan")
        )

        # Write extracted clean 5-min window CSV (preserving exact missing epochs without imputation)
        win_csv = SERIES_DIR / f"{eid}_{sta}_trop_window_v001.csv"
        with win_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp_utc", "ztd_mm", "ztd_std_mm", "iwv_kgm2"])
            w.writeheader()
            w.writerows(sorted_recs)

        qa_status = (
            "QA_PASS_GE_80PCT"
            if cov_frac >= 0.80
            else ("QA_PARTIAL_50_79PCT" if cov_frac >= 0.50 else "QA_LOW_COVERAGE_LT_50PCT")
        )

        qa_rows.append({
            "event_id": eid,
            "origin_time_utc": ev["origin_time_utc"],
            "magnitude": ev["magnitude"],
            "depth_km": ev["depth_km"],
            "frozen_macro_region_v001": ev["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": ev["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": ev["stage1d_analysis_role_v001"],
            "verified_gnss_station_id": sta,
            "verified_gnss_distance_km": ev["verified_gnss_distance_km"],
            "omni_quiet_days_kp_lt3_dst_gt_m30": ev["omni_quiet_days_kp_lt3_dst_gt_m30"],
            "expected_5min_samples": expected_samples,
            "valid_5min_samples": valid_samples,
            "coverage_fraction": f"{cov_frac:.4f}",
            "iwv_valid_samples": iwv_samples,
            "has_direct_iwv_pwv": str(iwv_samples > 0),
            "ztd_mean_mm": f"{ztd_mean:.2f}" if not math.isnan(ztd_mean) else "",
            "ztd_std_mm": f"{ztd_std:.2f}" if not math.isnan(ztd_std) else "",
            "source_zip_sha256_prefix": ";".join(zip_shas),
            "extracted_window_relpath": f"reports/stage3a/unr_trop_pilot_ingest_v001/extracted_windows/{win_csv.name}",
            "stage3a_qa_status": qa_status,
        })

    qa_csv = ANALYSIS_DIR / "stage3a_trop_pilot_qa_v001.csv"
    with qa_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(qa_rows[0].keys()))
        w.writeheader()
        w.writerows(qa_rows)

    man_csv = ANALYSIS_DIR / "stage3a_raw_zip_manifest_v001.csv"
    with man_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(sorted(manifest_rows, key=lambda x: x["file_name"]))

    md_out = OUT_DIR / "STAGE3A_UNR_TROP_PILOT_INGEST_v001.md"
    pass80 = sum(1 for r in qa_rows if r["stage3a_qa_status"] == "QA_PASS_GE_80PCT")
    md_out.write_text(
        "# Stage 3A - Tier-1 (<=150 km) M>=7.0 UNR Troposphere Ingest & QA Report (v001)\n\n"
        f"**Target Cohort:** {len(cohort)} Tier-1 (<=150 km) M>=7.0 benchmark-ready events\n"
        f"**Cached Raw UNR ZIP Archives:** {len(manifest_rows)}\n"
        f"**Events Passing >=80% 5-Minute Sample Completeness:** {pass80} / {len(cohort)}\n"
        "**Imputation Policy:** Strict `preserve_missing` (zero forward/backward/zero fill per `configs/quality_control.yaml`).\n",
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
        '$qa = Import-Csv (Join-Path $PackageRoot "analysis\\stage3a_trop_pilot_qa_v001.csv")\n'
        'Write-Host "ALL CHECKS PASSED ($($qa.Count) Tier-1 M>=7.0 events ingested, parsed, and SHA-256 verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE3A_UNR_TROP_PILOT_INGEST_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage3a_trop_pilot_qa_v001.csv",
        "analysis/stage3a_raw_zip_manifest_v001.csv",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print(f"\nStage 3A Complete: {pass80}/{len(cohort)} events achieved >=80% 5-min ZTD completeness.")


if __name__ == "__main__":
    main()


