import csv
import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S3B_CSV = ROOT / "reports/stage3b/multilayer_benchmark_v001/analysis/stage3b_multilayer_falsification_results_v001.csv"
ALIGNED_DIR = ROOT / "reports/stage3b/multilayer_benchmark_v001/aligned_hourly_series"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
OUT_DIR = ROOT / "reports/stage3c/deconfounded_falsification_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def load_omni_f107() -> dict[str, float]:
    """Load hourly/daily F10.7 solar flux (col index 50 in OMNI2) from cached files."""
    f107_map: dict[str, float] = {}
    for fp in sorted(OMNI_CACHE.glob("omni2_*.dat")):
        with fp.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 51:
                    continue
                try:
                    y, doy, hr = int(parts[0]), int(parts[1]), int(parts[2])
                    f107 = float(parts[50])
                except ValueError:
                    continue
                if 50.0 <= f107 <= 400.0:
                    dt = datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hr)
                    f107_map[dt.strftime("%Y-%m-%dT%H:00:00Z")] = f107
    return f107_map


def median_and_mad(vals: list[float]) -> tuple[float, float]:
    s = sorted(vals)
    n = len(s)
    med = s[n // 2] if n % 2 == 1 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    devs = sorted(abs(v - med) for v in s)
    mad = devs[n // 2] if n % 2 == 1 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
    return med, max(1e-6, 1.4826 * mad)


def roc_auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def wilcoxon_paired_greater_p(diffs: list[float]) -> float:
    """Normal-approximation one-sided Wilcoxon signed-rank p-value (H1: median(diffs) > 0)."""
    nz = [d for d in diffs if abs(d) > 1e-9]
    n = len(nz)
    if n < 5:
        return float("nan")
    ranked = sorted(enumerate(nz), key=lambda x: abs(x[1]))
    w_plus = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(ranked[j + 1][1]) - abs(ranked[i][1])) <= 1e-9:
            j += 1
        avg_rank = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            if ranked[k][1] > 0:
                w_plus += avg_rank
        i = j + 1
    mean_w = n * (n + 1) / 4.0
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = (w_plus - mean_w - 0.5) / std_w
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def mann_whitney_greater_p(x: list[float], y: list[float]) -> float:
    """Normal-approximation one-sided Mann-Whitney U p-value (H1: x > y)."""
    nx, ny = len(x), len(y)
    if nx < 3 or ny < 3:
        return float("nan")
    u = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                u += 1.0
            elif xi == yj:
                u += 0.5
    mean_u = nx * ny / 2.0
    std_u = math.sqrt(nx * ny * (nx + ny + 1) / 12.0)
    z = (u - mean_u - 0.5) / std_u
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def fit_f107_slope(rows: list[dict]) -> tuple[float, float]:
    """Fit simple linear VTEC ~ a + b * F10.7 on quiet baseline epochs [-45d, -11d]."""
    pts = [
        (r["f107"], r["vtec"])
        for r in rows
        if -45 * 24 <= r["rel_hours"] <= -11 * 24 - 1
        and r["is_quiet"]
        and r["f107"] is not None
        and r["vtec"] is not None
    ]
    if len(pts) < 48:
        return 0.0, 0.0
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx < 1e-6:
        return 0.0, mx
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    slope = sxy / sxx
    return slope, mx


def score_lag_matched_window(
    rows: list[dict],
    cal_h_min: int,
    cal_h_max: int,
    eval_h_min: int,
    eval_h_max: int,
    trop_key: str,
) -> dict:
    def build_cal(field: str, quiet_only: bool) -> dict[int, tuple[float, float]]:
        pool = [
            r[field] for r in rows
            if cal_h_min <= r["rel_hours"] <= cal_h_max
            and r[field] is not None
            and (not quiet_only or r["is_quiet"])
        ]
        if len(pool) < 24:
            return {}
        g_med, g_sig = median_and_mad(pool)
        out = {}
        for h in range(24):
            sub = [
                r[field] for r in rows
                if cal_h_min <= r["rel_hours"] <= cal_h_max
                and r["hour"] == h
                and r[field] is not None
                and (not quiet_only or r["is_quiet"])
            ]
            out[h] = median_and_mad(sub) if len(sub) >= 3 else (g_med, g_sig)
        return out

    trop_cal = build_cal(trop_key, quiet_only=False)
    vtec_cal = build_cal("vtec_detrended", quiet_only=True)

    trop_zs = []
    vtec_zs = []
    joint_hits = 0

    for r in rows:
        if not (eval_h_min <= r["rel_hours"] <= eval_h_max):
            continue
        zt = None
        zv = None
        if r[trop_key] is not None and r["hour"] in trop_cal:
            med, sig = trop_cal[r["hour"]]
            zt = abs((r[trop_key] - med) / sig)
            trop_zs.append(zt)
        if r["is_quiet"] and r["vtec_detrended"] is not None and r["hour"] in vtec_cal:
            med, sig = vtec_cal[r["hour"]]
            zv = abs((r["vtec_detrended"] - med) / sig)
            vtec_zs.append(zv)
        if zt is not None and zv is not None and zt >= 2.5 and zv >= 2.5:
            joint_hits += 1

    return {
        "trop_max_z": max(trop_zs) if trop_zs else float("nan"),
        "trop_q95_z": sorted(trop_zs)[int(0.95 * (len(trop_zs) - 1))] if trop_zs else float("nan"),
        "vtec_max_z": max(vtec_zs) if vtec_zs else float("nan"),
        "vtec_q95_z": sorted(vtec_zs)[int(0.95 * (len(vtec_zs) - 1))] if vtec_zs else float("nan"),
        "joint_hits": joint_hits,
    }


def main() -> None:
    f107_map = load_omni_f107()
    with S3B_CSV.open("r", encoding="utf-8-sig") as f:
        s3b_rows = list(csv.DictReader(f))

    deconf_rows = []
    for r in s3b_rows:
        eid = r["event_id"]
        sta = r["verified_gnss_station_id"]
        aligned_fp = ALIGNED_DIR / f"{eid}_{sta}_aligned_hourly_v001.csv"

        ts_rows = []
        with aligned_fp.open("r", encoding="utf-8") as af:
            for ar in csv.DictReader(af):
                ts = ar["timestamp_utc"]
                hr = int(ts[11:13])
                ztd = float(ar["ztd_mm"]) if ar["ztd_mm"] != "" else None
                iwv = float(ar["iwv_kgm2"]) if ar["iwv_kgm2"] != "" else None
                vtec = float(ar["code_gim_vtec_tecu"]) if ar["code_gim_vtec_tecu"] != "" else None
                ts_rows.append({
                    "ts": ts,
                    "rel_hours": int(ar["rel_hours"]),
                    "hour": hr,
                    "is_quiet": ar["is_geomag_quiet"] == "True",
                    "ztd": ztd,
                    "iwv": iwv,
                    "vtec": vtec,
                    "f107": f107_map.get(ts, None),
                })

        slope, f107_ref = fit_f107_slope(ts_rows)
        for tr in ts_rows:
            if tr["vtec"] is not None and tr["f107"] is not None:
                tr["vtec_detrended"] = tr["vtec"] - slope * (tr["f107"] - f107_ref)
            else:
                tr["vtec_detrended"] = tr["vtec"]

        trop_key = "iwv" if r["trop_variable_used"] == "IWV" else "ztd"

        # Equal 15-day causal baseline, equal 10-day (240 h) evaluation windows, equal 1-10d lag:
        # Placebo: [-20d, -11d] (-480h to -241h) vs baseline [-35d, -21d] (-840h to -481h)
        # Target : [-10d, -1d]  (-240h to -1h)   vs baseline [-25d, -11d] (-600h to -241h)
        placebo = score_lag_matched_window(ts_rows, -35 * 24, -21 * 24 - 1, -20 * 24, -11 * 24 - 1, trop_key)
        target = score_lag_matched_window(ts_rows, -25 * 24, -11 * 24 - 1, -10 * 24, -1, trop_key)

        deconf_rows.append({
            "event_id": eid,
            "origin_time_utc": r["origin_time_utc"],
            "magnitude": r["magnitude"],
            "depth_km": r["depth_km"],
            "frozen_macro_region_v001": r["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": r["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": r["stage1d_analysis_role_v001"],
            "verified_gnss_station_id": sta,
            "verified_gnss_distance_km": r["verified_gnss_distance_km"],
            "trop_variable_used": r["trop_variable_used"],
            "f107_vtec_slope_tecu_per_sfu": f"{slope:.4f}",
            "placebo_trop_max_z": f"{placebo['trop_max_z']:.3f}",
            "target_trop_max_z": f"{target['trop_max_z']:.3f}",
            "placebo_trop_q95_z": f"{placebo['trop_q95_z']:.3f}",
            "target_trop_q95_z": f"{target['trop_q95_z']:.3f}",
            "placebo_vtec_detr_max_z": f"{placebo['vtec_max_z']:.3f}",
            "target_vtec_detr_max_z": f"{target['vtec_max_z']:.3f}",
            "placebo_vtec_detr_q95_z": f"{placebo['vtec_q95_z']:.3f}",
            "target_vtec_detr_q95_z": f"{target['vtec_q95_z']:.3f}",
            "placebo_joint_hits_ge_2p5": placebo["joint_hits"],
            "target_joint_hits_ge_2p5": target["joint_hits"],
        })

    out_csv = ANALYSIS_DIR / "stage3c_deconfounded_results_v001.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(deconf_rows[0].keys()))
        w.writeheader()
        w.writerows(deconf_rows)

    shallow = [x for x in deconf_rows if x["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET"]
    null_ctrl = [x for x in deconf_rows if x["stage1d_analysis_role_v001"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    # Compute formal test summary table
    stat_rows = []
    metrics = [
        ("Troposphere Max |Z| (Lag-Matched 15d Causal)", "placebo_trop_max_z", "target_trop_max_z"),
        ("Troposphere 95th-Pct |Z| (Lag-Matched 15d Causal)", "placebo_trop_q95_z", "target_trop_q95_z"),
        ("Quiet GIM VTEC Max |Z| (F10.7-Detrended + Lag-Matched)", "placebo_vtec_detr_max_z", "target_vtec_detr_max_z"),
        ("Quiet GIM VTEC 95th-Pct |Z| (F10.7-Detrended + Lag-Matched)", "placebo_vtec_detr_q95_z", "target_vtec_detr_q95_z"),
    ]
    for label, p_col, t_col in metrics:
        sh_p = [float(x[p_col]) for x in shallow]
        sh_t = [float(x[t_col]) for x in shallow]
        nc_t = [float(x[t_col]) for x in null_ctrl]

        auc_vs_placebo = roc_auc(sh_t, sh_p)
        p_wilcox = wilcoxon_paired_greater_p([t - p for t, p in zip(sh_t, sh_p)])
        auc_vs_null = roc_auc(sh_t, nc_t)
        p_mw = mann_whitney_greater_p(sh_t, nc_t)

        stat_rows.append({
            "metric": label,
            "shallow_n": len(shallow),
            "shallow_placebo_median": f"{median_and_mad(sh_p)[0]:.2f}",
            "shallow_target_median": f"{median_and_mad(sh_t)[0]:.2f}",
            "auc_target_vs_placebo": f"{auc_vs_placebo:.3f}",
            "wilcoxon_p_target_gt_placebo": f"{p_wilcox:.4f}",
            "null_control_n": len(null_ctrl),
            "null_control_target_median": f"{median_and_mad(nc_t)[0]:.2f}",
            "auc_shallow_vs_null_control": f"{auc_vs_null:.3f}",
            "mann_whitney_p_shallow_gt_null": f"{p_mw:.4f}",
        })

    stat_csv = ANALYSIS_DIR / "stage3c_hypothesis_test_summary_v001.csv"
    with stat_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(stat_rows[0].keys()))
        w.writeheader()
        w.writerows(stat_rows)

    tex_path = ANALYSIS_DIR / "stage3c_falsification_table.tex"
    tex_lines = [
        r"% Auto-generated Stage 3C Lag-Matched & F10.7-Deconfounded Falsification Table",
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Stage 3C Lag-Matched ($15\,\text{d}$ Causal Baseline) and Solar-$F_{10.7}$-Deconfounded Falsification Benchmark Across Tier-1 ($d \le 150\,\text{km}$, $M \ge 7.0$) Earthquakes ($N = 43$: $34$ Primary Shallow Targets vs.\ $9$ Deep/Outer-Rise Null Controls).}",
        r"\label{tab:stage3c_falsification}",
        r"\begin{tabular}{lccccccc}",
        r"\hline",
        r"\textbf{Deconfounded Observable} & \textbf{Placebo Med.} & \textbf{Target Med.} & \textbf{AUC (T vs P)} & \textbf{$p_{\text{Wilc}}$} & \textbf{Null-Ctrl Med.} & \textbf{AUC (S vs NC)} & \textbf{$p_{\text{MW}}$} \\",
        r"\hline",
    ]
    short_names = [
        r"Trop.\ $\max\lvert Z\rvert$ (ZTD/IWV)",
        r"Trop.\ $Q_{95}\lvert Z\rvert$ (ZTD/IWV)",
        r"Quiet VTEC $\max\lvert Z\rvert$ ($F_{10.7}$-adj.)",
        r"Quiet VTEC $Q_{95}\lvert Z\rvert$ ($F_{10.7}$-adj.)",
    ]
    for sname, sr in zip(short_names, stat_rows):
        tex_lines.append(
            f"{sname} & {sr['shallow_placebo_median']} & {sr['shallow_target_median']} & "
            f"{sr['auc_target_vs_placebo']} & {sr['wilcoxon_p_target_gt_placebo']} & "
            f"{sr['null_control_target_median']} & {sr['auc_shallow_vs_null_control']} & "
            f"{sr['mann_whitney_p_shallow_gt_null']} \\\\"
        )
    tex_lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table*}",
    ])
    tex_path.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")

    md_out = OUT_DIR / "STAGE3C_DECONFOUNDED_FALSIFICATION_v001.md"
    md_out.write_text(
        "# Stage 3C - Lag-Matched & Solar-F10.7-Deconfounded Falsification Audit (v001)\n\n"
        "Tests whether apparent pre-seismic excursions survive equal-lag (`15d` causal baseline, `10d` evaluation window) "
        "and solar `F10.7` EUV de-trending across Primary Shallow Targets (`N = 34`) vs. Physical Null Controls (`N = 9`).\n",
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
        'Write-Host "ALL CHECKS PASSED (Stage 3C deconfounded falsification tables SHA-256 verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE3C_DECONFOUNDED_FALSIFICATION_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage3c_deconfounded_results_v001.csv",
        "analysis/stage3c_hypothesis_test_summary_v001.csv",
        "analysis/stage3c_falsification_table.tex",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print("Stage 3C Deconfounded Hypothesis Test Summary:")
    for sr in stat_rows:
        print(
            f"  {sr['metric']:56s} | Placebo={sr['shallow_placebo_median']} vs Target={sr['shallow_target_median']} "
            f"(AUC={sr['auc_target_vs_placebo']}, p={sr['wilcoxon_p_target_gt_placebo']}) | "
            f"NullCtrl={sr['null_control_target_median']} (AUC_S_vs_NC={sr['auc_shallow_vs_null_control']}, p={sr['mann_whitney_p_shallow_gt_null']})"
        )


if __name__ == "__main__":
    main()
