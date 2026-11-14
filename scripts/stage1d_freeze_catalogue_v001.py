import csv
import hashlib
import math
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
IN_CSV = ROOT / "reports/stage1c4/mechanism_adjudication_v001/analysis/event_level_mechanism_adjudication_v001.csv"
OUT_DIR = ROOT / "reports/stage1d/catalogue_freeze_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

with IN_CSV.open("r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

frozen_rows = []
exclusion_rows = []
role_counts = {}

for r in rows:
    eid = r["event_id"]
    mag = float(r["magnitude"])
    cw_status = r["frozen_crosswalk_status_v001"]
    src_class = r["stage1c4_final_source_class_v001"]
    dobrovolsky_km = round(10.0 ** (0.43 * mag), 2)

    if cw_status == "FROZEN_OUTSIDE_PILOT_EXCLUDED":
        role = "EXCLUDED_OUTSIDE_PILOT_SCOPE"
        included = "False"
        exclusion_rows.append({
            "event_id": eid,
            "exclusion_stage": "STAGE_1C3_REGIONAL_CROSSWALK",
            "exclusion_reason": "OUTSIDE_12_CORE_PILOT_REGIONS",
            "rule_id": "RULE_1C3_GEO_SCOPE",
            "decision_date_utc": "2026-11-14T00:00:00Z",
            "reviewer": "LAIC_GUARD_STAGE1D_FREEZE",
            "notes": f"Hasterok subplate={r['Hasterok_subplate']}; outside frozen 12-region pilot scope.",
        })
    elif cw_status == "FROZEN_SEPARATED_ADJACENT_STRATUM":
        role = "EXCLUDED_SEPARATED_ADJACENT_STRATUM"
        included = "False"
        exclusion_rows.append({
            "event_id": eid,
            "exclusion_stage": "STAGE_1C3_1C4_ADJACENT_SEPARATION",
            "exclusion_reason": f"SEPARATED_ADJACENT_DOMAIN_{r['frozen_macro_region_v001']}",
            "rule_id": "RULE_1C3_ADJACENT_BOUNDARY",
            "decision_date_utc": "2026-11-14T00:00:00Z",
            "reviewer": "LAIC_GUARD_STAGE1D_FREEZE",
            "notes": f"Subregion={r['frozen_subregion_v001']}; class={src_class}.",
        })
    elif src_class == "EARLY_MAINSHOCK_CODA_AFTERSHOCK_NO_MT":
        role = "EXCLUDED_CODA_MASKED_EARLY_AFTERSHOCK"
        included = "False"
        exclusion_rows.append({
            "event_id": eid,
            "exclusion_stage": "STAGE_1C4_SEQUENCE_DECONVOLUTION",
            "exclusion_reason": "CODA_MASKED_EARLY_AFTERSHOCK_NO_MT",
            "rule_id": "RULE_1C4_CODA_AFTERSHOCK",
            "decision_date_utc": "2026-11-14T00:00:00Z",
            "reviewer": "LAIC_GUARD_STAGE1D_FREEZE",
            "notes": r["stage1c2_caveat_v001"],
        })
    elif src_class.startswith(("INTERMEDIATE_INTRASLAB", "DEEP_INTRASLAB", "OUTER_RISE_TRENCH_SLOPE")):
        role = "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"
        included = "True"
    else:
        role = "PRIMARY_SHALLOW_TARGET"
        included = "True"

    role_counts[role] = role_counts.get(role, 0) + 1

    out_r = dict(r)
    out_r["dobrovolsky_radius_km"] = f"{dobrovolsky_km:.2f}"
    out_r["stage1d_included_in_pilot_v001"] = included
    out_r["stage1d_analysis_role_v001"] = role
    out_r["stage1d_freeze_version"] = "v001_2026_11_14"
    frozen_rows.append(out_r)

cat_out = ANALYSIS_DIR / "event_catalogue_frozen_v001.csv"
with cat_out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(frozen_rows[0].keys()))
    w.writeheader()
    w.writerows(frozen_rows)

exc_out = ANALYSIS_DIR / "event_exclusions_v001.csv"
exc_fields = ["event_id", "exclusion_stage", "exclusion_reason", "rule_id", "decision_date_utc", "reviewer", "notes"]
with exc_out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=exc_fields)
    w.writeheader()
    w.writerows(exclusion_rows)

md_out = OUT_DIR / "STAGE1D_CATALOGUE_FREEZE_v001.md"
md_out.write_text(
    "# Stage 1D - Frozen Event Catalogue & Exclusion Register (v001)\n\n"
    "**Status:** FROZEN Stage 1D baseline for Stage 2 observational coverage and station pairing.\n"
    "**Total Candidate Events:** 1,186\n"
    f"**Included Core Pilot Events:** {sum(1 for x in frozen_rows if x['stage1d_included_in_pilot_v001'] == 'True')} "
    f"({role_counts.get('PRIMARY_SHALLOW_TARGET', 0)} Primary Shallow Targets + "
    f"{role_counts.get('PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE', 0)} Physical Null-Control Slab/Outer-Rise Events)\n"
    f"**Excluded Events:** {len(exclusion_rows)} (logged in `analysis/event_exclusions_v001.csv`)\n",
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
    '$cat = Import-Csv (Join-Path $PackageRoot "analysis\\event_catalogue_frozen_v001.csv")\n'
    '$exc = Import-Csv (Join-Path $PackageRoot "analysis\\event_exclusions_v001.csv")\n'
    '$incCount = ($cat | Where-Object { $_.stage1d_included_in_pilot_v001 -eq "True" }).Count\n'
    'if ($cat.Count -ne 1186 -or ($incCount + $exc.Count) -ne 1186) { throw "Partition mismatch" }\n'
    'Write-Host "ALL CHECKS PASSED (1,186 total = $incCount included + $($exc.Count) excluded)." -ForegroundColor Cyan\n',
    encoding="utf-8",
)

rel_files = [
    "STAGE1D_CATALOGUE_FREEZE_v001.md",
    "VERIFY_PACKAGE.ps1",
    "analysis/event_catalogue_frozen_v001.csv",
    "analysis/event_exclusions_v001.csv",
]
with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["relative_path", "size_bytes", "sha256"])
    for rel in rel_files:
        fp = OUT_DIR / rel
        w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

for k, v in sorted(role_counts.items(), key=lambda x: -x[1]):
    print(f"  {k:45s} : {v}")
