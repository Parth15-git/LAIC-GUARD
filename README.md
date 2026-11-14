# LAIC-GUARD (v002)

**Deconfounded Multi-Domain Benchmark for Lithosphere–Atmosphere–Ionosphere Coupling (`2000–2025`)**

## Reproduced Benchmark Summary (`v002` Zero-Overlap, Equal-Lag `1–10 d` Calibration)
- **Global Catalogue Funnel:** `1,186` USGS ComCat $M \ge 6.5$ earthquakes (`2000–2025`) $\rightarrow$ `563` Core Pilot events (`378` shallow targets, `185` deep-slab/outer-rise candidate negative controls) $\rightarrow$ `111` within-event paired near-field ($d \le 150\text{ km}$) events (`90` shallow, `21` controls) with $\ge 80\%$ 5-min GNSS completeness (`4,039` daily CODE AIUB IONEX maps; NASA OMNIWeb `Kp`/`Dst`/`F10.7`).
- **M2a (`GNSS Troposphere ZTD-Only`, Shallow $N=90$):** $\text{ROC-AUC} = 0.518\ [0.44, 0.60]$ ($p_{\text{Wilc}} = 0.1233$) — no statistically distinguishable discriminative skill over placebo under equal-lag calibration.
- **M3 (`F10.7-Adjusted Quiet GIM VTEC`, Shallow $N=90$):** $\text{ROC-AUC} = 0.627\ [0.56, 0.70]$ ($p_{\text{Wilc}} = 0.0010$; `0.623` under $\pm 15\text{ d}$ storm-cluster CV) vs. `0.522 [0.32, 0.71]` on slab/outer-rise controls ($N=21$).
- **Tectonic Mechanism Split (`M3`):** Signal concentrates in shallow megathrust interface ruptures ($\text{AUC} = 0.645\ [0.57, 0.73]$, $N=62$) rather than shallow crustal/splay events ($\text{AUC} = 0.463\ [0.34, 0.60]$, $N=28$).

## Reproducibility & Integrity Verification
Every pipeline stage (`Stage 1C.2` through `Stage 5D`) includes a `SHA256SUMS.csv` manifest and `VERIFY_PACKAGE.ps1` script enforcing `configs/quality_control.yaml` (`preserve_missing`, zero imputation).
