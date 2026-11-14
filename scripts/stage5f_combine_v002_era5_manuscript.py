import csv, hashlib, shutil
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S5C_CSV = ROOT / "reports/stage5c/zero_overlap_equallag_v002/analysis/stage5c_zero_overlap_equallag_v002.csv"
S5E_CSV = ROOT / "reports/stage5e/era5_deconfounded_v002_era5/analysis/stage5e_era5_ablation_summary_v002.csv"

MS_DIR = ROOT / "manuscript"
MS_TABLES = MS_DIR / "tables"
MS_FIGS = MS_DIR / "figures"
DOCS_DIR = ROOT / "docs"
OUT_DIR = ROOT / "reports/stage5f/combined_release_v002_era5"

for d in (MS_TABLES, MS_FIGS, DOCS_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

r5c = {r["model_or_stratum"]: r for r in csv.DictReader(S5C_CSV.open(encoding="utf-8-sig"))}
r5e = {r["model_or_stratum"]: r for r in csv.DictReader(S5E_CSV.open(encoding="utf-8-sig"))}

# Remove superseded v002-only table/figure from manuscript/ (originals remain in reports/stage5c & stage5d)
for old in (MS_TABLES / "stage5c_v002_benchmark_table.tex", MS_FIGS / "fig_stage5c_laic_guard_benchmark.png"):
    if old.exists():
        old.unlink()

# 1. Unified Table II (v002 + v002_era5)
tbl_lines = [
    r"% Auto-generated Stage 5F Unified Multi-Domain & ERA5-Deconfounded Benchmark Table",
    r"\begin{table*}[t]",
    r"\centering",
    r"\caption{Out-of-Sample Leave-One-Event-Out (LOEO) $\text{ROC-AUC}$ (95\% Cluster-Bootstrap CIs), $\text{PR-AUC}$, and Within-Event Paired Wilcoxon $p$-Values Under Strictly Non-Overlapping, Equal-Lag ($1\text{--}10\,\text{d}$) Calibration Across Tropospheric (\texttt{v002\_era5}) and Ionospheric (\texttt{v002}) Domains.}",
    r"\label{tab:stage5f_combined_benchmark}",
    r"\begin{tabular}{lcccc}",
    r"\hline",
    r"\textbf{Ablation Model / Tectonic \& Geomagnetic Stratum} & \textbf{Events ($N$)} & \textbf{ROC-AUC [95\% CI]} & \textbf{PR-AUC} & \textbf{Paired $p_{\text{Wilc}}$} \\",
    r"\hline",
]
entries = [
    (r5e["M2a: Raw GNSS ZTD-Only (Shallow Baseline)"], r"M2a: Raw GNSS ZTD-Only (Shallow Target)"),
    (r5e["M2b: Physical GNSS - ERA5 (ZHD+ZWD) Residual (Shallow)"], r"M2b: Uncalibrated $\text{GNSS} - \text{ERA5}$ ($\text{ZHD}+\text{ZWD}$, Shallow)"),
    (r5e["M2c: Calibrated GNSS - ERA5 Residual (Shallow, Event-LOEO)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow, Event-LOEO)"),
    (r5e["M2c: Calibrated GNSS - ERA5 Residual (Shallow, Cluster-CV)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow, Cluster-CV)"),
    (r5e["M2c: Calibrated GNSS - ERA5 Residual (Null-Control Slab)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Slab / Outer-Rise Controls)"),
    (r5e["M2c: Calibrated GNSS - ERA5 Residual (Megathrust N=62)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow Megathrust)"),
    (r5e["M2c: Calibrated GNSS - ERA5 Residual (Crustal/Splay N=28)"], r"M2c: Causal-Calibrated $\text{GNSS} - \text{ERA5}$ Residual (Shallow Crustal / Splay)"),
    (r5c["M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow, Event-LOEO)"),
    (r5c["M3: Quiet VTEC (Shallow M>=6.5, Storm-Cluster)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow, Storm-Cluster CV)"),
    (r5c["M3: Quiet VTEC (Null-Control Slab/Outer)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Slab / Outer-Rise Controls)"),
    (r5c["M3: Quiet VTEC (Shallow Megathrust)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow Megathrust)"),
    (r5c["M3: Quiet VTEC (Shallow Crustal/Splay)"], r"M3: Quiet $F_{10.7}$-Adj.\ GIM VTEC (Shallow Crustal / Splay)"),
    (r5c["M3: Quiet VTEC (Shallow |gm_lat| <= 25 deg)"], r"M3: Quiet GIM VTEC (Geomagnetic $\lvert\lambda_m\rvert \le 25^\circ$)"),
    (r5c["M3: Quiet VTEC (Shallow |gm_lat| > 25 deg)"], r"M3: Quiet GIM VTEC (Geomagnetic $\lvert\lambda_m\rvert > 25^\circ$)"),
    (r5e["M4_era5: Joint ERA5-Resid + Quiet VTEC (Shallow)"], r"M4$_{\text{ERA5}}$: Joint Calibrated ERA5-Residual + Quiet VTEC (Shallow)"),
]
for r, lbl in entries:
    tbl_lines.append(f"{lbl} & {r['n_events']} & {r['roc_auc']} {r['ci95']} & {r['pr_auc']} & {r['wilcoxon_p']} \\\\")
tbl_lines.extend([r"\hline", r"\end{tabular}", r"\end{table*}"])
(MS_TABLES / "stage5f_combined_benchmark_table.tex").write_text("\n".join(tbl_lines) + "\n", encoding="utf-8")

# 2. 300-DPI Combined Two-Panel Figure
fig_path = MS_FIGS / "fig_stage5f_combined_benchmark.png"
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 5.2), dpi=300)

    p1 = [
        (r5e["M2a: Raw GNSS ZTD-Only (Shallow Baseline)"], "M2a: Raw GNSS ZTD\n(Shallow, N=90)", "#ff7f0e"),
        (r5e["M2b: Physical GNSS - ERA5 (ZHD+ZWD) Residual (Shallow)"], "M2b: Raw GNSS - ERA5\n(Uncalibrated, N=90)", "#8c564b"),
        (r5e["M2c: Calibrated GNSS - ERA5 Residual (Shallow, Event-LOEO)"], "M2c: Calibrated ERA5 Resid\n(Shallow, N=90)", "#17becf"),
        (r5c["M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)"], "M3: Quiet F10.7 VTEC\n(Shallow, N=90)", "#2ca02c"),
        (r5e["M4_era5: Joint ERA5-Resid + Quiet VTEC (Shallow)"], "M4_ERA5: Joint Trop+VTEC\n(Shallow, N=90)", "#1f77b4"),
    ]
    ax1.axvline(0.5, color="#555555", linestyle="--", linewidth=1.1)
    for idx, (r, lbl, col) in enumerate(p1):
        auc = float(r["roc_auc"])
        lo, hi = [float(x) for x in r["ci95"].strip("[]").split(",")]
        ax1.barh(idx, auc, height=0.52, color=col, alpha=0.88)
        ax1.errorbar(auc, idx, xerr=[[auc - lo], [hi - auc]], fmt="none", ecolor="black", elinewidth=1.3, capsize=3.5)
    ax1.set_yticks(range(len(p1)))
    ax1.set_yticklabels([x[1] for x in p1], fontsize=8.8)
    ax1.invert_yaxis()
    ax1.set_xlim(0.25, 0.85)
    ax1.set_xlabel("Out-of-Sample LOEO ROC-AUC (95% Bootstrap CI)", fontsize=9.5)
    ax1.set_title("(a) Multi-Domain Deconfounding Progression (N = 90)", fontsize=10.5, fontweight="bold")
    ax1.grid(axis="x", linestyle=":", alpha=0.5)

    strata_labels = ["Megathrust\n(N = 62)", "Crustal / Splay\n(N = 28)", "Slab / Outer-Rise\nControls (N = 21)"]
    m2c_s = [
        r5e["M2c: Calibrated GNSS - ERA5 Residual (Megathrust N=62)"],
        r5e["M2c: Calibrated GNSS - ERA5 Residual (Crustal/Splay N=28)"],
        r5e["M2c: Calibrated GNSS - ERA5 Residual (Null-Control Slab)"],
    ]
    m3_s = [
        r5c["M3: Quiet VTEC (Shallow Megathrust)"],
        r5c["M3: Quiet VTEC (Shallow Crustal/Splay)"],
        r5c["M3: Quiet VTEC (Null-Control Slab/Outer)"],
    ]
    ax2.axvline(0.5, color="#555555", linestyle="--", linewidth=1.1)
    for idx in range(3):
        a2 = float(m2c_s[idx]["roc_auc"])
        l2, h2 = [float(x) for x in m2c_s[idx]["ci95"].strip("[]").split(",")]
        a3 = float(m3_s[idx]["roc_auc"])
        l3, h3 = [float(x) for x in m3_s[idx]["ci95"].strip("[]").split(",")]
        ax2.barh(idx - 0.17, a2, height=0.31, color="#17becf", alpha=0.9, label="M2c: Calibrated GNSS - ERA5" if idx == 0 else "")
        ax2.errorbar(a2, idx - 0.17, xerr=[[a2 - l2], [h2 - a2]], fmt="none", ecolor="black", elinewidth=1.2, capsize=3)
        ax2.barh(idx + 0.17, a3, height=0.31, color="#2ca02c", alpha=0.9, label="M3: Quiet F10.7-Adj. VTEC" if idx == 0 else "")
        ax2.errorbar(a3, idx + 0.17, xerr=[[a3 - l3], [h3 - a3]], fmt="none", ecolor="black", elinewidth=1.2, capsize=3)
    ax2.set_yticks(range(3))
    ax2.set_yticklabels(strata_labels, fontsize=9.2)
    ax2.invert_yaxis()
    ax2.set_xlim(0.25, 0.85)
    ax2.set_xlabel("Out-of-Sample LOEO ROC-AUC (95% Bootstrap CI)", fontsize=9.5)
    ax2.set_title("(b) Cross-Layer Tectonic Specificity (Troposphere vs. VTEC)", fontsize=10.5, fontweight="bold")
    ax2.legend(loc="lower right", fontsize=8.3)
    ax2.grid(axis="x", linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(fig_path, dpi=300)
    plt.close(fig)
except ImportError:
    print("matplotlib unavailable; skipped PNG generation.")

# 3. Master Macros (manuscript/laic_guard_numbers.tex)
(MS_DIR / "laic_guard_numbers.tex").write_text(
    "% Auto-generated LAIC-GUARD Combined v002 + v002_era5 Macros\n"
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
    "\\newcommand{\\LgAucZtdRaw}{0.518}\n"
    "\\newcommand{\\LgAucEraUncal}{0.422}\n"
    "\\newcommand{\\LgAucEraCal}{0.621}\n"
    "\\newcommand{\\LgAucEraCalCluster}{0.618}\n"
    "\\newcommand{\\LgAucEraNullCtrl}{0.503}\n"
    "\\newcommand{\\LgAucEraMegathrust}{0.672}\n"
    "\\newcommand{\\LgAucEraCrustal}{0.445}\n"
    "\\newcommand{\\LgAucVtecM65}{0.627}\n"
    "\\newcommand{\\LgAucVtecClusterCv}{0.623}\n"
    "\\newcommand{\\LgAucVtecNullCtrl}{0.522}\n"
    "\\newcommand{\\LgAucVtecMegathrust}{0.645}\n"
    "\\newcommand{\\LgAucVtecCrustal}{0.463}\n"
    "\\newcommand{\\LgAucVtecGeomagLow}{0.616}\n"
    "\\newcommand{\\LgAucVtecGeomagHigh}{0.638}\n"
    "\\newcommand{\\LgAucJointEraVtec}{0.642}\n",
    encoding="utf-8",
)

# 4. Append ERA5 & Bevis citations to references.bib
bib_txt = (MS_DIR / "references.bib").read_text(encoding="utf-8")
if "hersbach2020" not in bib_txt:
    bib_txt += (
        "\n@article{hersbach2020,\n"
        "  author={Hersbach, H. and others},\n"
        "  title={The {ERA5} global reanalysis},\n"
        "  journal={Quarterly Journal of the Royal Meteorological Society}, volume={146}, number={730}, pages={1999--2049}, year={2020},\n"
        "  doi={10.1002/qj.3803}\n}\n\n"
        "@article{bevis1992,\n"
        "  author={Bevis, M. and Businger, S. and Herring, T. A. and Rocken, C. and Anthes, R. A. and Ware, R. H.},\n"
        "  title={{GPS} meteorology: Remote sensing of atmospheric water vapor using the Global Positioning System},\n"
        "  journal={Journal of Geophysical Research: Atmospheres}, volume={97}, number={D14}, pages={15787--15801}, year={1992},\n"
        "  doi={10.1029/92JD01517}\n}\n"
    )
    (MS_DIR / "references.bib").write_text(bib_txt, encoding="utf-8")

# 5. Unified IEEEtran Manuscript (manuscript/main.tex)
(MS_DIR / "main.tex").write_text(
    r"""\documentclass[conference]{IEEEtran}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}

\input{laic_guard_numbers.tex}

\title{LAIC-GUARD: A Deconfounded Multi-Domain Benchmark for Lithosphere--Atmosphere--Ionosphere Earthquake Precursors (2000--2025)}

\author{\IEEEauthorblockN{Parth Nilesh Jichkar}
\IEEEauthorblockA{Department of Electronics and Communication Engineering, MIT World Peace University, Pune, India}}

\begin{document}
\maketitle

\begin{abstract}
Retrospective studies of pre-seismic anomalies across tropospheric delay and ionospheric total electron content (TEC) often suffer from post-hoc event selection, overlapping baseline windows, meteorological and geomagnetic storm leakage, and a lack of deep-source negative controls. We introduce \textbf{LAIC-GUARD}, a reproducible, zero-imputation multi-domain benchmark spanning all \LgTotalGlobalEvents{} global $M \ge 6.5$ earthquakes (2000--2025). Combining tectonic province attribution, moment-tensor adjudication, and Dobrovolsky strain-radius ($R_D = 10^{0.43M}$\,km) station pairing across Nevada Geodetic Laboratory (UNR) continuous GNSS tropospheric solutions, ECMWF ERA5 meteorological reanalysis, CODE AIUB global ionosphere maps (\LgIonexMapsIngested{} daily IONEX files), and NASA OMNIWeb indices, we isolate \LgPairedTierOneTotal{} within-event paired near-field ($d \le 150$\,km) earthquakes (\LgPairedShallowM65{} primary shallow targets vs.\ \LgPairedNullCtrlM65{} deep-slab and outer-rise candidate negative controls). Under strictly non-overlapping, equal-lag ($1\text{--}10$\,d) calibration, raw GNSS zenith total delay (ZTD) shows no statistically distinguishable skill ($\text{AUC} = \LgAucZtdRaw$, $p_{\text{Wilc}} = 0.1233$). However, removing synoptic weather via station-calibrated ERA5 hydrostatic-plus-wet reanalysis uncovers a non-meteorological ZTD residual ($\text{AUC} = \LgAucEraCal$, $p_{\text{Wilc}} = 0.0009$) that mirrors solar-$F_{10.7}$-detrended quiet GIM VTEC ($\text{AUC} = \LgAucVtecM65$, $p_{\text{Wilc}} = 0.0010$). Both signals concentrate in shallow megathrust interface ruptures ($\text{AUC} = \LgAucEraMegathrust$ and $\LgAucVtecMegathrust$, respectively) while remaining at chance for crustal/splay earthquakes ($\LgAucEraCrustal$, $\LgAucVtecCrustal$) and slab/outer-rise controls ($\LgAucEraNullCtrl$, $\LgAucVtecNullCtrl$), yielding $\text{AUC} = \LgAucJointEraVtec$ when fused jointly.
\end{abstract}

\begin{IEEEkeywords}
Lithosphere--atmosphere--ionosphere coupling, GNSS troposphere, ERA5 reanalysis, GIM VTEC, earthquake precursors
\end{IEEEkeywords}

\section{Introduction}
The Lithosphere--Atmosphere--Ionosphere Coupling (LAIC) framework hypothesizes that pre-rupture stress accumulation perturbs atmospheric moisture and ionospheric electron density prior to major earthquakes \cite{dobrovolsky1979,pulinets2011}. Recent multi-decadal audits emphasize that credible benchmark evaluation requires explicit non-overlapping baselines, event-wise and storm-clustered cross-validation, negative controls, and rigorous meteorological and space-weather deconfounding \cite{diaz2026,chaniadakis2025,wen2026}.

\section{Catalogue Adjudication and Multi-Domain Pipeline}
From \LgTotalGlobalEvents{} global $M \ge 6.5$ earthquakes in USGS ComCat (2000--2025), tectonic province overlays \cite{hasterok2022} and W-phase/GCMT moment tensors isolate \LgCorePilotIncluded{} Core Pilot events across \LgPilotRegions{} macro-regions (\LgPrimaryShallowTotal{} shallow targets at $z < 70$\,km and \LgPhysicalNullControlTotal{} deep-slab/outer-rise candidate negative controls; \LgExcludedTotal{} excluded).

\input{tables/stage1c_manuscript_tables.tex}

Spatial-temporal pairing against the UNR GNSS network \cite{blewitt2018} yields \LgNearRegionalCohort{} near-regional ($d \le 300$\,km) events and \LgStageThreeReady{} archive-verified events with $\ge 15$ geomagnetically quiet baseline days ($Kp < 3$, $Dst > -30$\,nT). Within Tier-1 near-field stations ($d \le 150$\,km, \LgTierOneReady{} events), \LgTierOneGnssQaPass{} achieve $\ge 80\%$ 5-minute completeness without imputation, and \LgPairedTierOneTotal{} (\LgPairedShallowM65{} shallow, \LgPairedNullCtrlM65{} controls) satisfy strict quiet-epoch completeness across non-overlapping placebo ($[-30\,\text{d}, -21\,\text{d}]$) and pre-event ($[-10\,\text{d}, -1\,\text{d}]$) windows using \LgIonexMapsIngested{} daily CODE AIUB IONEX maps \cite{schaer1999} and hourly ECMWF ERA5 reanalysis \cite{hersbach2020,bevis1992}.

\section{Zero-Overlap Equal-Lag & ERA5-Deconfounded Results}
Placebo windows are calibrated against $[-45\,\text{d}, -31\,\text{d}]$ and pre-event windows against $[-25\,\text{d}, -11\,\text{d}]$. Table~\ref{tab:stage5f_combined_benchmark} and Fig.~\ref{fig:benchmark_v002_combined} report out-of-sample discrimination across all tropospheric, ERA5-deconfounded, and ionospheric models.

\input{tables/stage5f_combined_benchmark_table.tex}

\begin{figure*}[t]
\centering
\includegraphics[width=0.96\textwidth]{figures/fig_stage5f_combined_benchmark.png}
\caption{LAIC-GUARD (\texttt{v002} + \texttt{v002\_era5}) zero-overlap, equal-lag ($1\text{--}10$\,d) out-of-sample $\text{ROC-AUC}$ with 95\% cluster-bootstrap confidence intervals across (a) progressive meteorological and ionospheric deconfounding models ($N = \LgPairedShallowM65$), and (b) tectonic mechanism and candidate negative-control strata.}
\label{fig:benchmark_v002_combined}
\end{figure*}

Raw GNSS ZTD ($\text{AUC} = \LgAucZtdRaw$) and uncalibrated $\text{GNSS} - \text{ERA5}$ differences ($\LgAucEraUncal$) fail to separate pre-seismic windows from placebo due to synoptic weather and `0.25°` grid-elevation mismatch. Applying station-specific linear transfer calibration within each causal baseline (M2c) isolates a non-meteorological ZTD residual ($\text{AUC} = \LgAucEraCal$, $p_{\text{Wilc}} = 0.0009$; $\LgAucEraCluster$ under $\pm 15$\,d storm-cluster CV). Independently, M2c and quiet $F_{10.7}$-adjusted VTEC (M3) converge on shallow megathrust interface earthquakes ($\text{AUC} = \LgAucEraMegathrust$ and $\LgAucVtecMegathrust$, $N=62$), while remaining indistinguishable from chance on crustal/splay ruptures ($\LgAucEraCrustal$, $\LgAucVtecCrustal$, $N=28$) and slab/outer-rise controls ($\LgAucEraNullCtrl$, $\LgAucVtecNullCtrl$, $N=21$). Fusing calibrated ERA5 residuals with quiet VTEC (M4$_{\text{ERA5}}$) yields $\text{AUC} = \LgAucJointEraVtec$.

\section{Limitations and Conclusion}
While causal-window OLS calibration in M2c prevents future leakage, non-stationary synoptic shifts between baseline windows can influence residual variance; nonetheless, chance-level performance on slab controls ($\LgAucEraNullCtrl$) argues against a generic baseline artifact. Together, our findings show that meteorological and solar deconfounding isolates a modest, megathrust-specific multi-layer association rather than an operational earthquake-prediction capability.

\bibliographystyle{IEEEtran}
\bibliography{references}
\end{document}
""",
    encoding="utf-8",
)

# 6. Governance Freeze Addendum & Zenodo CITATION.cff
(DOCS_DIR / "GOVERNANCE_AND_FREEZE_ADDENDUM_v002.md").write_text(
    "# LAIC-GUARD Governance & Freeze Addendum (Stages 1C.0 – 5F)\n\n"
    "- **Catalogue Freeze (`Stage 1D`):** `1,186` USGS ComCat events (`2000–2025`) adjudicated across 12 macro-regions and W-phase/GCMT moment tensors into `563` Core Pilot events (`378` primary shallow targets, `185` deep-slab/outer-rise candidate negative controls) and `623` logged exclusions (`metadata/event_exclusions.csv`).\n"
    "- **Zero-Overlap Equal-Lag Protocol (`v002` & `v002_era5`):** Placebo `[-30d, -21d]` calibrated on `[-45d, -31d]`; Target `[-10d, -1d]` calibrated on `[-25d, -11d]`; strict zero-imputation policy (`configs/quality_control.yaml`).\n"
    "- **Row-Level Attrition Ledger:** Complete `1,186`-event accounting locked in `reports/stage5b/hardened_audit_v002/analysis/event_attrition_ledger_v002.csv`.\n",
    encoding="utf-8",
)

(ROOT / "CITATION.cff").write_text(
    "cff-version: 1.2.0\n"
    "title: \"LAIC-GUARD: A Deconfounded Multi-Domain Benchmark for Lithosphere-Atmosphere-Ionosphere Earthquake Precursors (2000-2025)\"\n"
    "message: \"If you use this benchmark dataset or pipeline, please cite it using these metadata.\"\n"
    "type: dataset\n"
    "authors:\n"
    "  - family-names: Jichkar\n"
    "    given-names: Parth Nilesh\n"
    "    affiliation: MIT World Peace University, Pune, India\n"
    "version: v002_era5\n"
    "date-released: 2026-11-15\n"
    "repository-code: \"https://github.com/Parth15-git/LAIC-GUARD\"\n",
    encoding="utf-8",
)

# 7. Release Manifest & SHA256SUMS.csv
(OUT_DIR / "STAGE5F_COMBINED_RELEASE_v002_era5.md").write_text("# Stage 5F Combined v002 + v002_era5 Release\n", encoding="utf-8")
(OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
    'param([string]$PackageRoot = $PSScriptRoot)\n$ErrorActionPreference = "Stop"\n'
    'foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {\n'
    '  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }\n'
    '  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n}\n'
    'Write-Host "ALL CHECKS PASSED (Stage 5F combined v002 + v002_era5 release verified)." -ForegroundColor Cyan\n',
    encoding="utf-8",
)
with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["relative_path", "size_bytes", "sha256"])
    for rel in ["STAGE5F_COMBINED_RELEASE_v002_era5.md", "VERIFY_PACKAGE.ps1"]:
        fp = OUT_DIR / rel
        w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])
