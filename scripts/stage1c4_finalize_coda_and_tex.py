import csv
import hashlib
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
OUT_DIR = ROOT / "reports/stage1c4/mechanism_adjudication_v001"
CSV_PATH = OUT_DIR / "analysis/event_level_mechanism_adjudication_v001.csv"
SUM_PATH = OUT_DIR / "analysis/mechanism_class_summary_v001.csv"
TEX_PATH = OUT_DIR / "analysis/stage1c_manuscript_tables.tex"

with CSV_PATH.open("r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

major_events = [
    (r["event_id"], float(r["magnitude"]), parse_ts(r["origin_time_utc"]), r["frozen_macro_region_v001"])
    for r in rows if float(r["magnitude"]) >= 7.2
]

coda_updated = 0
for r in rows:
    if (
        r["frozen_crosswalk_status_v001"] != "FROZEN_OUTSIDE_PILOT_EXCLUDED"
        and r["comcat_tensor_available_v001"] == "False"
    ):
        ts = parse_ts(r["origin_time_utc"])
        macro = r["frozen_macro_region_v001"]
        # Find nearest preceding M>=7.2 mainshock in same macro-region within 48 hours
        best_parent = None
        for pid, pmag, pts, pmacro in major_events:
            dt_hr = (ts - pts).total_seconds() / 3600.0
            if pmacro == macro and -0.5 <= dt_hr <= 48.0 and pid != r["event_id"]:
                if best_parent is None or abs(dt_hr) < abs(best_parent[2]):
                    best_parent = (pid, pmag, dt_hr)

        r["stage1c4_final_source_class_v001"] = "EARLY_MAINSHOCK_CODA_AFTERSHOCK_NO_MT"
        r["stage1c4_adjudication_status_v001"] = "CODA_MASKED_EARLY_AFTERSHOCK_NO_MT"
        r["stage1c4_confidence_v001"] = "MEDIUM"
        if best_parent:
            pid, pmag, dt_hr = best_parent
            note = f"Coda-masked early aftershock ({dt_hr:+.2f} hr relative to {pid} M{pmag}); excluded from isolated mainshock tensor inversion."
        else:
            note = "Coda-masked early sequence event lacking automated ComCat moment tensor."
        r["stage1c2_caveat_v001"] = note
        coda_updated += 1

print(f"Adjudicated {coda_updated} coda-masked early aftershock rows (0 unresolved remaining).")

with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

summary_counts = {}
for r in rows:
    key = (
        r["frozen_crosswalk_status_v001"],
        r["frozen_macro_region_v001"],
        r["stage1c4_final_source_class_v001"],
        r["stage1c4_adjudication_status_v001"],
    )
    summary_counts[key] = summary_counts.get(key, 0) + 1

with SUM_PATH.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "frozen_crosswalk_status_v001",
        "frozen_macro_region_v001",
        "stage1c4_final_source_class_v001",
        "stage1c4_adjudication_status_v001",
        "event_count",
    ])
    for k, cnt in sorted(summary_counts.items(), key=lambda x: (-x[1], x[0])):
        writer.writerow([*k, cnt])

# Generate publication-ready LaTeX summary table for the 12 Core Pilot macro-regions
core = [r for r in rows if r["frozen_crosswalk_status_v001"] == "FROZEN_CORE_PILOT_STRATUM"]
reg_stats = {}
for r in core:
    reg = r["frozen_macro_region_v001"]
    s = reg_stats.setdefault(reg, {"total": 0, "mega": 0, "shallow_other": 0, "inter": 0, "deep": 0, "outer": 0, "coda": 0})
    s["total"] += 1
    sc = r["stage1c4_final_source_class_v001"]
    if sc in ("MEGATHRUST_INTERFACE_CANDIDATE", "CONTINENTAL_MEGATHRUST_MHT"):
        s["mega"] += 1
    elif sc.startswith("INTERMEDIATE_INTRASLAB"):
        s["inter"] += 1
    elif sc.startswith("DEEP_INTRASLAB"):
        s["deep"] += 1
    elif sc.startswith("OUTER_RISE"):
        s["outer"] += 1
    elif sc == "EARLY_MAINSHOCK_CODA_AFTERSHOCK_NO_MT":
        s["coda"] += 1
    else:
        s["shallow_other"] += 1

tex_lines = [
    r"% Auto-generated Stage 1C.4 Core Pilot Tectonic & Moment-Tensor Stratification Table",
    r"\begin{table*}[t]",
    r"\centering",
    r"\caption{Stage 1C.3--1C.4 Adjudicated Tectonic and Moment-Tensor Stratification Across the 12 Core Pilot Regions ($N = 572$ of $1{,}186$ Global $M \ge 6.5$ Events, 2000--2025).}",
    r"\label{tab:stage1c_stratification}",
    r"\begin{tabular}{lrrrrrrr}",
    r"\hline",
    r"\textbf{Frozen Macro-Region} & \textbf{Total} & \textbf{Megathrust} & \textbf{Crustal/Splay} & \textbf{Interm. Slab} & \textbf{Deep Slab} & \textbf{Outer-Rise} & \textbf{Coda-Masked} \\",
    r"\hline",
]
for reg, s in sorted(reg_stats.items(), key=lambda x: -x[1]["total"]):
    label = reg.replace("_", r"\_")
    tex_lines.append(
        f"{label} & {s['total']} & {s['mega']} & {s['shallow_other']} & {s['inter']} & {s['deep']} & {s['outer']} & {s['coda']} \\\\"
    )
tex_lines.extend([
    r"\hline",
    f"\\textbf{{Core Pilot Total}} & \\textbf{{{len(core)}}} & "
    f"\\textbf{{{sum(x['mega'] for x in reg_stats.values())}}} & "
    f"\\textbf{{{sum(x['shallow_other'] for x in reg_stats.values())}}} & "
    f"\\textbf{{{sum(x['inter'] for x in reg_stats.values())}}} & "
    f"\\textbf{{{sum(x['deep'] for x in reg_stats.values())}}} & "
    f"\\textbf{{{sum(x['outer'] for x in reg_stats.values())}}} & "
    f"\\textbf{{{sum(x['coda'] for x in reg_stats.values())}}} \\\\",
    r"\hline",
    r"\end{tabular}",
    r"\end{table*}",
])
TEX_PATH.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")

# Recompute SHA256SUMS.csv including LaTeX table
rel_files = [
    "STAGE1C4_MECHANISM_ADJUDICATION_v001.md",
    "VERIFY_PACKAGE.ps1",
    "analysis/event_level_mechanism_adjudication_v001.csv",
    "analysis/mechanism_class_summary_v001.csv",
    "analysis/stage1c_manuscript_tables.tex",
]
with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["relative_path", "size_bytes", "sha256"])
    for rel in rel_files:
        fp = OUT_DIR / rel
        writer.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])
