import csv
import hashlib
import math
import random
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S4B_EV = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
S1D_CAT = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
OUT_DIR = ROOT / "reports/stage4c/stratified_audit_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
FIG_DIR = OUT_DIR / "figures"

ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)


def roc_auc(scores: list[float], labels: list[int]) -> float:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
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


def fit_and_predict_loeo(samples: list[dict], feat_keys: list[str]) -> list[float]:
    event_ids = sorted({s["event_id"] for s in samples})
    preds = [0.5] * len(samples)
    for hold_eid in event_ids:
        train_idx = [i for i, s in enumerate(samples) if s["event_id"] != hold_eid]
        test_idx = [i for i, s in enumerate(samples) if s["event_id"] == hold_eid]
        means, stds = [], []
        for k in feat_keys:
            vals = [samples[i][k] for i in train_idx]
            m = sum(vals) / len(vals)
            v = sum((x - m) ** 2 for x in vals) / max(1, len(vals) - 1)
            means.append(m)
            stds.append(max(1e-6, math.sqrt(v)))

        x_tr = [[(samples[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)] for i in train_idx]
        y_tr = [samples[i]["label"] for i in train_idx]
        d = len(feat_keys)
        w = [0.0] * d
        b = 0.0
        n_tr = len(x_tr)
        for _ in range(250):
            gw = [0.0] * d
            gb = 0.0
            for xi, yi in zip(x_tr, y_tr):
                z = max(-20.0, min(20.0, b + sum(wj * xij for wj, xij in zip(w, xi))))
                p = 1.0 / (1.0 + math.exp(-z))
                err = p - yi
                gb += err
                for j in range(d):
                    gw[j] += err * xi[j]
            b -= 0.08 * (gb / n_tr)
            for j in range(d):
                w[j] -= 0.08 * ((gw[j] / n_tr) + 1.0 * w[j])

        for i in test_idx:
            xi = [(samples[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)]
            z = max(-20.0, min(20.0, b + sum(wj * xij for wj, xij in zip(w, xi))))
            preds[i] = 1.0 / (1.0 + math.exp(-z))
    return preds


def bootstrap_ci(samples: list[dict], preds: list[float], n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    rng = random.Random(seed)
    by_ev: dict[str, list[tuple[float, int]]] = {}
    for s, p in zip(samples, preds):
        by_ev.setdefault(s["event_id"], []).append((p, s["label"]))
    ev_keys = sorted(by_ev.keys())
    n_ev = len(ev_keys)
    aucs = []
    for _ in range(n_boot):
        sampled = [ev_keys[rng.randrange(n_ev)] for _ in range(n_ev)]
        bs, by = [], []
        for ek in sampled:
            for p, y in by_ev[ek]:
                bs.append(p)
                by.append(y)
        aucs.append(roc_auc(bs, by))
    aucs.sort()
    return aucs[int(0.025 * n_boot)], aucs[int(0.975 * n_boot)]


def build_samples(sub_events: list[dict]) -> list[dict]:
    out = []
    for e in sub_events:
        out.append({
            "event_id": e["event_id"], "label": 0,
            "trop_max": float(e["p_trop_max"]), "trop_q95": float(e["p_trop_q95"]),
            "vtec_max": float(e["p_vtec_max"]), "vtec_q95": float(e["p_vtec_q95"]),
        })
        out.append({
            "event_id": e["event_id"], "label": 1,
            "trop_max": float(e["t_trop_max"]), "trop_q95": float(e["t_trop_q95"]),
            "vtec_max": float(e["t_vtec_max"]), "vtec_q95": float(e["t_vtec_q95"]),
        })
    return out


def main() -> None:
    with S1D_CAT.open("r", encoding="utf-8-sig") as f:
        cat_meta = {r["event_id"]: r for r in csv.DictReader(f)}
    with S4B_EV.open("r", encoding="utf-8-sig") as f:
        events = list(csv.DictReader(f))

    for e in events:
        m = cat_meta[e["event_id"]]
        e["lat"] = float(m["latitude_deg"])
        e["lon"] = float(m["longitude_deg"])
        e["abs_lat"] = abs(e["lat"])

    strata = [
        ("Shallow: Megathrust Interface", r"Shallow: Megathrust Interface",
         [e for e in events if e["stage1c4_final_source_class_v001"] == "MEGATHRUST_INTERFACE_CANDIDATE"]),
        ("Shallow: Crustal / Splay / Strike-Slip", r"Shallow: Crustal / Splay / Non-Interface",
         [e for e in events if e["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET" and e["stage1c4_final_source_class_v001"] != "MEGATHRUST_INTERFACE_CANDIDATE"]),
        ("Null-Control: Intermediate Slab (70-299 km)", r"Null-Ctrl: Intermediate Slab (70--299\,km)",
         [e for e in events if e["stage1c4_final_source_class_v001"].startswith("INTERMEDIATE_INTRASLAB")]),
        ("Null-Control: Deep Slab & Outer-Rise", r"Null-Ctrl: Deep Slab ($\ge 300$\,km) \& Outer-Rise",
         [e for e in events if e["stage1c4_final_source_class_v001"].startswith(("DEEP_INTRASLAB", "OUTER_RISE"))]),
        ("Shallow: Low-Latitude EIA (|lat| <= 25 deg)", r"Shallow: Low-Latitude EIA ($\lvert\text{lat}\rvert \le 25^\circ$)",
         [e for e in events if e["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET" and e["abs_lat"] <= 25.0]),
        ("Shallow: Mid-Latitude (|lat| > 25 deg)", r"Shallow: Mid-Latitude ($\lvert\text{lat}\rvert > 25^\circ$)",
         [e for e in events if e["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET" and e["abs_lat"] > 25.0]),
    ]

    strat_rows = []
    for s_name, s_tex, sub in strata:
        samp = build_samples(sub)
        p_trop = fit_and_predict_loeo(samp, ["trop_max", "trop_q95"])
        p_vtec = fit_and_predict_loeo(samp, ["vtec_max", "vtec_q95"])
        y = [s["label"] for s in samp]

        t_auc = roc_auc(p_trop, y)
        t_lo, t_hi = bootstrap_ci(samp, p_trop)
        v_auc = roc_auc(p_vtec, y)
        v_lo, v_hi = bootstrap_ci(samp, p_vtec)

        strat_rows.append({
            "stratum": s_name,
            "latex_label": s_tex,
            "n_events": len(sub),
            "m2_trop_auc": f"{t_auc:.3f}",
            "m2_trop_ci95": f"[{t_lo:.2f}, {t_hi:.2f}]",
            "m3_vtec_auc": f"{v_auc:.3f}",
            "m3_vtec_ci95": f"[{v_lo:.2f}, {v_hi:.2f}]",
        })

    out_csv = ANALYSIS_DIR / "stage4c_stratified_specificity_v001.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(strat_rows[0].keys()))
        w.writeheader()
        w.writerows(strat_rows)

    tex_path = ANALYSIS_DIR / "stage4c_stratified_table.tex"
    tex_lines = [
        r"% Auto-generated Stage 4C Tectonic Mechanism, Depth, and Latitude Stratification Table",
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Stage 4C Leave-One-Event-Out $\text{ROC-AUC}$ (with 95\% Cluster-Bootstrap CIs) for Deconfounded Troposphere (\textbf{M2}) and $F_{10.7}$-Adjusted Quiet GIM VTEC (\textbf{M3}) Stratified by Rupture Mechanism, Slab Depth, and Equatorial Ionization Anomaly (EIA) Latitude ($N = 111$ Paired Tier-1 Events).}",
        r"\label{tab:stage4c_stratified}",
        r"\begin{tabular}{lccc}",
        r"\hline",
        r"\textbf{Tectonic / Latitude Stratum} & \textbf{Events ($N$)} & \textbf{M2: Trop LOEO AUC} & \textbf{M3: Quiet VTEC LOEO AUC} \\",
        r"\hline",
    ]
    for sr in strat_rows:
        tex_lines.append(
            f"{sr['latex_label']} & {sr['n_events']} & {sr['m2_trop_auc']} {sr['m2_trop_ci95']} & {sr['m3_vtec_auc']} {sr['m3_vtec_ci95']} \\\\"
        )
    tex_lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table*}",
    ])
    tex_path.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")

    # Update master manuscript macros (laic_guard_numbers.tex)
    macros_tex = ANALYSIS_DIR / "laic_guard_numbers.tex"
    macros_tex.write_text(
        "% Auto-generated LAIC-GUARD Complete Benchmark Macros (Stages 1A - 4C)\n"
        "\\newcommand{\\LgTotalGlobalEvents}{1{,}186}\n"
        "\\newcommand{\\LgPilotRegions}{12}\n"
        "\\newcommand{\\LgCorePilotIncluded}{563}\n"
        "\\newcommand{\\LgPrimaryShallowTotal}{378}\n"
        "\\newcommand{\\LgPhysicalNullControlTotal}{185}\n"
        "\\newcommand{\\LgExcludedTotal}{623}\n"
        "\\newcommand{\\LgNearRegionalCohort}{363}\n"
        "\\newcommand{\\LgStageThreeReady}{269}\n"
        "\\newcommand{\\LgTierOneReady}{192}\n"
        "\\newcommand{\\LgTierOneGnssQaPass}{149}\n"
        "\\newcommand{\\LgIonexMapsIngested}{4{,}039}\n"
        "\\newcommand{\\LgPairedTierOneTotal}{111}\n"
        "\\newcommand{\\LgPairedShallowM65}{90}\n"
        "\\newcommand{\\LgPairedNullCtrlM65}{21}\n"
        "\\newcommand{\\LgPairedShallowM70}{26}\n"
        "\\newcommand{\\LgPairedNullCtrlM70}{6}\n"
        "\\newcommand{\\LgAucTropM65}{0.505}\n"
        "\\newcommand{\\LgAucVtecM65}{0.634}\n"
        "\\newcommand{\\LgDeltaAucVtecM65}{+0.163}\n"
        "\\newcommand{\\LgAucVtecM70}{0.649}\n"
        "\\newcommand{\\LgDeltaAucVtecM70}{+0.399}\n",
        encoding="utf-8",
    )

    # Generate 300-DPI publication figure if matplotlib is installed
    fig_rel = None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.2), dpi=300)

        # Panel A: Stage 4B Model Ablation (Shallow vs Null-Control, M >= 6.5)
        s4b_sum = list(csv.DictReader((ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_full_tier1_ablation_v001.csv").open(encoding="utf-8")))
        m65 = [r for r in s4b_sum if r["cohort"] == "ALL_TIER1_M65"]
        labels_a = ["M1: Seismicity", "M2: Trop (ZTD/IWV)", "M3: Quiet VTEC", "M4: Joint Trop×VTEC", "M5: Full Multi-Domain"]
        sh_vals = [float(r["shallow_auc"]) for r in m65]
        nc_vals = [float(r["null_auc"]) for r in m65]

        y_pos = list(range(len(labels_a)))
        ax1.axvline(0.5, color="#555555", linestyle="--", linewidth=1.1, label="Random Chance (0.50)")
        ax1.barh([y - 0.17 for y in y_pos], sh_vals, height=0.32, color="#1f77b4", label="Primary Shallow (N = 90)")
        ax1.barh([y + 0.17 for y in y_pos], nc_vals, height=0.32, color="#d62728", alpha=0.82, label="Physical Null-Control (N = 21)")
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(labels_a, fontsize=9.5)
        ax1.invert_yaxis()
        ax1.set_xlim(0.2, 0.85)
        ax1.set_xlabel("Leave-One-Event-Out ROC-AUC", fontsize=10)
        ax1.set_title("(a) Domain Ablation: Shallow vs. Null-Control (M ≥ 6.5)", fontsize=10.5, fontweight="bold")
        ax1.legend(loc="lower right", fontsize=8.5)
        ax1.grid(axis="x", linestyle=":", alpha=0.5)

        # Panel B: Stage 4C Stratified M2 vs M3 AUC across Tectonic & Latitude Strata
        labels_b = [
            f"Megathrust (N={strat_rows[0]['n_events']})",
            f"Crustal/Splay (N={strat_rows[1]['n_events']})",
            f"Interm. Slab (N={strat_rows[2]['n_events']})",
            f"Deep/Outer-Rise (N={strat_rows[3]['n_events']})",
            f"Shallow EIA |lat|<=25° (N={strat_rows[4]['n_events']})",
            f"Shallow Mid-Lat >25° (N={strat_rows[5]['n_events']})",
        ]
        m2_b = [float(r["m2_trop_auc"]) for r in strat_rows]
        m3_b = [float(r["m3_vtec_auc"]) for r in strat_rows]

        y_pos_b = list(range(len(labels_b)))
        ax2.axvline(0.5, color="#555555", linestyle="--", linewidth=1.1)
        ax2.barh([y - 0.17 for y in y_pos_b], m3_b, height=0.32, color="#2ca02c", label="M3: Quiet VTEC (F10.7-adj.)")
        ax2.barh([y + 0.17 for y in y_pos_b], m2_b, height=0.32, color="#ff7f0e", alpha=0.85, label="M2: Troposphere (ZTD/IWV)")
        ax2.set_yticks(y_pos_b)
        ax2.set_yticklabels(labels_b, fontsize=9)
        ax2.invert_yaxis()
        ax2.set_xlim(0.2, 0.85)
        ax2.set_xlabel("Leave-One-Event-Out ROC-AUC", fontsize=10)
        ax2.set_title("(b) Tectonic Mechanism & Latitude Stratification (N = 111)", fontsize=10.5, fontweight="bold")
        ax2.legend(loc="lower right", fontsize=8.5)
        ax2.grid(axis="x", linestyle=":", alpha=0.5)

        plt.tight_layout()
        fig_path = FIG_DIR / "fig_stage4c_laic_guard_benchmark.png"
        plt.savefig(fig_path, dpi=300)
        plt.close(fig)
        fig_rel = "figures/fig_stage4c_laic_guard_benchmark.png"
    except ImportError:
        print("Note: matplotlib not installed in active Python environment; skipped PNG figure generation.")

    md_out = OUT_DIR / "STAGE4C_STRATIFIED_AUDIT_v001.md"
    md_out.write_text(
        "# Stage 4C - Tectonic Mechanism, Slab Depth, and EIA Latitude Audit (v001)\n\n"
        "Evaluated M2 (Deconfounded Troposphere) and M3 (F10.7-Adjusted Quiet GIM VTEC) across 6 tectonic and latitude strata (`N = 111` paired Tier-1 events).\n",
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
        'Write-Host "ALL CHECKS PASSED (Stage 4C stratified audit, LaTeX macros, and figures verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE4C_STRATIFIED_AUDIT_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage4c_stratified_specificity_v001.csv",
        "analysis/stage4c_stratified_table.tex",
        "analysis/laic_guard_numbers.tex",
    ]
    if fig_rel:
        rel_files.append(fig_rel)

    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])


if __name__ == "__main__":
    main()
