import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
FROZEN_CSV = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
DIST_CSV = ROOT / "reports/stage2a/gnss_station_pairing_v001/analysis/station_event_distances_v001.csv"
OUT_DIR = ROOT / "reports/stage2b/coverage_matrix_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def distance_tier(dist_km: float) -> str:
    if dist_km <= 150.0:
        return "TIER1_NEAR_FIELD_LE_150KM"
    if dist_km <= 300.0:
        return "TIER2_REGIONAL_150_300KM"
    return "TIER3_FAR_DOBROVOLSKY_GT_300KM"


def main() -> None:
    with FROZEN_CSV.open("r", encoding="utf-8-sig") as f:
        events = [
            r for r in csv.DictReader(f)
            if r["stage1d_included_in_pilot_v001"] == "True"
        ]

    # Load active station-event pairs grouped by event_id
    active_by_event: dict[str, list[dict]] = {}
    total_pairs = 0
    active_pairs_total = 0
    with DIST_CSV.open("r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            total_pairs += 1
            if r["station_active_minus45_plus5d"] == "True":
                active_pairs_total += 1
                active_by_event.setdefault(r["event_id"], []).append(r)

    for eid in active_by_event:
        active_by_event[eid].sort(key=lambda x: float(x["distance_km"]))

    anchor_rows = []
    cov_matrix_rows = []
    tier_counts = {}

    for ev in events:
        eid = ev["event_id"]
        macro = ev["frozen_macro_region_v001"]
        role = ev["stage1d_analysis_role_v001"]
        src_class = ev["stage1c4_final_source_class_v001"]
        rd_km = float(ev["dobrovolsky_radius_km"])
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        w_start = (ev_dt - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        w_end = (ev_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        apairs = active_by_event.get(eid, [])
        t1 = [p for p in apairs if float(p["distance_km"]) <= 150.0]
        t2 = [p for p in apairs if 150.0 < float(p["distance_km"]) <= 300.0]
        t3 = [p for p in apairs if float(p["distance_km"]) > 300.0]

        p1 = apairs[0] if len(apairs) >= 1 else None
        p2 = apairs[1] if len(apairs) >= 2 else None
        p1_dist = float(p1["distance_km"]) if p1 else None

        if p1_dist is None:
            coupling_tier = "NO_ACTIVE_GNSS_IN_RD"
            near_reg_eligible = "False"
        elif p1_dist <= 150.0:
            coupling_tier = "TIER1_NEAR_FIELD_ELIGIBLE_LE_150KM"
            near_reg_eligible = "True"
        elif p1_dist <= 300.0:
            coupling_tier = "TIER2_REGIONAL_ELIGIBLE_150_300KM"
            near_reg_eligible = "True"
        else:
            coupling_tier = "TIER3_FAR_FIELD_DOBROVOLSKY_ONLY_GT_300KM"
            near_reg_eligible = "False"

        tier_counts[coupling_tier] = tier_counts.get(coupling_tier, 0) + 1

        anchor_rows.append({
            "event_id": eid,
            "origin_time_utc": ev["origin_time_utc"],
            "magnitude": ev["magnitude"],
            "depth_km": ev["depth_km"],
            "frozen_macro_region_v001": macro,
            "frozen_subregion_v001": ev["frozen_subregion_v001"],
            "stage1c4_final_source_class_v001": src_class,
            "stage1d_analysis_role_v001": role,
            "dobrovolsky_radius_km": f"{rd_km:.2f}",
            "active_stations_tier1_le_150km": len(t1),
            "active_stations_tier2_150_300km": len(t2),
            "active_stations_tier3_gt_300km": len(t3),
            "active_stations_total_in_rd": len(apairs),
            "primary_gnss_station_id": p1["station_id"] if p1 else "",
            "primary_gnss_distance_km": p1["distance_km"] if p1 else "",
            "primary_gnss_azimuth_deg": p1["azimuth_deg"] if p1 else "",
            "primary_gnss_distance_tier": distance_tier(p1_dist) if p1_dist is not None else "NONE",
            "backup_gnss_station_id": p2["station_id"] if p2 else "",
            "backup_gnss_distance_km": p2["distance_km"] if p2 else "",
            "stage2b_coupling_eligibility_tier": coupling_tier,
            "stage2b_near_regional_eligible_le_300km": near_reg_eligible,
        })

        # Populate schema-aligned multi-domain coverage matrix rows (metadata/coverage_matrix.csv schema)
        gnss_sta = p1["station_id"] if p1 else "NONE_IN_RD"
        gnss_status = (
            f"PAIRED_PENDING_TROPO_FETCH_{coupling_tier}"
            if p1 else "UNAVAILABLE_NO_ACTIVE_UNR_STATION_IN_RD"
        )
        gnss_notes = (
            f"Primary={p1['station_id']} ({p1['distance_km']} km, tier={distance_tier(p1_dist)}); "
            f"Tier1(<=150km)={len(t1)}, Tier2(150-300km)={len(t2)}, Tier3(>300km)={len(t3)}"
            if p1 else f"0 active UNR stations within R_D={rd_km:.1f} km"
        )

        domains = [
            (
                gnss_sta,
                "GNSS_TROPOSPHERE",
                "ZTD_AND_PWV_5MIN",
                "UNR_NGL_IGS20_TROP",
                "14400",  # 50 days * 288 samples/day (5-min)
                gnss_status,
                gnss_notes,
            ),
            (
                "GLOBAL_GIM_GRID",
                "IONOSPHERE_GIM",
                "VTEC_1H_OR_2H",
                "CODE_AIUB_IONEX_GIM",
                "1200",   # 50 days * 24 hourly epochs
                "READY_FOR_CODE_IONEX_INGEST",
                f"Epicenter ({ev['latitude_deg']}, {ev['longitude_deg']}) bilinear GIM interpolation",
            ),
            (
                "OMNIWEB_GLOBAL",
                "SPACE_WEATHER",
                "KP_DST_AP_F107_1H",
                "NASA_OMNIWEB_LOWRES",
                "1200",   # 50 days * 24 hourly epochs
                "READY_FOR_OMNIWEB_INGEST",
                "Geomagnetic quiet-day filter (Kp < 3, Dst > -30 nT)",
            ),
            (
                "ERA5_SINGLE_LEVELS",
                "METEOROLOGY_REANALYSIS",
                "TCWV_T2M_SP_TP_1H",
                "ECMWF_COPERNICUS_ERA5",
                "1200",   # 50 days * 24 hourly epochs
                "READY_FOR_ERA5_MET_DECONFOUNDING",
                "Meteorological PWV confound control at primary GNSS / epicenter",
            ),
        ]

        for sta_id, dom, param, prod, exp_samp, cov_st, note in domains:
            cov_matrix_rows.append({
                "event_id": eid,
                "sequence_id": f"SEQ_{eid}",
                "station_id": sta_id,
                "domain": dom,
                "parameter": param,
                "product": prod,
                "window_start_utc": w_start,
                "window_end_utc": w_end,
                "expected_samples": exp_samp,
                "valid_samples": "",
                "coverage_fraction": "",
                "qa_pass_fraction": "",
                "local_relative_path": "",
                "manifest_id": "stage2b_v001_pre_ingest",
                "coverage_status": cov_st,
                "notes": note,
            })

    anchor_csv = ANALYSIS_DIR / "event_primary_gnss_anchors_v001.csv"
    with anchor_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(anchor_rows[0].keys()))
        w.writeheader()
        w.writerows(anchor_rows)

    cov_csv = ANALYSIS_DIR / "coverage_matrix_v001.csv"
    with cov_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cov_matrix_rows[0].keys()))
        w.writeheader()
        w.writerows(cov_matrix_rows)

    md_out = OUT_DIR / "STAGE2B_TIERED_COVERAGE_MATRIX_v001.md"
    md_out.write_text(
        "# Stage 2B - Distance-Tiered GNSS Anchor Selection & Multi-Domain Coverage Matrix (v001)\n\n"
        f"**Stage 2A Total Pairs (d <= R_D):** {total_pairs:,} total ({active_pairs_total:,} active across [-45d, +5d])\n"
        f"**Stage 1D Included Events Evaluated:** {len(events)}\n"
        f"**Near-Regional Eligible (<= 300 km):** {sum(1 for x in anchor_rows if x['stage2b_near_regional_eligible_le_300km'] == 'True')} / {len(events)}\n"
        f"**Multi-Domain Coverage Matrix Rows:** {len(cov_matrix_rows):,} ({len(events)} events x 4 domains)\n",
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
        '$anc = Import-Csv (Join-Path $PackageRoot "analysis\\event_primary_gnss_anchors_v001.csv")\n'
        '$cov = Import-Csv (Join-Path $PackageRoot "analysis\\coverage_matrix_v001.csv")\n'
        'if ($anc.Count -ne 563 -or $cov.Count -ne (563 * 4)) { throw "Row count mismatch" }\n'
        'Write-Host "ALL CHECKS PASSED (563 anchor assignments, 2,252 multi-domain coverage rows verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE2B_TIERED_COVERAGE_MATRIX_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/event_primary_gnss_anchors_v001.csv",
        "analysis/coverage_matrix_v001.csv",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print("\nStage 2B Tier Breakdown (563 Stage 1D Events):")
    for k, v in sorted(tier_counts.items(), key=lambda x: -x[1]):
        print(f"  {k:45s} : {v}")


if __name__ == "__main__":
    main()
