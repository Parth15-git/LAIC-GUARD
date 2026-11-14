# LAIC-GUARD (`v002_era5`)

**Deconfounded Multi-Domain Benchmark for Lithosphere–Atmosphere–Ionosphere Coupling (`2000–2025`)**

## Reproduced Benchmark Summary (`v002` + `v002_era5` Zero-Overlap, Equal-Lag `1–10 d` Calibration)
- **Global Catalogue Funnel:** `1,186` USGS ComCat $M \ge 6.5$ earthquakes (`2000–2025`) $\rightarrow$ `563` Core Pilot events (`378` shallow targets, `185` deep-slab/outer-rise candidate negative controls) $\rightarrow$ `111` within-event paired near-field ($d \le 150\text{ km}$) events (`90` shallow, `21` controls) with $\ge 80\%$ 5-min GNSS completeness (`4,039` daily CODE AIUB IONEX maps; NASA OMNIWeb `Kp`/`Dst`/`F10.7`; hourly ECMWF ERA5 reanalysis).
- **M2a (`Raw GNSS ZTD-Only`, Shallow $N=90$):** $\text{ROC-AUC} = 0.518\ [0.44, 0.60]$ ($p_{\text{Wilc}} = 0.1233$) — masked by synoptic weather variability.
- **M2c (`Causal-Calibrated GNSS − ERA5 ZHD+ZWD Residual`, Shallow $N=90$):** $\text{ROC-AUC} = 0.621\ [0.55, 0.70]$ ($p_{\text{Wilc}} = 0.0009$; `0.618` under $\pm 15\text{ d}$ storm-cluster CV) vs. `0.503 [0.33, 0.67]` on slab/outer-rise controls ($N=21$).
- **M3 (`Quiet F10.7-Adjusted GIM VTEC`, Shallow $N=90$):** $\text{ROC-AUC} = 0.627\ [0.56, 0.70]$ ($p_{\text{Wilc}} = 0.0010$; `0.623` under storm-cluster CV) vs. `0.522 [0.32, 0.71]` on slab/outer-rise controls ($N=21$).
- **Cross-Layer Tectonic Specificity & Joint Fusion (`M4_era5`):** Both `M2c` and `M3` concentrate in shallow megathrust interface ruptures (`0.672` and `0.645`, $N=62$) rather than shallow crustal/splay events (`0.445` and `0.463`, $N=28$), reaching $\text{ROC-AUC} = 0.642\ [0.56, 0.72]$ when fused jointly.

## Reproducibility & Governance
Every pipeline stage (`Stage 1C.2` through `Stage 5F`) is verified via `SHA256SUMS.csv` and `VERIFY_PACKAGE.ps1` under strict zero-imputation (`configs/quality_control.yaml`), with full event-level attrition and governance records in `docs/GOVERNANCE_AND_FREEZE_ADDENDUM_v002.md`.
