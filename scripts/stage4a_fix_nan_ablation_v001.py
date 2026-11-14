import csv
import hashlib
import math
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S3C_RES = ROOT / "reports/stage3c/deconfounded_falsification_v001/analysis/stage3c_deconfounded_results_v001.csv"
OUT_DIR = ROOT / "reports/stage4a/benchmark_synthesis_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"


def is_valid_num(v: float) -> bool:
    return v is not None and not math.isnan(v) and not math.isinf(v)


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


def fit_and_predict_loeo(samples: list[dict], feat_keys: list[str]) -> tuple[list[float], list[int], int]:
    """Leave-One-Event-Out standardized L2 logistic regression on valid non-NaN windows."""
    valid = [s for s in samples if all(is_valid_num(s[k]) for k in feat_keys)]
    event_ids = sorted({s["event_id"] for s in valid})
    preds = [0.5] * len(valid)

    for hold_eid in event_ids:
        train_idx = [i for i, s in enumerate(valid) if s["event_id"] != hold_eid]
        test_idx = [i for i, s in enumerate(valid) if s["event_id"] == hold_eid]

        means = []
        stds = []
        for k in feat_keys:
            vals = [valid[i][k] for i in train_idx]
            m = sum(vals) / len(vals)
            v = sum((x - m) ** 2 for x in vals) / max(1, len(vals) - 1)
            means.append(m)
            stds.append(max(1e-6, math.sqrt(v)))

        x_tr = [[(valid[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)] for i in train_idx]
        y_tr = [valid[i]["label"] for i in train_idx]

        d = len(feat_keys)
        w = [0.0] * d
        b = 0.0
        lr = 0.08
        l2 = 1.0
        n_tr = len(x_tr)

        for _ in range(250):
            gw = [0.0] * d
            gb = 0.0
            for xi, yi in zip(x_tr, y_tr):
                raw_z = b + sum(wj * xij for wj, xij in zip(w, xi))
                z = max(-20.0, min(20.0, raw_z))
                p = 1.0 / (1.0 + math.exp(-z))
                err = p - yi
                gb += err
                for j in range(d):
                    gw[j] += err * xi[j]
            b -= lr * (gb / n_tr)
            for j in range(d):
                w[j] -= lr * ((gw[j] / n_tr) + l2 * w[j])

        for i in test_idx:
            xi = [(valid[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)]
            raw_z = b + sum(wj * xij for wj, xij in zip(w, xi))
            z = max(-20.0, min(20.0, raw_z))
            preds[i] = 1.0 / (1.0 + math.exp(-z))

    return preds, [s["label"] for s in valid], len(event_ids)


def main() -> None:
    with S3C_RES.open("r", encoding="utf-8-sig") as f:
        s3c_rows = list(csv.DictReader(f))

    shallow_samples = []
    null_samples = []
    storm_blanked = []

    for r in s3c_rows:
        mag = float(r["magnitude"])
        dist = float(r["verified_gnss_distance_km"])
        role = r["stage1d_analysis_role_v001"]

        p_vtec_max = float(r["placebo_vtec_detr_max_z"])
        t_vtec_max = float(r["target_vtec_detr_max_z"])
        if not is_valid_num(p_vtec_max) or not is_valid_num(t_vtec_max):
            storm_blanked.append((r["event_id"], r["origin_time_utc"][:10], role, p_vtec_max, t_vtec_max))

        p_sample = {
            "event_id": r["event_id"],
            "label": 0,
            "mag": mag,
            "dist_km": dist,
            "trop_max_z": float(r["placebo_trop_max_z"]),
            "trop_q95_z": float(r["placebo_trop_q95_z"]),
            "vtec_max_z": p_vtec_max,
            "vtec_q95_z": float(r["placebo_vtec_detr_q95_z"]),
            "joint_hits": float(r["placebo_joint_hits_ge_2p5"]),
            "joint_prod": float(r["placebo_trop_max_z"]) * p_vtec_max if is_valid_num(p_vtec_max) else float("nan"),
        }
        t_sample = {
            "event_id": r["event_id"],
            "label": 1,
            "mag": mag,
            "dist_km": dist,
            "trop_max_z": float(r["target_trop_max_z"]),
            "trop_q95_z": float(r["target_trop_q95_z"]),
            "vtec_max_z": t_vtec_max,
            "vtec_q95_z": float(r["target_vtec_detr_q95_z"]),
            "joint_hits": float(r["target_joint_hits_ge_2p5"]),
            "joint_prod": float(r["target_trop_max_z"]) * t_vtec_max if is_valid_num(t_vtec_max) else float("nan"),
        }

        if role == "PRIMARY_SHALLOW_TARGET":
            shallow_samples.extend([p_sample, t_sample])
        else:
            null_samples.extend([p_sample, t_sample])

    print(f"Storm-blanked VTEC windows (0 quiet hours in 10d window): {len(storm_blanked)} event(s)")
    for sb in storm_blanked:
        print(f"  {sb[0]} ({sb[1]}, {sb[2]}): placebo_vtec={sb[3]}, target_vtec={sb[4]}")

    models = [
        ("M1_Seismicity_Station_Baseline", r"M1: Seismicity \& Distance Only", ["mag", "dist_km"]),
        ("M2_Troposphere_Deconfounded", r"M2: Troposphere (ZTD/IWV, 15d-lag)", ["trop_max_z", "trop_q95_z"]),
        ("M3_Ionosphere_Quiet_VTEC_F107", r"M3: Quiet GIM VTEC ($F_{10.7}$-adj.)", ["vtec_max_z", "vtec_q95_z"]),
        ("M4_Joint_Trop_VTEC_Concordance", r"M4: Joint Trop $\times$ VTEC Concordance", ["joint_hits", "joint_prod"]),
        ("M5_Full_MultiDomain_Combined", r"M5: Full Multi-Domain Feature Set", ["mag", "dist_km", "trop_max_z", "trop_q95_z", "vtec_max_z", "vtec_q95_z", "joint_hits"]),
    ]

    ablation_rows = []
    for mid, mtex, fkeys in models:
        sh_preds, sh_y, sh_ev_n = fit_and_predict_loeo(shallow_samples, fkeys)
        nc_preds, nc_y, nc_ev_n = fit_and_predict_loeo(null_samples, fkeys)
        sh_auc = roc_auc(sh_preds, sh_y)
        nc_auc = roc_auc(nc_preds, nc_y)
        diff_auc = sh_auc - nc_auc
        ablation_rows.append({
            "model_id": mid,
            "latex_label": mtex,
            "features": ";".join(fkeys),
            "shallow_valid_windows": len(sh_y),
            "shallow_loeo_auc": f"{sh_auc:.3f}",
            "null_control_valid_windows": len(nc_y),
            "null_control_loeo_auc": f"{nc_auc:.3f}",
            "net_physical_specificity_delta_auc": f"{diff_auc:+.3f}",
        })

    abl_csv = ANALYSIS_DIR / "stage4a_loeo_ablation_summary_v001.csv"
    with abl_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ablation_rows[0].keys()))
        w.writeheader()
        w.writerows(ablation_rows)

    abl_tex = ANALYSIS_DIR / "stage4a_ablation_table.tex"
    tex_lines = [
        r"% Auto-generated Stage 4A Leave-One-Event-Out Multi-Domain Ablation Table",
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Leave-One-Event-Out (LOEO) Cross-Validated $\text{ROC-AUC}$ Across Five LAIC-GUARD Domain Ablation Models Comparing Primary Shallow Ruptures ($N = 34$) Against Deep/Outer-Rise Physical Null Controls ($N = 9$) Under Strict Zero-Imputation Storm Masking.}",
        r"\label{tab:stage4a_ablation}",
        r"\begin{tabular}{lcccc}",
        r"\hline",
        r"\textbf{Ablation Model} & \textbf{Valid Win. (S / NC)} & \textbf{Shallow LOEO AUC} & \textbf{Null-Control LOEO AUC} & \textbf{Specificity $\Delta\text{AUC}$ (S $-$ NC)} \\",
        r"\hline",
    ]
    for ar in ablation_rows:
        tex_lines.append(
            f"{ar['latex_label']} & {ar['shallow_valid_windows']} / {ar['null_control_valid_windows']} & "
            f"{ar['shallow_loeo_auc']} & {ar['null_control_loeo_auc']} & {ar['net_physical_specificity_delta_auc']} \\\\"
        )
    tex_lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table*}",
    ])
    abl_tex.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")

    rel_files = [
        "STAGE4A_BENCHMARK_SYNTHESIS_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage4a_loeo_ablation_summary_v001.csv",
        "analysis/stage4a_ablation_table.tex",
        "analysis/laic_guard_numbers.tex",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])


if __name__ == "__main__":
    main()
