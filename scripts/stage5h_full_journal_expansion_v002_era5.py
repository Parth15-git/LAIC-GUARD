import csv, hashlib, math
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S5B_CSV = ROOT / "reports/stage5b/hardened_audit_v002/analysis/stage5b_hardened_audit_summary_v002.csv"
S5B_ATT = ROOT / "reports/stage5b/hardened_audit_v002/analysis/event_attrition_ledger_v002.csv"
S5C_CSV = ROOT / "reports/stage5c/zero_overlap_equallag_v002/analysis/stage5c_zero_overlap_equallag_v002.csv"
S5E_CSV = ROOT / "reports/stage5e/era5_deconfounded_v002_era5/analysis/stage5e_era5_ablation_summary_v002.csv"
S5E_EV  = ROOT / "reports/stage5e/era5_deconfounded_v002_era5/analysis/stage5e_era5_event_features_v002.csv"

MS_DIR = ROOT / "manuscript"
MS_TABLES = MS_DIR / "tables"
MS_FIGS = MS_DIR / "figures"
OUT_DIR = ROOT / "reports/stage5f/combined_release_v002_era5"

for d in (MS_TABLES, MS_FIGS, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

r5b = {r["stratum_or_model"]: r for r in csv.DictReader(S5B_CSV.open(encoding="utf-8-sig"))}
r5c = {r["model_or_stratum"]: r for r in csv.DictReader(S5C_CSV.open(encoding="utf-8-sig"))}
r5e = {r["model_or_stratum"]: r for r in csv.DictReader(S5E_CSV.open(encoding="utf-8-sig"))}
ev5e = list(csv.DictReader(S5E_EV.open(encoding="utf-8-sig")))

# Ensure Table I has \label{tab:stage1c_summary}
t1_path = MS_TABLES / "stage1c_manuscript_tables.tex"
if t1_path.exists():
    t1_txt = t1_path.read_text(encoding="utf-8")
    if "\\label{" in t1_txt:
        import re
        t1_txt = re.sub(r"\\label\{[^}]+\}", r"\\label{tab:stage1c_summary}", t1_txt)
    else:
        t1_txt = t1_txt.replace("\\caption{", "\\label{tab:stage1c_summary}\\caption{")
    t1_path.write_text(t1_txt, encoding="utf-8")

# 1. Generate Table II: 1,186-Event Attrition Ledger Table
t2_lines = [
    r"% Auto-generated Stage 5H Table II: 1,186-Event Attrition Funnel Ledger",
    r"\begin{table*}[t]",
    r"\centering",
    r"\caption{Complete Row-Level Attrition and Selection Funnel Across All $1{,}186$ Global $M \ge 6.5$ Earthquakes in USGS ComCat (2000--2025) From Stage~1C.1 Reconnaissance to the Final Paired Tier-1 Benchmark Cohort ($N = 111$).}",
    r"\label{tab:stage5b_attrition}",
    r"\resizebox{\textwidth}{!}{%",
    r"\begin{tabular}{llrrl}",
    r"\hline",
    r"\textbf{Pipeline Gate} & \textbf{Disposition Code} & \textbf{Dropped} & \textbf{Remaining} & \textbf{Geophysical / Quality-Control Criterion} \\",
    r"\hline",
    r"Stage 1C.1 & \texttt{GLOBAL\_COMCAT\_M65\_INITIAL} & --- & $1{,}186$ & Exhaustive global USGS ComCat $M \ge 6.5$ census (2000--2025) \\",
    r"Stage 1C.2--1D & \texttt{EXCL\_STAGE1D\_EXCLUDED\_OUTSIDE\_PILOT\_SCOPE} & $545$ & $641$ & Mid-ocean ridges, oceanic transforms, and diffuse outside-pilot zones \\",
    r"Stage 1C.3--1D & \texttt{EXCL\_STAGE1D\_EXCLUDED\_SEPARATED\_ADJACENT\_STRATUM} & $70$ & $571$ & Secondary back-arc / adjacent tectonic buffer zones excluded a priori \\",
    r"Stage 1C.4--1D & \texttt{EXCL\_STAGE1D\_EXCLUDED\_CODA\_MASKED\_EARLY\_AFTERSHOCK} & $8$ & $563$ & Early $\le 48\,\text{h}$ aftershocks masked by mainshock coda (Core Pilot frozen) \\",
    r"Stage 2A--2B & \texttt{EXCL\_STAGE2B\_NO\_ACTIVE\_GNSS\_IN\_RD} & $35$ & $528$ & Zero active UNR continuous GNSS stations within Dobrovolsky radius $R_D$ \\",
    r"Stage 2B & \texttt{EXCL\_STAGE2B\_TIER3\_FAR\_FIELD\_DOBROVOLSKY\_ONLY\_GT\_300KM} & $165$ & $363$ & Nearest active GNSS station at $300\,\text{km} < d \le R_D$ (Near-Regional frozen) \\",
    r"Stage 2C & \texttt{EXCL\_STAGE2C\_QUIET\_DAYS\_LT\_15} & $86$ & $277$ & Fewer than $15$ geomagnetically quiet baseline days ($Kp < 3$, $Dst > -30\,\text{nT}$) \\",
    r"Stage 2C & \texttt{EXCL\_STAGE2C\_NO\_UNR\_TROP\_ZIP} & $8$ & $269$ & Station lacks published UNR \texttt{IGS20/trop} SINEX archive for event year \\",
    r"Stage 3A--4B & \texttt{DEFERRED\_TIER2\_150\_300KM} & $77$ & $192$ & Tier-2 regional stations ($150 < d \le 300\,\text{km}$) held out from Tier-1 near-field \\",
    r"Stage 4B--5C & \texttt{EXCL\_STAGE4B\_QA\_OR\_UNPAIRED\_WINDOW} & $81$ & $111$ & $<80\%$ 5-min raw GNSS completeness or $<12$ quiet hours in disjoint windows \\",
    r"\hline",
    r"\textbf{Final Cohort} & \texttt{INCLUDED\_FINAL\_111\_BENCHMARK} & \textbf{0} & \textbf{111} & \textbf{90 Primary Shallow Targets ($z < 70\,\text{km}$) + 21 Slab/Outer-Rise Controls} \\",
    r"\hline",
    r"\end{tabular}%",
    r"}",
    r"\end{table*}",
]
(MS_TABLES / "stage5b_attrition_ledger_table.tex").write_text("\n".join(t2_lines) + "\n", encoding="utf-8")

# 2. Generate Table III: Baseline Window Design & Sensitivity Audit
t3_lines = [
    r"% Auto-generated Stage 5H Table III: Baseline Window Design & Lag-Symmetry Audit",
    r"\begin{table*}[t]",
    r"\centering",
    r"\caption{Methodological Sensitivity Audit Comparing Overlapping (`v001`), Shared-Baseline Disjoint (`Stage 5B`), and Strictly Non-Overlapping Equal-Lag (`Stage 5C v002`) Calibration Designs on Quiet $F_{10.7}$-Detrended GIM VTEC (M3).}",
    r"\label{tab:stage5b_baseline_audit}",
    r"\resizebox{\textwidth}{!}{%",
    r"\begin{tabular}{llllccc}",
    r"\hline",
    r"\textbf{Calibration Protocol / Stratum} & \textbf{Placebo Cal.\ $\to$ Eval.} & \textbf{Target Cal.\ $\to$ Eval.} & \textbf{Lag Symmetry} & \textbf{Events ($N$)} & \textbf{ROC-AUC [95\% CI]} & \textbf{Paired $p_{\text{Wilc}}$} \\",
    r"\hline",
    r"Overlapping Target Baseline (\texttt{v001} Shallow) & $[-45,-21] \to [-20,-11]$ & $[-35,-11] \to [-10,-1]$ & Equal ($1\text{--}10\,\text{d}$), Overlapped & $90$ & $0.634\ [0.56, 0.71]$ & $0.0002$ \\",
    r"Overlapping Target Baseline (\texttt{v001} Megathrust) & $[-45,-21] \to [-20,-11]$ & $[-35,-11] \to [-10,-1]$ & Overlapped $[-20,-11]$ & $62$ & $0.580\ [0.48, 0.68]$ & $0.0195$ \\",
    r"Overlapping Target Baseline (\texttt{v001} Crustal/Splay) & $[-45,-21] \to [-20,-11]$ & $[-35,-11] \to [-10,-1]$ & Overlapped $[-20,-11]$ & $28$ & $0.733\ [0.62, 0.85]$ & $0.0008$ \\",
    r"\hline",
    r"Shared Disjoint Base ($L=10\,\text{d}$, Shallow) & $[-35,-21] \to [-20,-11]$ & $[-35,-21] \to [-10,-1]$ & Asymmetric ($1\text{--}10$ vs.\ $11\text{--}20\,\text{d}$) & $90$ & " + f"{r5b['Disjoint Fixed Base (L=10d, Base=[-35,-21])']['roc_auc']}\\ {r5b['Disjoint Fixed Base (L=10d, Base=[-35,-21])']['ci95']} & {r5b['Disjoint Fixed Base (L=10d, Base=[-35,-21])']['wilcoxon_p']} \\\\",
    r"Shared Disjoint Wide Base ($L=10\,\text{d}$, Shallow) & $[-45,-21] \to [-20,-11]$ & $[-45,-21] \to [-10,-1]$ & Asymmetric ($1\text{--}10$ vs.\ $11\text{--}20\,\text{d}$) & $90$ & " + f"{r5b['Disjoint Fixed Base (L=10d, Base=[-45,-21])']['roc_auc']}\\ {r5b['Disjoint Fixed Base (L=10d, Base=[-45,-21])']['ci95']} & {r5b['Disjoint Fixed Base (L=10d, Base=[-45,-21])']['wilcoxon_p']} \\\\",
    r"Shared Disjoint Multi-Lag ($L=12\,\text{d}$, Shallow) & $[-39,-25] \to [-24,-13]$ & $[-39,-25] \to [-12,-1]$ & Asymmetric ($1\text{--}12$ vs.\ $13\text{--}24\,\text{d}$) & $90$ & " + f"{r5b['Disjoint Multi-Lag (L=12d, Base=[-39,-25])']['roc_auc']}\\ {r5b['Disjoint Multi-Lag (L=12d, Base=[-39,-25])']['ci95']} & {r5b['Disjoint Multi-Lag (L=12d, Base=[-39,-25])']['wilcoxon_p']} \\\\",
    r"Shared Disjoint Multi-Lag ($L=15\,\text{d}$, Shallow) & $[-45,-31] \to [-30,-16]$ & $[-45,-31] \to [-15,-1]$ & Asymmetric ($1\text{--}15$ vs.\ $16\text{--}30\,\text{d}$) & $90$ & " + f"{r5b['Disjoint Multi-Lag (L=15d, Base=[-45,-31])']['roc_auc']}\\ {r5b['Disjoint Multi-Lag (L=15d, Base=[-45,-31])']['ci95']} & {r5b['Disjoint Multi-Lag (L=15d, Base=[-45,-31])']['wilcoxon_p']} \\\\",
    r"Shared Disjoint Base (Slab / Outer-Rise Controls) & $[-35,-21] \to [-20,-11]$ & $[-35,-21] \to [-10,-1]$ & Asymmetric Drift Leakage & $21$ & " + f"{r5b['M3: Quiet VTEC (Null-Control Slab/Outer)']['roc_auc']}\\ {r5b['M3: Quiet VTEC (Null-Control Slab/Outer)']['ci95']} & {r5b['M3: Quiet VTEC (Null-Control Slab/Outer)']['wilcoxon_p']} \\\\",
    r"\hline",
    r"\textbf{Zero-Overlap Equal-Lag (\texttt{v002} Shallow)} & $[-45,-31] \to [-30,-21]$ & $[-25,-11] \to [-10,-1]$ & \textbf{Strict Equal ($1\text{--}10\,\text{d}$), Disjoint} & $90$ & \textbf{" + f"{r5c['M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)']['roc_auc']}\\ {r5c['M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)']['ci95']}" + r"} & \textbf{" + f"{r5c['M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)']['wilcoxon_p']}" + r"} \\",
    r"\textbf{Zero-Overlap Equal-Lag (\texttt{v002} Megathrust)} & $[-45,-31] \to [-30,-21]$ & $[-25,-11] \to [-10,-1]$ & \textbf{Strict Equal ($1\text{--}10\,\text{d}$), Disjoint} & $62$ & \textbf{" + f"{r5c['M3: Quiet VTEC (Shallow Megathrust)']['roc_auc']}\\ {r5c['M3: Quiet VTEC (Shallow Megathrust)']['ci95']}" + r"} & \textbf{" + f"{r5c['M3: Quiet VTEC (Shallow Megathrust)']['wilcoxon_p']}" + r"} \\",
    r"\textbf{Zero-Overlap Equal-Lag (\texttt{v002} Crustal/Splay)} & $[-45,-31] \to [-30,-21]$ & $[-25,-11] \to [-10,-1]$ & \textbf{Strict Equal ($1\text{--}10\,\text{d}$), Disjoint} & $28$ & " + f"{r5c['M3: Quiet VTEC (Shallow Crustal/Splay)']['roc_auc']}\\ {r5c['M3: Quiet VTEC (Shallow Crustal/Splay)']['ci95']} & {r5c['M3: Quiet VTEC (Shallow Crustal/Splay)']['wilcoxon_p']} \\\\",
    r"\textbf{Zero-Overlap Equal-Lag (\texttt{v002} Slab Controls)} & $[-45,-31] \to [-30,-21]$ & $[-25,-11] \to [-10,-1]$ & \textbf{Strict Equal ($1\text{--}10\,\text{d}$), Disjoint} & $21$ & " + f"{r5c['M3: Quiet VTEC (Null-Control Slab/Outer)']['roc_auc']}\\ {r5c['M3: Quiet VTEC (Null-Control Slab/Outer)']['ci95']} & {r5c['M3: Quiet VTEC (Null-Control Slab/Outer)']['wilcoxon_p']} \\\\",
    r"\hline",
    r"\end{tabular}%",
    r"}",
    r"\end{table*}",
]
(MS_TABLES / "stage5b_baseline_design_table.tex").write_text("\n".join(t3_lines) + "\n", encoding="utf-8")

# 3. Generate Expanded Table IV: Comprehensive Multi-Domain & Stratified Benchmark Table
t4_lines = [
    r"% Auto-generated Stage 5H Table IV: Comprehensive Multi-Domain & Stratified Benchmark Table",
    r"\begin{table*}[t]",
    r"\centering",
    r"\caption{Comprehensive Out-of-Sample Leave-One-Event-Out (LOEO) and Storm-Cluster Cross-Validated $\text{ROC-AUC}$ (95\% Cluster-Bootstrap CIs), $\text{PR-AUC}$, and Paired Wilcoxon $p$-Values Across Tropospheric (\texttt{v002\_era5}), Ionospheric (\texttt{v002}), and Multi-Domain Models.}",
    r"\label{tab:stage5f_combined_benchmark}",
    r"\resizebox{\textwidth}{!}{%",
    r"\begin{tabular}{llcccc}",
    r"\hline",
    r"\textbf{Domain} & \textbf{Ablation Model / Tectonic, Geomagnetic, Coastal \& Era Stratum} & \textbf{Events ($N$)} & \textbf{ROC-AUC [95\% CI]} & \textbf{PR-AUC} & \textbf{Paired $p_{\text{Wilc}}$} \\",
    r"\hline",
]
t4_rows = [
    ("Troposphere", r5e["M2a: Raw GNSS ZTD-Only (Shallow Baseline)"], r"M2a: Raw GNSS ZTD-Only (Shallow Target Cohort)"),
    ("Troposphere", r5e["M2b: Physical GNSS - ERA5 (ZHD+ZWD) Residual (Shallow)"], r"M2b: Uncalibrated $\text{GNSS} - \text{ERA5}$ ($\text{ZHD}+\text{ZWD}$, Shallow)"),
    ("Troposphere", r5e["M2c: Calibrated GNSS - ERA5 Residual (Shallow, Event-LOEO)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow, Event-LOEO)"),
    ("Troposphere", r5e["M2c: Calibrated GNSS - ERA5 Residual (Shallow, Cluster-CV)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow, $\pm 15\,\text{d}$ Cluster-CV)"),
    ("Troposphere", r5e["M2c: Calibrated GNSS - ERA5 Residual (Null-Control Slab)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Slab / Outer-Rise Controls)"),
    ("Troposphere", r5e["M2c: Calibrated GNSS - ERA5 Residual (Megathrust N=62)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow Megathrust Interface)"),
    ("Troposphere", r5e["M2c: Calibrated GNSS - ERA5 Residual (Crustal/Splay N=28)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow Crustal / Splay)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow $M \ge 6.5$, Event-LOEO)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow M>=6.5, Storm-Cluster)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow $M \ge 6.5$, $\pm 15\,\text{d}$ Cluster-CV)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Null-Control Slab/Outer)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Slab / Outer-Rise Candidate Controls)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow Megathrust)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow Megathrust Interface)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow Crustal/Splay)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow Crustal / Splay)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow M>=7.0)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Major Shallow Ruptures $M \ge 7.0$)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow |gm_lat| <= 25 deg)"], r"M3: Quiet GIM VTEC (Low Geomagnetic Latitude $|\lambda_m| \le 25^\circ$, EIA Belt)"),
    ("Ionosphere", r5c["M3: Quiet VTEC (Shallow |gm_lat| > 25 deg)"], r"M3: Quiet GIM VTEC (Mid Geomagnetic Latitude $|\lambda_m| > 25^\circ$)"),
    ("Ionosphere", r5b["Shallow: Modified Dip |modip| > 30 deg"], r"M3: Quiet GIM VTEC (Modified Dip $|\text{modip}| > 30^\circ$, Disjoint Baseline)"),
    ("Ionosphere", r5b["Shallow: Onshore/Near-Coast (<= 50 km)"], r"M3: Quiet GIM VTEC (Near-Field Station $d \le 50\,\text{km}$, Disjoint Baseline)"),
    ("Ionosphere", r5b["Shallow: Offshore/Regional (50-150 km)"], r"M3: Quiet GIM VTEC (Sub-Regional Station $50 < d \le 150\,\text{km}$, Disjoint Baseline)"),
    ("Multi-Domain", r5e["M4_era5: Joint ERA5-Resid + Quiet VTEC (Shallow)"], r"M4$_{\text{ERA5}}$: Joint Calibrated ERA5-Residual + Quiet VTEC Fusion (Shallow)"),
]
for dom, r, lbl in t4_rows:
    t4_lines.append(f"{dom} & {lbl} & {r['n_events']} & {r['roc_auc']} {r['ci95']} & {r['pr_auc']} & {r['wilcoxon_p']} \\\\")
t4_lines.extend([r"\hline", r"\end{tabular}%", r"}", r"\end{table*}"])
(MS_TABLES / "stage5f_combined_benchmark_table.tex").write_text("\n".join(t4_lines) + "\n", encoding="utf-8")

# 4. Generate Figure 2: 300-DPI Three-Panel Journal Diagnostic Figure
fig2_path = MS_FIGS / "fig_stage5h_journal_diagnostics.png"
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15.6, 4.9), dpi=300)

# Panel (a): 1,186 -> 111 Cohort Funnel
funnel_stages = [
    ("Global M>=6.5\nComCat", 1186, "#4c72b0"),
    ("Core Pilot\n(12 Regions)", 563, "#4c72b0"),
    ("Near-Regional\n(d <= 300 km)", 363, "#55a868"),
    ("Quiet Baseline\n(>=15d + ZIP)", 269, "#55a868"),
    ("Tier-1 Near-Field\n(d <= 150 km)", 192, "#c44e52"),
    ("Raw >=80%\nGNSS QA Pass", 149, "#c44e52"),
    ("Final Paired\nBenchmark", 111, "#8172b2"),
]
for idx, (lbl, cnt, col) in enumerate(funnel_stages):
    ax1.barh(idx, cnt, height=0.58, color=col, alpha=0.88, edgecolor="black", linewidth=0.7)
    ax1.text(cnt + 22, idx, f"{cnt}", va="center", fontsize=8.5, fontweight="bold")
ax1.set_yticks(range(len(funnel_stages)))
ax1.set_yticklabels([x[0] for x in funnel_stages], fontsize=8.3)
ax1.invert_yaxis()
ax1.set_xlim(0, 1360)
ax1.set_xlabel("Number of Earthquakes (N)", fontsize=9.2)
ax1.set_title("(a) Zero-Imputation Cohort Funnel", fontsize=10.2, fontweight="bold", pad=14)
ax1.grid(axis="x", linestyle=":", alpha=0.5)

# Panel (b): Within-event paired anomaly shift (\Delta Q95 = Target - Placebo)
def mean_se(vals):
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / max(1, len(vals) - 1))
    return m, 1.96 * sd / math.sqrt(len(vals))

mega_ev = [e for e in ev5e if e["role"] == "PRIMARY_SHALLOW_TARGET" and e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"]
crus_ev = [e for e in ev5e if e["role"] == "PRIMARY_SHALLOW_TARGET" and e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"]
null_ev = [e for e in ev5e if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

groups = [("Megathrust\n(N = 62)", mega_ev), ("Crustal / Splay\n(N = 28)", crus_ev), ("Slab / Outer-Rise\nControls (N = 21)", null_ev)]
ax2.axvline(0.0, color="#555555", linestyle="--", linewidth=1.1)
for idx, (glbl, g_ev) in enumerate(groups):
    d_cal = [float(e["t_cal_q95"]) - float(e["p_cal_q95"]) for e in g_ev]
    d_vtc = [float(e["t_vtec_q95"]) - float(e["p_vtec_q95"]) for e in g_ev]
    mc, ec = mean_se(d_cal)
    mv, ev_ci = mean_se(d_vtc)
    ax2.barh(idx - 0.17, mc, height=0.31, color="#17becf", alpha=0.9, label="M2c: ERA5 Residual ΔQ95" if idx == 0 else "")
    ax2.errorbar(mc, idx - 0.17, xerr=ec, fmt="none", ecolor="black", elinewidth=1.2, capsize=3)
    ax2.barh(idx + 0.17, mv, height=0.31, color="#2ca02c", alpha=0.9, label="M3: Quiet VTEC ΔQ95" if idx == 0 else "")
    ax2.errorbar(mv, idx + 0.17, xerr=ev_ci, fmt="none", ecolor="black", elinewidth=1.2, capsize=3)
ax2.set_yticks(range(len(groups)))
ax2.set_yticklabels([g[0] for g in groups], fontsize=8.8)
ax2.invert_yaxis()
ax2.set_xlabel("Paired Within-Event Shift ΔQ95 (σ_MAD units)", fontsize=9.2)
ax2.set_title("(b) Paired Target - Placebo Shift (ΔQ95)", fontsize=10.2, fontweight="bold", pad=22)
ax2.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=True, fontsize=7.6)
ax2.grid(axis="x", linestyle=":", alpha=0.5)

# Panel (c): Ionospheric Subgroup & Era Sensitivity
sub_items = [
    (r5c["M3: Quiet VTEC (Shallow |gm_lat| > 25 deg)"], "Geomag |λm| > 25° (N=33)", "#2ca02c"),
    (r5c["M3: Quiet VTEC (Shallow |gm_lat| <= 25 deg)"], "Geomag |λm| <= 25° (N=57)", "#17becf"),
    (r5b["Shallow: Modified Dip |modip| > 30 deg"], "Modip > 30° (N=47)", "#1f77b4"),
    (r5b["Shallow: Onshore/Near-Coast (<= 50 km)"], "Dist d <= 50 km (N=31)", "#9467bd"),
    (r5b["Shallow: Offshore/Regional (50-150 km)"], "Dist 50-150 km (N=59)", "#8c564b"),
    (r5c["M3: Quiet VTEC (Shallow M>=7.0)"], "Major M >= 7.0 (N=26)", "#e377c2"),
]
ax3.axvline(0.5, color="#555555", linestyle="--", linewidth=1.1)
for idx, (r, slbl, col) in enumerate(sub_items):
    auc = float(r["roc_auc"])
    lo, hi = [float(x) for x in r["ci95"].strip("[]").split(",")]
    ax3.barh(idx, auc, height=0.52, color=col, alpha=0.88)
    ax3.errorbar(auc, idx, xerr=[[auc - lo], [hi - auc]], fmt="none", ecolor="black", elinewidth=1.2, capsize=3)
ax3.set_yticks(range(len(sub_items)))
ax3.set_yticklabels([x[1] for x in sub_items], fontsize=8.4)
ax3.invert_yaxis()
ax3.set_xlim(0.30, 0.85)
ax3.set_xlabel("Out-of-Sample ROC-AUC (95% Bootstrap CI)", fontsize=9.2)
ax3.set_title("(c) Ionospheric Subgroup Sensitivity (M3)", fontsize=10.2, fontweight="bold", pad=14)
ax3.grid(axis="x", linestyle=":", alpha=0.5)

plt.tight_layout()
plt.savefig(fig2_path, dpi=300)
plt.close(fig)

# 5. Expand references.bib to 18 peer-reviewed journal references
(MS_DIR / "references.bib").write_text(
    "@article{dobrovolsky1979,\n"
    "  author={Dobrovolsky, I. P. and Zubkov, S. I. and Miachkin, V. I.},\n"
    "  title={Estimation of the size of earthquake preparation zones},\n"
    "  journal={Pure and Applied Geophysics}, volume={117}, number={5}, pages={1025--1044}, year={1979},\n"
    "  doi={10.1007/BF00876083}\n}\n\n"
    "@article{pulinets2011,\n"
    "  author={Pulinets, S. and Ouzounov, D.},\n"
    "  title={Lithosphere--Atmosphere--Ionosphere Coupling ({LAIC}) model -- An unified concept for earthquake precursors validation},\n"
    "  journal={Journal of Asian Earth Sciences}, volume={41}, number={4--5}, pages={371--382}, year={2011},\n"
    "  doi={10.1016/j.jseaes.2010.03.005}\n}\n\n"
    "@article{blewitt2018,\n"
    "  author={Blewitt, G. and Hammond, W. C. and Kreemer, C.},\n"
    "  title={Harnessing the {GPS} data explosion for interdisciplinary science},\n"
    "  journal={Eos}, volume={99}, year={2018}, doi={10.1029/2018EO104623}\n}\n\n"
    "@article{hasterok2022,\n"
    "  author={Hasterok, D. and Halpin, J. A. and Collins, A. S. and Hand, M. and Kreemer, C. and Gard, M. G. and Glorie, S.},\n"
    "  title={New maps of global geological provinces and tectonic plates},\n"
    "  journal={Earth-Science Reviews}, volume={231}, pages={104069}, year={2022},\n"
    "  doi={10.1016/j.earscirev.2022.104069}\n}\n\n"
    "@article{schaer1999,\n"
    "  author={Schaer, S. and Gurtner, W. and Feltens, J.},\n"
    "  title={{IONEX}: The {IONosphere} Map {EXchange} Format Version 1},\n"
    "  journal={Proceedings of the IGS AC Workshop}, pages={233--247}, year={1999}\n}\n\n"
    "@article{diaz2026,\n"
    "  author={D{\\'i}az, J. and others},\n"
    "  title={Artificial Intelligence and Total Electron Content in Earthquake-Related Seismo-Ionospheric Analysis: A Mapping Review},\n"
    "  journal={Geomatics}, volume={6}, number={4}, pages={74}, year={2026}, doi={10.3390/geomatics6040074}\n}\n\n"
    "@article{chaniadakis2025,\n"
    "  author={Chaniadakis, I. and others},\n"
    "  title={Are Ionospheric Disturbances Spatiotemporally Invariant Earthquake Precursors? A Multi-Decadal 100-Station Study},\n"
    "  journal={Applied Sciences}, volume={15}, number={24}, pages={13218}, year={2025}, doi={10.3390/app152413218}\n}\n\n"
    "@article{wen2026,\n"
    "  author={Wen, Y. and Liu, J.-Y. and others},\n"
    "  title={A Hybrid Approach Using Statistics and Unsupervised Learning to Investigate the Impact of Ionospheric Storm Disturbances on Pre-Earthquake Total Electron Content Anomalies},\n"
    "  journal={IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing}, volume={19}, pages={23747--23759}, year={2026},\n"
    "  doi={10.1109/JSTARS.2026.3709918}\n}\n\n"
    "@article{hersbach2020,\n"
    "  author={Hersbach, H. and others},\n"
    "  title={The {ERA5} global reanalysis},\n"
    "  journal={Quarterly Journal of the Royal Meteorological Society}, volume={146}, number={730}, pages={1999--2049}, year={2020},\n"
    "  doi={10.1002/qj.3803}\n}\n\n"
    "@article{bevis1992,\n"
    "  author={Bevis, M. and Businger, S. and Herring, T. A. and Rocken, C. and Anthes, R. A. and Ware, R. H.},\n"
    "  title={{GPS} meteorology: Remote sensing of atmospheric water vapor using the Global Positioning System},\n"
    "  journal={Journal of Geophysical Research: Atmospheres}, volume={97}, number={D14}, pages={15787--15801}, year={1992},\n"
    "  doi={10.1029/92JD01517}\n}\n\n"
    "@incollection{saastamoinen1972,\n"
    "  author={Saastamoinen, J.},\n"
    "  title={Atmospheric correction for the troposphere and stratosphere in radio ranging of satellites},\n"
    "  booktitle={The Use of Artificial Satellites for Geodesy}, volume={15}, pages={247--251}, year={1972},\n"
    "  publisher={American Geophysical Union}, doi={10.1029/GM015p0247}\n}\n\n"
    "@article{davis1985,\n"
    "  author={Davis, J. L. and Herring, T. A. and Shapiro, I. I. and Rogers, A. E. E. and Elgered, G.},\n"
    "  title={Geodesy by radio interferometry: Effects of atmospheric modeling errors on estimates of baseline length},\n"
    "  journal={Radio Science}, volume={20}, number={6}, pages={1593--1607}, year={1985}, doi={10.1029/RS020i006p01593}\n}\n\n"
    "@article{he2017,\n"
    "  author={He, L. and Heki, K.},\n"
    "  title={Ionospheric anomalies immediately before $M_w$ 7.0--8.0 earthquakes},\n"
    "  journal={Journal of Geophysical Research: Space Physics}, volume={122}, number={8}, pages={8659--8678}, year={2017},\n"
    "  doi={10.1002/2017JA024012}\n}\n\n"
    "@article{heki2011,\n"
    "  author={Heki, K.},\n"
    "  title={Ionospheric electron enhancement preceding the 2011 {Tohoku-Oki} earthquake},\n"
    "  journal={Geophysical Research Letters}, volume={38}, number={17}, pages={L17312}, year={2011},\n"
    "  doi={10.1029/2011GL047908}\n}\n\n"
    "@article{jordan2011,\n"
    "  author={Jordan, T. H. and Chen, Y.-T. and Gasparini, P. and Madariaga, R. and Main, I. and Marzocchi, W. and Papadopoulos, G. and Sobolev, G. and Yamaoka, K. and Zschau, J.},\n"
    "  title={Operational earthquake forecasting: State of knowledge and guidelines for utilization},\n"
    "  journal={Annals of Geophysics}, volume={54}, number={4}, pages={315--391}, year={2011}, doi={10.4401/ag-5350}\n}\n\n"
    "@article{kossobokov2020,\n"
    "  author={Kossobokov, V. G. and Panza, G. F.},\n"
    "  title={Myth of short-term earthquake predictions: Ionospheric precursors},\n"
    "  journal={Pure and Applied Geophysics}, volume={177}, pages={1627--1636}, year={2020}\n}\n\n"
    "@article{bird2003,\n"
    "  author={Bird, P.},\n"
    "  title={An updated digital model of plate boundaries},\n"
    "  journal={Geochemistry, Geophysics, Geosystems}, volume={4}, number={3}, pages={1027}, year={2003},\n"
    "  doi={10.1029/2001GC000252}\n}\n\n"
    "@article{ekstrom2012,\n"
    "  author={Ekstr{\\\"o}m, G. and Nettles, M. and Dziewo{\\'n}ski, A. M.},\n"
    "  title={The global {CMT} project 2004--2010: Centroid-moment tensors for 13,017 earthquakes},\n"
    "  journal={Physics of the Earth and Planetary Interiors}, volume={200--201}, pages={1--9}, year={2012},\n"
    "  doi={10.1016/j.pepi.2012.04.002}\n}\n",
    encoding="utf-8",
)

# 6. Write Full-Length IEEE Journal Manuscript (manuscript/main.tex)
(MS_DIR / "main.tex").write_text(
    r"""\documentclass[journal]{IEEEtran}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}

\input{laic_guard_numbers.tex}

\markboth{IEEE TRANSACTIONS ON GEOSCIENCE AND REMOTE SENSING, VOL.~XX, NO.~X, NOVEMBER~2026}%
{JICHKAR: LAIC-GUARD DECONFOUNDED MULTI-DOMAIN EARTHQUAKE PRECURSOR BENCHMARK (2000--2025)}

\title{LAIC-GUARD: A Deconfounded Multi-Domain Benchmark for Lithosphere--Atmosphere--Ionosphere Earthquake Precursors (2000--2025)}

\author{Parth~Nilesh~Jichkar%
\thanks{Manuscript received November 15, 2026. All benchmark datasets, deterministic verification manifests, and reproducible pipeline scripts (\texttt{tag: v002\_era5}) are archived at \url{https://github.com/Parth15-git/LAIC-GUARD}.}%
\thanks{P.~N.~Jichkar is with the Department of Electronics and Communication Engineering, MIT World Peace University, Pune 411038, Maharashtra, India (e-mail: parthjichkar939@gmail.com).}}

\begin{document}
\maketitle

\begin{abstract}
Retrospective studies of pre-seismic anomalies in Global Navigation Satellite System (GNSS) tropospheric zenith delay and ionospheric vertical total electron content (VTEC) frequently suffer from post-hoc case selection, overlapping calibration and evaluation windows, unmodeled synoptic weather variability, solar and geomagnetic storm leakage, and the absence of deep-source physical negative controls. We introduce \textbf{LAIC-GUARD}, a reproducible, zero-imputation multi-domain falsification and evaluation benchmark spanning all \LgTotalGlobalEvents{} global $M \ge 6.5$ earthquakes recorded in the USGS ComCat catalogue between 2000 and 2025. By integrating tectonic province overlays, centroid moment-tensor adjudication, and Dobrovolsky strain-radius ($R_D = 10^{0.43M}$\,km) spatial pairing across Nevada Geodetic Laboratory (UNR) continuous GNSS tropospheric solutions, hourly ECMWF ERA5 meteorological reanalysis, CODE AIUB global ionosphere maps (\LgIonexMapsIngested{} daily IONEX files), and NASA OMNIWeb geomagnetic and solar indices, we deterministically isolate \LgPairedTierOneTotal{} within-event paired near-field ($d \le 150$\,km) earthquakes (\LgPairedShallowMain{} primary shallow crustal and megathrust targets at $z < 70$\,km vs.\ \LgPairedNullCtrlMain{} intermediate/deep intraslab and outer-rise candidate negative controls). Under strictly non-overlapping, equal-lag ($1\text{--}10$\,d) out-of-sample evaluation, raw GNSS zenith total delay (ZTD) exhibits no statistically distinguishable discriminative skill over pre-event placebo windows ($\text{ROC-AUC} = \LgAucZtdRaw$, $95\%$ CI $[0.44, 0.60]$, $p_{\text{Wilc}} = 0.1233$). However, subtracting synoptic hydrostatic and wet delay via causal baseline-calibrated ERA5 reanalysis uncovers a non-meteorological tropospheric residual ($\text{ROC-AUC} = \LgAucEraCal$, $95\%$ CI $[0.55, 0.70]$, $p_{\text{Wilc}} = 0.0009$; $\LgAucEraCalCluster$ under $\pm 15$\,d storm-cluster cross-validation) that closely parallels solar-$F_{10.7}$-detrended, geomagnetically quiet GIM VTEC ($\text{ROC-AUC} = \LgAucVtecMain$, $95\%$ CI $[0.56, 0.70]$, $p_{\text{Wilc}} = 0.0010$; $\LgAucVtecClusterCv$ under cluster cross-validation). Independently across both atmospheric layers, discriminative skill concentrates in large-area shallow megathrust interface ruptures ($\text{AUC} = \LgAucEraMegathrust$ and $\LgAucVtecMegathrust$, $N=62$) while remaining indistinguishable from random chance on shallow crustal and splay faults ($\LgAucEraCrustal$ and $\LgAucVtecCrustal$, $N=28$) and deep-slab/outer-rise negative controls ($\LgAucEraNullCtrl$ and $\LgAucVtecNullCtrl$, $N=21$). Joint multi-domain fusion reaches $\text{ROC-AUC} = \LgAucJointEraVtec$ ($95\%$ CI $[0.56, 0.72]$), establishing a transparent statistical baseline for seismo-atmospheric coupling research.
\end{abstract}

\begin{IEEEkeywords}
Lithosphere--atmosphere--ionosphere coupling (LAIC), GNSS meteorology, zenith total delay (ZTD), ERA5 reanalysis, global ionosphere maps (GIM), vertical total electron content (VTEC), earthquake precursor falsification benchmark.
\end{IEEEkeywords}

\section{Introduction}
\IEEEPARstart{T}{he} Lithosphere--Atmosphere--Ionosphere Coupling (LAIC) hypothesis posits that tectonic stress accumulation within the earthquake preparation zone prior to major ruptures induces measurable perturbations across the lower atmosphere and ionosphere \cite{dobrovolsky1979,pulinets2011}. Proposed physical coupling pathways include: (i) microfracturing-driven volatile and radon exhalation that alters boundary-layer air conductivity and latent heat release \cite{pulinets2011}; (ii) pre-seismic crustal deformation and surface thermal anomalies exciting atmospheric acoustic-gravity waves (AGWs) that propagate upward into the thermosphere; and (iii) direct stressed-rock charge-carrier activation and electrodynamic $\mathbf{E} \times \mathbf{B}$ plasma redistribution in the ionospheric F-region \cite{heki2011,he2017}.

Despite hundreds of retrospective case reports over the past two decades, whether pre-seismic tropospheric and ionospheric anomalies carry reproducible, out-of-sample discriminative skill remains intensely debated \cite{jordan2011,kossobokov2020,chaniadakis2025,diaz2026}. Recent multi-decadal mapping reviews and multi-station audits identify five pervasive methodological vulnerabilities in the existing literature \cite{chaniadakis2025,diaz2026,wen2026}:
\begin{enumerate}
    \item \textbf{Post-Hoc Event and Station Cherry-Picking:} Restricting evaluation to a handful of famous $M_w \ge 7.0$ mainshocks without accounting for the full global earthquake population or reporting the station-selection attrition funnel.
    \item \textbf{Overlapping and Asymmetric Baseline Leakage:} Using sliding 15--30 day running medians where the pre-event target window shares calibration epochs with the control window, or where the target window is separated from its calibration baseline by a longer temporal lag than the placebo window.
    \item \textbf{Unmodeled Synoptic Meteorology in GNSS Tropospheric Series:} Treating raw GNSS zenith total delay (ZTD) or precipitable water vapor (PWV) spikes as lithospheric signals without removing frontal barometric pressure drops and synoptic moisture advection \cite{bevis1992,hersbach2020}.
    \item \textbf{Solar EUV Drift and Geomagnetic Storm Contamination:} Attributing equatorial ionization anomaly (EIA) enhancements or post-storm ionospheric disturbances to impending earthquakes without simultaneously masking geomagnetic storms ($Kp$, $Dst$) and detrending 27-day solar rotation ($F_{10.7}$) trends \cite{wen2026}.
    \item \textbf{Absence of Physical Negative Controls:} Failing to verify that any putative lithosphere-to-ionosphere coupling vanishes (or degrades to chance) on deep-focus intraslab ruptures ($z \ge 70$\,km) and oceanic outer-rise bending earthquakes where upper-crustal fluid/gas release and continental boundary-layer coupling are physically suppressed.
\end{enumerate}

To resolve these limitations, we construct \textbf{LAIC-GUARD} (\texttt{v002\_era5}), a fully reproducible, zero-imputation multi-domain benchmark auditing all \LgTotalGlobalEvents{} global $M \ge 6.5$ earthquakes from 2000 through 2025. The primary contributions of this paper are fivefold:
\begin{enumerate}
    \item \textbf{Exhaustive Global Catalogue Funnel and Tectonic Adjudication:} We audit all \LgTotalGlobalEvents{} USGS ComCat $M \ge 6.5$ earthquakes using digital plate-boundary and geological province models \cite{bird2003,hasterok2022} and W-phase/GCMT moment tensors \cite{ekstrom2012}, publishing a complete row-level attrition ledger down to \LgPairedTierOneTotal{} within-event paired near-field ($d \le 150$\,km) events (\LgPairedShallowMain{} primary shallow targets and \LgPairedNullCtrlMain{} deep-slab/outer-rise candidate negative controls).
    \item \textbf{SINEX Tropospheric Schema Audit and Strict Zero-Imputation QC:} We audit 176 multi-year Nevada Geodetic Laboratory (UNR) \texttt{IGS20/trop} SINEX archives \cite{blewitt2018}, demonstrating that standard UNR `.trop` files provide total zenith delay (\texttt{TROTOT}) and horizontal gradients rather than direct integrated water vapor (\texttt{IWV}), and enforcing a strict $\ge 80\%$ 5-minute data completeness gate without gap interpolation.
    \item \textbf{Baseline Overlap and Lag-Symmetry Falsification Audit:} We prove empirically that shared disjoint baselines introduce a 10-day lag asymmetry that inflates deep-slab null controls to $\text{AUC} = 0.601$, while overlapping target baselines artificially invert crustal versus megathrust performance. Enforcing strictly non-overlapping, equal-lag ($1\text{--}10$\,d) calibration restores deep-slab controls to chance ($\text{AUC} = \LgAucVtecNullCtrl$).
    \item \textbf{Causal Station-Level ERA5 Meteorological Deconfounding:} Using collocated hourly ECMWF ERA5 reanalysis \cite{hersbach2020}, we show that while raw GNSS ZTD lies at random chance ($\text{AUC} = \LgAucZtdRaw$), removing hydrostatic and wet weather delay via causal baseline ordinary least squares (OLS) calibration isolates a significant non-meteorological ZTD residual ($\text{AUC} = \LgAucEraCal$, $p_{\text{Wilc}} = 0.0009$).
    \item \textbf{Cross-Layer Convergence on Megathrust Interfaces:} We demonstrate that independently deconfounded tropospheric residuals (M2c) and quiet $F_{10.7}$-adjusted GIM VTEC (M3) exhibit identical tectonic specificity: both concentrate in shallow megathrust interface ruptures ($\text{AUC} = \LgAucEraMegathrust$ and $\LgAucVtecMegathrust$, $N=62$), both drop to chance on shallow crustal/splay faults ($\LgAucEraCrustal$ and $\LgAucVtecCrustal$, $N=28$), and both remain at chance on deep-slab/outer-rise controls ($\LgAucEraNullCtrl$ and $\LgAucVtecNullCtrl$, $N=21$).
\end{enumerate}

\section{Global Catalogue Adjudication and Attrition Funnel (2000--2025)}

\subsection{USGS ComCat Census and Tectonic Province Overlay}
We begin with an exhaustive, count-verified census of all \LgTotalGlobalEvents{} global earthquakes with magnitude $M \ge 6.5$ occurring between January 1, 2000 (`00:00:00 UTC`) and December 31, 2025 (`23:59:59 UTC`) in the USGS Comprehensive Earthquake Catalogue (ComCat). Rather than selecting events with known ionospheric anomalies, every earthquake is deterministically georeferenced against the Hasterok et al.\ (2022) global geological provinces and plate-boundary dataset \cite{hasterok2022} and the PB2002 digital plate model \cite{bird2003}.

Events occurring along mid-ocean spreading ridges, remote oceanic transform faults, or diffuse oceanic intraplate domains lacking near-field land geodetic networks ($N = 545$), together with $70$ events situated in separated secondary back-arc buffer strata, are excluded prior to time-series inspection. This leaves \LgStageOneCRegionalTotal{} regional candidate earthquakes distributed across \LgPilotRegions{} convergent and collisional macro-regions (Table~\ref{tab:stage1c_summary}).

\input{tables/stage1c_manuscript_tables.tex}

\subsection{Moment-Tensor Mechanism Adjudication and Negative Controls}
To separate ruptures capable of direct upper-crustal lithospheric coupling from deep or oceanic bending sources, we retrieve USGS ComCat and Global Centroid-Moment-Tensor (GCMT) focal mechanisms \cite{ekstrom2012} for all \LgStageOneCRegionalTotal{} regional candidates. First, \LgCodaMaskedExcluded{} early aftershocks occurring within $48\,\text{h}$ and inside the rupture zone of a preceding $M \ge 7.0$ mainshock are excluded (`EXCL_STAGE1D_EXCLUDED_CODA_MASKED_EARLY_AFTERSHOCK`) because their pre-event windows are contaminated by mainshock co-seismic and post-seismic deformation, freezing the Core Pilot catalogue at \LgCorePilotIncluded{} events.

Second, each of the \LgCorePilotIncluded{} Core Pilot earthquakes is assigned to one of two pre-specified analytical roles:
\begin{itemize}
    \item \textbf{Primary Shallow Targets ($z < 70$\,km, $N = \LgPrimaryShallowTotal$):} Comprising $209$ low-angle subduction megathrust interface candidates (thrust rake $45^\circ \le \lambda \le 135^\circ$, dip $\delta \le 35^\circ$, within $250$\,km landward of the trench axis) and $169$ shallow upper-plate crustal, strike-slip, or splay-fault ruptures.
    \item \textbf{Candidate Physical Negative Controls ($N = \LgPhysicalNullControlTotal$):} Comprising $87$ intermediate-depth intraslab ruptures ($70 \le z < 300$\,km), $73$ deep-focus slab ruptures ($z \ge 300$\,km), and $25$ trenchward oceanic outer-rise normal-faulting events. Because intraslab earthquakes nucleate within the cold subducting lithosphere beneath the Moho and asthenospheric wedge, and outer-rise ruptures occur in Flexural oceanic lithosphere seaward of the trench, they serve as natural within-network negative controls for testing whether putative anomalies are merely artifacts of regional climatology or space weather.
\end{itemize}

\subsection{Complete 1,186-Event Attrition Funnel}
Table~\ref{tab:stage5b_attrition} and Fig.~\ref{fig:journal_diagnostics}(a) document the complete, zero-imputation attrition funnel from the initial \LgTotalGlobalEvents{} global events to the final \LgPairedTierOneTotal{}-event near-field benchmark cohort. Every excluded event is logged with an explicit disposition code and SHA-256 hash in \texttt{metadata/event\_exclusions.csv}.

\input{tables/stage5b_attrition_ledger_table.tex}

\section{Multi-Domain Geophysical Data Architecture and Quality Control}

\subsection{Dobrovolsky Strain-Radius GNSS Pairing and SINEX Schema Audit}
For each of the \LgCorePilotIncluded{} Core Pilot earthquakes, we compute the theoretical Dobrovolsky preparation-zone radius \cite{dobrovolsky1979}:
\begin{equation}
    R_D = 10^{0.43 M}\quad (\text{km}),
    \label{eq:dobrovolsky}
\end{equation}
which spans from $R_D = 623.7$\,km at $M = 6.5$ to $R_D = 2{,}754.2$\,km at $M = 8.0$. Cross-matching event origin times and epicenters against the full 23,839-station Nevada Geodetic Laboratory (UNR) continuous GNSS holdings \cite{blewitt2018} identifies \LgNearRegionalCohort{} near-regional events with at least one active station at epicentral distance $d \le 300$\,km (excluding $35$ events with no active station inside $R_D$ and $165$ Tier-3 far-field events with $300\,\text{km} < d \le R_D$).

To prevent atmospheric attenuation over hundreds of kilometers from diluting localized boundary-layer signals, primary evaluation is restricted to \textbf{Tier-1 near-field stations} ($d \le 150$\,km, \LgTierOneReady{} archive-ready events after removing $86$ events with $<15$ quiet baseline days and $8$ events lacking published UNR `.trop` archives). Under our strict zero-imputation rule (\texttt{preserve\_missing: true}), the nearest Tier-1 station must achieve $\ge 80\%$ raw 5-minute epoch completeness across the 50-day window $[-45\,\text{d}, +5\,\text{d}]$, which is satisfied by \LgTierOneGnssQaPass{} events ($111$ of which retain $\ge 12$ geomagnetically quiet hourly samples in every disjoint baseline and evaluation sub-window).

During our Stage~5C schema audit of all 176 multi-year UNR \texttt{IGS20/trop} SINEX archives, we verified that standard UNR tropospheric solution blocks (\texttt{+TROP/SOLUTION}) contain strictly seven columns:
\begin{equation*}
    \texttt{SITE} \quad \texttt{EPOCH} \quad \texttt{TROTOT} \quad \texttt{STDDEV} \quad \texttt{TGNTOT} \quad \texttt{STDDEV} \quad \texttt{TGETOT} \quad \texttt{STDDEV}
\end{equation*}
Crucially, auxiliary meteorological columns (\texttt{PRESS}, \texttt{TEMP}, \texttt{IWV}) are absent from standard UNR \texttt{IGS20} `.trop` distributions. Consequently, pipeline implementations that fall back to fixed positional column index~8 when the string \texttt{"IWV"} is absent inadvertently parse horizontal gradient standard deviations, producing artificial variance compression and spurious false-alarm inflation. In LAIC-GUARD, we enforce strict header-token validation and evaluate verified 5-minute \texttt{TROTOT} ($\text{ZTD}_{\text{GNSS}}$, bounded within $[1000, 3500]$\,mm) aggregated into exact UTC hourly means.

\subsection{ECMWF ERA5 Meteorological Reanalysis Forward Model}
Because raw $\text{ZTD}_{\text{GNSS}}$ is dominated by barometric pressure systems (zenith hydrostatic delay, $\text{ZHD} \approx 2100\text{--}2300$\,mm) and synoptic tropospheric water vapor (zenith wet delay, $\text{ZWD} \approx 20\text{--}350$\,mm), we collocate hourly ECMWF ERA5 reanalysis fields \cite{hersbach2020}—surface pressure $P_s(t)$ (hPa), 2-m air temperature $T_{2\text{m}}(t)$ (K), 2-m dew-point temperature $T_d(t)$ ($^\circ\text{C}$), and total column integrated water vapour $\text{TCWV}(t)$ ($\text{kg}\,\text{m}^{-2}$)—at the exact geodetic coordinates $(\phi_s, \lambda_s, H_{\text{km}})$ of each paired Tier-1 GNSS station across $[-45\,\text{d}, +5\,\text{d}]$.

Using the Saastamoinen (1972) and Davis et al.\ (1985) formulation \cite{saastamoinen1972,davis1985}, hourly reanalysis hydrostatic delay (in mm) is computed as:
\begin{equation}
    \text{ZHD}_{\text{ERA5}}(t) = \frac{2.2768 \, P_s(t)}{1 - 0.00266 \cos(2\phi_s) - 0.00028 \, H_{\text{km}}}.
    \label{eq:zhd}
\end{equation}
Following Bevis et al.\ (1992) \cite{bevis1992}, we estimate the water-vapor-weighted mean atmospheric temperature $T_m(t)$ (K) and dimensionless inverse conversion factor $\Pi^{-1}(t)$:
\begin{align}
    T_m(t) &= 70.2 + 0.72 \, T_{2\text{m}}(t), \label{eq:tm} \\
    \Pi^{-1}(t) &= 10^{-6} R_v \left(\frac{k_3}{T_m(t)} + k_2'\right), \label{eq:pi_inv}
\end{align}
where $R_v = 461.5\,\text{J}\,\text{kg}^{-1}\,\text{K}^{-1}$, $k_3 = 3.739 \times 10^5\,\text{K}^2\,\text{hPa}^{-1}$, and $k_2' = 22.1\,\text{K}\,\text{hPa}^{-1}$. The ERA5 wet and total zenith delays (in mm) are then:
\begin{align}
    \text{ZWD}_{\text{ERA5}}(t) &= 10^3 \, \Pi^{-1}(t) \, \text{TCWV}(t), \label{eq:zwd} \\
    \text{ZTD}_{\text{ERA5}}(t) &= \text{ZHD}_{\text{ERA5}}(t) + \text{ZWD}_{\text{ERA5}}(t). \label{eq:ztd_era5}
\end{align}

\subsection{CODE AIUB GIM IONEX and NASA OMNIWeb Space-Weather Ingestion}
To audit the ionospheric layer concurrently, we ingest \LgIonexMapsIngested{} daily Global Ionosphere Map (GIM) files in IONEX format produced by the Center for Orbit Determination in Europe (CODE, Astronomical Institute, University of Bern) \cite{schaer1999}, spanning years 2000--2025 ($2.5^\circ$ latitude $\times 5.0^\circ$ longitude spatial grid; 2-hour cadence during 2000--2014 and 1-hour cadence during 2015--2025). For each hourly map epoch, vertical total electron content ($\text{VTEC}$, in $\text{TECU}$, $1\,\text{TECU} = 10^{16}\,\text{el}\,\text{m}^{-2}$) is bilinearly interpolated from the four surrounding grid nodes to the earthquake epicenter $(\phi_e, \lambda_e)$.

Hourly planetary geomagnetic indices ($Kp$, $Dst$) and solar $10.7$\,cm radio flux ($F_{10.7}$, in sfu) are ingested from NASA GSFC OMNIWeb low-resolution archives. An hourly epoch $t$ is classified as \textbf{geomagnetically quiet} if and only if:
\begin{equation}
    t \in \mathcal{Q} \iff Kp(t) < 3.0 \quad \text{and} \quad Dst(t) > -30\,\text{nT}.
    \label{eq:quiet_mask}
\end{equation}

\section{Deconfounding Methodology and Zero-Overlap Equal-Lag Protocol}

\subsection{Eliminating Baseline Overlap and Temporal Lag Asymmetry}
A critical flaw in retrospective precursor studies is calibrating a pre-seismic target window $w_1 = [-10\,\text{d}, -1\,\text{d}]$ against an immediately preceding 25-day baseline $[-35\,\text{d}, -11\,\text{d}]$ while evaluating a placebo window $w_0 = [-20\,\text{d}, -11\,\text{d}]$ that overlaps the target's calibration baseline. Conversely, if both $w_0 = [-20\,\text{d}, -11\,\text{d}]$ and $w_1 = [-10\,\text{d}, -1\,\text{d}]$ are calibrated against a single shared disjoint baseline $\mathcal{B} = [-35\,\text{d}, -21\,\text{d}]$, the target window sits $11\text{--}20\,\text{d}$ after the baseline whereas the placebo window sits only $1\text{--}10\,\text{d}$ after the baseline. Under seasonal tropospheric drift or 27-day solar EUV rotation, this 10-day lag asymmetry systematically inflates target-window variance even on non-seismic series.

To eliminate both overlap and lag asymmetry simultaneously, LAIC-GUARD (\texttt{v002}) enforces a **strictly non-overlapping, equal-lag ($1\text{--}10\,\text{d}$) paired design**:
\begin{align}
    \text{Placebo Pair:} \quad \mathcal{B}_0 &= [-45\,\text{d}, -31\,\text{d}] \xrightarrow{\text{lag } 1\text{--}10\,\text{d}} w_0 = [-30\,\text{d}, -21\,\text{d}], \label{eq:pair_plac} \\
    \text{Target Pair:} \quad \mathcal{B}_1 &= [-25\,\text{d}, -11\,\text{d}] \xrightarrow{\text{lag } 1\text{--}10\,\text{d}} w_1 = [-10\,\text{d}, -1\,\text{d}]. \label{eq:pair_targ}
\end{align}
Here $\mathcal{B}_0, w_0, \mathcal{B}_1, w_1$ form four mutually disjoint time intervals prior to $t_0$ (with $[-1\,\text{d}, 0]$ held out as a co-seismic guard band), and both $w_0$ and $w_1$ are evaluated across identical $10\,\text{d}$ durations at an identical $1\text{--}10\,\text{d}$ forward lag from their respective $15\,\text{d}$ causal baselines.

\subsection{Causal Station-Level ERA5 Transfer Calibration (\texttt{M2c})}
Because ERA5 fields represent $0.25^\circ \times 0.25^\circ$ ($\sim 28\,\text{km}$) areal averages, the reanalysis model orography differs from the exact GPS monument altitude by up to $300\text{--}1{,}200\,\text{m}$ along steep coastal subduction zones (e.g., Andes, Japan, Kuril, Sumatra). Direct uncalibrated subtraction $r_{\text{raw}}(t) = \text{ZTD}_{\text{GNSS}}(t) - \text{ZTD}_{\text{ERA5}}(t)$ (\textbf{Model M2b}) therefore leaves a terrain-dependent hydrostatic scale mismatch $\beta_s \ne 1$ that injects synoptic barometric variance into the difference series.

In \textbf{Model M2c}, we fit a station-specific affine transfer function $(\hat{\alpha}_k, \hat{\beta}_k)$ via ordinary least squares (OLS) strictly inside each causal baseline $\mathcal{B}_k$ ($k \in \{0, 1\}$), with zero access to evaluation epochs $w_k$:
\begin{equation}
    (\hat{\alpha}_k, \hat{\beta}_k) = \arg\min_{\alpha,\beta} \sum_{t \in \mathcal{B}_k} \left[\text{ZTD}_{\text{GNSS}}(t) - \left(\alpha + \beta \, \text{ZTD}_{\text{ERA5}}(t)\right)\right]^2,
    \label{eq:ols_era5}
\end{equation}
and evaluate the deconfounded residual inside $w_k$:
\begin{equation}
    r_{\text{cal}}^{(k)}(t) = \text{ZTD}_{\text{GNSS}}(t) - \left(\hat{\alpha}_k + \hat{\beta}_k \, \text{ZTD}_{\text{ERA5}}(t)\right), \quad t \in \mathcal{B}_k \cup w_k.
    \label{eq:res_cal}
\end{equation}

\subsection{Quiet-Time Solar $F_{10.7}$ Detrending (\texttt{M3}) and Diurnal MAD Scoring}
For \textbf{Model M3}, all storm-disturbed epochs ($t \notin \mathcal{Q}$) are masked prior to baseline fitting and window scoring. To remove slow solar cycle and 27-day EUV rotation trends without leaking pre-event target data, linear regression of quiet-time $\text{VTEC}(t)$ against $F_{10.7}(t)$ is fitted exclusively on the union of quiet baseline epochs $\mathcal{B}_{\text{quiet}} = (\mathcal{B}_0 \cup \mathcal{B}_1) \cap \mathcal{Q}$:
\begin{equation}
    \widetilde{\text{VTEC}}(t) = \text{VTEC}(t) - \hat{\gamma}_{\mathcal{B}} \left(F_{10.7}(t) - \bar{F}_{10.7,\mathcal{B}}\right), \quad t \in \mathcal{Q}.
    \label{eq:vtec_detrend}
\end{equation}

To account for strong diurnal cycles in both tropospheric moisture and ionospheric photoionization, any candidate series $x(t) \in \{\text{ZTD}_{\text{GNSS}}, r_{\text{raw}}, r_{\text{cal}}, \widetilde{\text{VTEC}}\}$ is standardized separately for each UTC hour of the day $h \in \{0, 1, \dots, 23\}$ using the causal baseline median $m_{h,k}$ and Median Absolute Deviation ($\text{MAD}$) scale $\sigma_{h,k}$ computed strictly over $\{t \in \mathcal{B}_k : \text{hour}(t) = h\}$:
\begin{align}
    m_{h,k} &= \text{median}_{t \in \mathcal{B}_{k,h}} x(t), \label{eq:med} \\
    \sigma_{h,k} &= 1.4826 \times \text{median}_{t \in \mathcal{B}_{k,h}} \lvert x(t) - m_{h,k} \rvert, \label{eq:mad} \\
    z_k(t) &= \frac{\lvert x(t) - m_{\text{hour}(t),k} \rvert}{\sigma_{\text{hour}(t),k}}, \quad t \in w_k. \label{eq:zscore}
\end{align}
Each 10-day window $w_k$ ($k=0$ placebo, $k=1$ pre-event target) is summarized by the 2-D extreme-value feature vector:
\begin{equation}
    \mathbf{u}_{e,k} = \begin{bmatrix} \max_{t \in w_k} z_k(t) \\ Q_{0.95}\!\left(\{z_k(t)\}_{t \in w_k}\right) \end{bmatrix},
    \label{eq:feat_vec}
\end{equation}
where $Q_{0.95}$ denotes the 95th percentile across valid hourly epochs in $w_k$. Out-of-sample classification probabilities $\hat{p}_{e,k}$ are generated via L2-regularized logistic regression under both **Leave-One-Event-Out (LOEO)** cross-validation and **Storm-Cluster Cross-Validation** (holding out entire $\pm 15\,\text{d}$ multi-earthquake temporal clusters simultaneously). Statistical significance is assessed via the non-parametric within-event paired Wilcoxon signed-rank test on $\Delta Q_{0.95,e} = Q_{0.95}(w_{e,1}) - Q_{0.95}(w_{e,0})$ and 2,000-replicate event-cluster bootstrap 95\% confidence intervals.

\section{Empirical Benchmark Results and Stratified Audits}

\subsection{Baseline Overlap and Lag-Symmetry Audit (\texttt{Stage 5B} vs.\ \texttt{Stage 5C})}
Table~\ref{tab:stage5b_baseline_audit} demonstrates the necessity of our zero-overlap, equal-lag protocol. When a single disjoint baseline ($[-35\,\text{d}, -21\,\text{d}]$ or $[-45\,\text{d}, -21\,\text{d}]$) is shared between placebo and target windows, the 10-day lag asymmetry causes deep-slab and outer-rise negative controls ($N=21$) to drift upward to $\text{ROC-AUC} = 0.601\ [0.51, 0.70]$ ($p_{\text{Wilc}} = 0.0722$). Furthermore, in the preliminary \texttt{v001} design where the target baseline $[-35\,\text{d}, -11\,\text{d}]$ overlapped the placebo window $[-20\,\text{d}, -11\,\text{d}]$, elevated variance during $[-20\,\text{d}, -11\,\text{d}]$ prior to large megathrust ruptures inflated the target denominator $\sigma_{h,1}$, artificially depressing megathrust skill to $0.580$ while inflating crustal/splay events to $0.733$.

Restoring strict zero-overlap and equal $1\text{--}10\,\text{d}$ lag (\texttt{v002}, bottom rows of Table~\ref{tab:stage5b_baseline_audit}) eliminates both artifacts: deep-slab/outer-rise negative controls drop to random chance ($\text{AUC} = \LgAucVtecNullCtrl$, $p_{\text{Wilc}} = 0.3641$), while shallow megathrust interface ruptures emerge as the primary physical driver ($\text{AUC} = \LgAucVtecMegathrust$, $p_{\text{Wilc}} = 0.0005$) and shallow crustal/splay faults fall to chance ($\text{AUC} = \LgAucVtecCrustal$, $p_{\text{Wilc}} = 0.2437$).

\input{tables/stage5b_baseline_design_table.tex}

\subsection{Tropospheric ERA5 Deconfounding Progression (\texttt{M2a} $\to$ \texttt{M2c})}
Table~\ref{tab:stage5f_combined_benchmark} and Fig.~\ref{fig:benchmark_v002_combined}(a) present the complete multi-domain ablation across all \LgPairedTierOneTotal{} paired Tier-1 events:
\begin{itemize}
    \item \textbf{M2a (Raw GNSS ZTD-Only):} Evaluated across the \LgPairedShallowMain{} primary shallow earthquakes, raw GNSS ZTD yields $\text{ROC-AUC} = \LgAucZtdRaw$ ($95\%$ CI $[0.44, 0.60]$, $\text{PR-AUC} = 0.518$, $p_{\text{Wilc}} = 0.1233$), confirming that unadjusted tropospheric delay provides no statistically distinguishable pre-seismic skill under equal-lag calibration.
    \item \textbf{M2b (Uncalibrated $\text{GNSS} - \text{ERA5}$ Difference):} Directly subtracting physical $\text{ZTD}_{\text{ERA5}}$ (\ref{eq:ztd_era5}) without station elevation/scale calibration degrades performance to $\text{ROC-AUC} = \LgAucEraUncal$ ($[0.34, 0.50]$), reflecting $0.25^\circ$ grid-topography mismatch in coastal mountain belts.
    \item \textbf{M2c (Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual):} Fitting the causal station transfer model (\ref{eq:ols_era5}) removes topographic scale bias and synoptic barometric/moisture variance, uncovering a statistically significant positive residual on shallow targets: $\text{ROC-AUC} = \LgAucEraCal$ ($95\%$ CI $[0.55, 0.70]$, $\text{PR-AUC} = 0.636$, $p_{\text{Wilc}} = 0.0009$) under Event-LOEO, and $\text{ROC-AUC} = \LgAucEraCalCluster$ ($[0.54, 0.70]$) under $\pm 15\,\text{d}$ storm-cluster cross-validation. Crucially, the exact same M2c pipeline applied to the \LgPairedNullCtrlMain{} deep-slab and outer-rise negative controls yields $\text{ROC-AUC} = \LgAucEraNullCtrl$ ($[0.33, 0.67]$, $p_{\text{Wilc}} = 0.3383$).
\end{itemize}

\input{tables/stage5f_combined_benchmark_table.tex}

\begin{figure*}[t]
\centering
\includegraphics[width=0.96\textwidth]{figures/fig_stage5f_combined_benchmark.png}
\caption{LAIC-GUARD (\texttt{v002} + \texttt{v002\_era5}) zero-overlap, equal-lag ($1\text{--}10$\,d) out-of-sample $\text{ROC-AUC}$ with 95\% cluster-bootstrap confidence intervals across (a) progressive meteorological and ionospheric deconfounding models ($N = \LgPairedShallowMain$), and (b) tectonic mechanism and candidate negative-control strata.}
\label{fig:benchmark_v002_combined}
\end{figure*}

\subsection{Cross-Layer Tectonic Specificity and Subgroup Sensitivity}
Comparing Fig.~\ref{fig:benchmark_v002_combined}(b) and Fig.~\ref{fig:journal_diagnostics}(b) reveals a striking physical convergence between the lower atmosphere (M2c) and ionosphere (M3):
\begin{enumerate}
    \item \textbf{Shallow Megathrust Interface Ruptures ($N=62$):} Both layers achieve their highest discriminative performance on subduction megathrust interfaces, with M2c reaching $\text{ROC-AUC} = \LgAucEraMegathrust$ ($[0.58, 0.76]$, $\text{PR-AUC} = 0.719$, $p_{\text{Wilc}} = 0.0004$) and M3 reaching $\text{ROC-AUC} = \LgAucVtecMegathrust$ ($[0.57, 0.73]$, $\text{PR-AUC} = 0.579$, $p_{\text{Wilc}} = 0.0005$). As shown in Fig.~\ref{fig:journal_diagnostics}(b), within-event paired 95th-percentile anomalies shift positively ($\Delta Q_{0.95} > 0$) in both domains specifically for megathrust events.
    \item \textbf{Shallow Crustal and Splay Faults ($N=28$):} Both layers drop to random chance on smaller-area continental and upper-plate splay faults: $\text{ROC-AUC} = \LgAucEraCrustal$ ($p_{\text{Wilc}} = 0.2509$) for M2c and $\text{ROC-AUC} = \LgAucVtecCrustal$ ($p_{\text{Wilc}} = 0.2437$) for M3.
    \item \textbf{Geomagnetic Latitude and Coastal Proximity (Fig.~\ref{fig:journal_diagnostics}c):} Stratifying M3 by dipole geomagnetic latitude $\lambda_m$ shows comparable skill inside the Equatorial Ionization Anomaly belt ($\lvert\lambda_m\rvert \le 25^\circ$, $N=57$, $\text{AUC} = \LgAucVtecGeomagLow$, $p_{\text{Wilc}} = 0.0293$) and at mid-latitudes ($\lvert\lambda_m\rvert > 25^\circ$, $N=33$, $\text{AUC} = \LgAucVtecGeomagHigh$, $p_{\text{Wilc}} = 0.0035$), refuting claims of a sharp $25^\circ$ latitude cutoff. Similarly, stations within $d \le 50$\,km ($N=31$, $\text{AUC} = 0.631$) slightly outperform stations at $50 < d \le 150$\,km ($N=59$, $\text{AUC} = 0.612$).
    \item \textbf{Multi-Domain Fusion (\texttt{M4\_ERA5}):} Combining the two M2c tropospheric residual features with the two M3 quiet-VTEC features in a 4-feature out-of-sample LOEO classifier achieves $\text{ROC-AUC} = \LgAucJointEraVtec$ ($95\%$ CI $[0.56, 0.72]$, $\text{PR-AUC} = 0.637$, $p_{\text{Wilc}} = 0.0009$), outperforming either single-domain model across the full $N=90$ shallow cohort.
\end{enumerate}

\begin{figure*}[t]
\centering
\includegraphics[width=0.98\textwidth]{figures/fig_stage5h_journal_diagnostics.png}
\caption{LAIC-GUARD diagnostic synthesis: (a) deterministic zero-imputation selection waterfall from $1{,}186$ global ComCat earthquakes to the $111$ paired Tier-1 cohort; (b) within-event paired anomaly shift $\Delta Q_{0.95} = Q_{0.95}(w_1) - Q_{0.95}(w_0)$ (mean $\pm 95\%$ CI in $\sigma_{\text{MAD}}$ units) showing cross-layer convergence on megathrust ruptures ($N=62$) and null shifts on crustal ($N=28$) and slab/outer-rise control ($N=21$) strata; and (c) ionospheric M3 sensitivity across geomagnetic dipole latitude, modified dip, station proximity, and magnitude.}
\label{fig:journal_diagnostics}
\end{figure*}

\section{Physical Interpretation, Limitations, and Discussion}

\subsection{Why Do Anomalies Concentrate in Megathrust Interfaces?}
The independent convergence of ERA5-deconfounded GNSS tropospheric residuals ($\text{AUC} = \LgAucEraMegathrust$) and solar-detrended quiet GIM VTEC ($\text{AUC} = \LgAucVtecMegathrust$) on shallow subduction megathrusts—while crustal/splay faults ($\LgAucEraCrustal, \LgAucVtecCrustal$) and deep-slab controls ($\LgAucEraNullCtrl, \LgAucVtecNullCtrl$) remain at chance—offers an important physical clue. Subduction megathrust earthquakes involve coherent pre-seismic locking and slow-slip strain accumulation across fault patches tens to hundreds of kilometers wide along coastal ocean--land boundaries \cite{heki2011,he2017}. By contrast, continental strike-slip and upper-plate splay ruptures at $M \sim 6.5\text{--}7.0$ have compact preparation zones whose localized boundary-layer perturbations are rapidly dispersed by horizontal winds and sub-grid turbulence below the spatial resolution of $2.5^\circ \times 5.0^\circ$ GIM IONEX maps.

\subsection{Methodological Limitations and Operational Caveats}
In accordance with international guidelines for earthquake forecasting validation \cite{jordan2011,kossobokov2020}, four methodological limitations must be emphasized:
\begin{enumerate}
    \item \textbf{Causal OLS Non-Stationarity in \texttt{M2c}:} Because $\hat{\alpha}_k, \hat{\beta}_k$ in (\ref{eq:ols_era5}) are fitted separately on $\mathcal{B}_0 = [-45\,\text{d}, -31\,\text{d}]$ and $\mathcal{B}_1 = [-25\,\text{d}, -11\,\text{d}]$ to prevent future leakage, rapid seasonal regime transitions between baseline windows can influence residual scaling. However, the null result on the \LgPairedNullCtrlMain{} slab/outer-rise controls ($\text{AUC} = \LgAucEraNullCtrl$, $p_{\text{Wilc}} = 0.3383$) rules out a generic regression artifact.
    \item \textbf{Coarse Spatial Resolution of GIM IONEX:} Global IONEX maps smooth ionospheric structure over $2.5^\circ \times 5.0^\circ$ cells. Future extensions incorporating station-specific slant TEC (sTEC) from raw RINEX observations may sharpen near-field sensitivity.
    \item \textbf{Control Cohort Sample Size ($N=21$):} While \LgPhysicalNullControlTotal{} deep-slab and outer-rise controls were frozen in Stage~1D, requiring a Tier-1 station within $d \le 150$\,km and $\ge 80\%$ 5-minute completeness reduced the paired control sample to $N = \LgPairedNullCtrlMain{}$, resulting in wider bootstrap confidence intervals ($[0.32, 0.71]$). Expanding evaluation to Tier-2 stations ($150 < d \le 300$\,km, $N = 77$ deferred events) is a priority for future work.
    \item \textbf{Statistical Benchmark vs.\ Operational Forecasting:} An out-of-sample $\text{ROC-AUC}$ of $0.642\text{--}0.672$ demonstrates a statistically reproducible geophysical association above random chance, but yields substantial false-alarm rates under extreme base-rate imbalance in continuous daily monitoring \cite{jordan2011,chaniadakis2025}. LAIC-GUARD should therefore be interpreted as a deconfounded physical benchmark rather than an operational earthquake warning system.
\end{enumerate}

\section{Conclusion}
We have presented \textbf{LAIC-GUARD} (\texttt{v002\_era5}), a deconfounded, zero-imputation benchmark evaluating pre-seismic tropospheric and ionospheric anomalies across \LgTotalGlobalEvents{} global $M \ge 6.5$ earthquakes (2000--2025). Under strictly non-overlapping, equal-lag ($1\text{--}10\,\text{d}$) calibration, raw GNSS ZTD exhibits chance-level skill ($\text{AUC} = \LgAucZtdRaw$), but causal station-level ERA5 meteorological deconfounding uncovers a megathrust-specific tropospheric residual ($\text{AUC} = \LgAucEraCal$ overall; $\LgAucEraMegathrust$ on megathrusts) that mirrors quiet-time $F_{10.7}$-detrended GIM VTEC ($\text{AUC} = \LgAucVtecMain$ overall; $\LgAucVtecMegathrust$ on megathrusts) and reaches $\text{AUC} = \LgAucJointEraVtec$ when fused jointly, while both layers remain at chance on deep-slab/outer-rise negative controls ($\LgAucEraNullCtrl, \LgAucVtecNullCtrl$).

\bibliographystyle{IEEEtran}
\bibliography{references}
\end{document}
""",
    encoding="utf-8",
)

print("Full-length IEEE journal manuscript and tables/figures generated successfully.")
