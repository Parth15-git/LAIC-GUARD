import csv
import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
CW_CSV = ROOT / "reports/stage1c3/regional_crosswalk_v001/analysis/event_level_regional_crosswalk_v001.csv"
CACHE_DIR = ROOT / "data/external/tectonics/stage1c4_comcat_details_v001"
OUT_DIR = ROOT / "reports/stage1c4/mechanism_adjudication_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage1C4-Adjudication/1.0 (academic-research)"


def fetch_event_detail(event_id: str) -> tuple[str, dict | None, str]:
    cache_file = CACHE_DIR / f"{event_id}.json"
    if cache_file.exists() and cache_file.stat().st_size > 100:
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                return event_id, json.load(f), "CACHED"
        except Exception:
            pass

    url = f"https://earthquake.usgs.gov/fdsnws/event/1/query?eventid={event_id}&format=geojson"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                with cache_file.open("w", encoding="utf-8") as f:
                    f.write(raw)
                return event_id, data, "FETCHED"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return event_id, None, "HTTP_404"
            time.sleep(1.0 * (attempt + 1))
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return event_id, None, "FETCH_FAILED"


def extract_best_tensor(detail: dict | None) -> dict:
    empty = {
        "has_tensor": False,
        "tensor_product_type": "",
        "tensor_source": "",
        "strike1": "",
        "dip1": "",
        "rake1": "",
        "strike2": "",
        "dip2": "",
        "rake2": "",
        "tensor_depth_km": "",
        "percent_dc": "",
        "kinematic_style": "NO_COMCAT_TENSOR",
    }
    if not detail:
        return empty

    products = detail.get("properties", {}).get("products", {})
    chosen = None
    chosen_type = ""
    for ptype in ("moment-tensor", "focal-mechanism"):
        plist = products.get(ptype, [])
        if plist:
            # Prefer USGS W-phase / GCMT over regional/automated if multiple exist
            def rank(p):
                src = str(p.get("source", "")).lower()
                code = str(p.get("code", "")).lower()
                score = 0
                if src == "us":
                    score += 10
                if "mww" in code or "wphase" in code:
                    score += 5
                elif "gcmt" in src or "gcmt" in code:
                    score += 4
                return score

            chosen = sorted(plist, key=rank, reverse=True)[0]
            chosen_type = ptype
            break

    if not chosen:
        return empty

    props = chosen.get("properties", {})

    def fval(key):
        v = props.get(key)
        if v is None or str(v).strip() == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    s1, d1, r1 = fval("nodal-plane-1-strike"), fval("nodal-plane-1-dip"), fval("nodal-plane-1-rake")
    s2, d2, r2 = fval("nodal-plane-2-strike"), fval("nodal-plane-2-dip"), fval("nodal-plane-2-rake")
    t_depth = fval("depth")
    p_dc = fval("percent-double-couple")

    kin = "UNCLASSIFIED_TENSOR"
    if r1 is not None:
        # Standard Aki & Richards rake classification
        r_check = r1
        if 45.0 <= r_check <= 135.0:
            kin = "THRUST_REVERSE"
        elif -135.0 <= r_check <= -45.0:
            kin = "NORMAL"
        elif (-45.0 < r_check < 45.0) or (r_check > 135.0) or (r_check < -135.0):
            kin = "STRIKE_SLIP"

    return {
        "has_tensor": r1 is not None and d1 is not None,
        "tensor_product_type": chosen_type,
        "tensor_source": str(chosen.get("source", "")),
        "strike1": f"{s1:.1f}" if s1 is not None else "",
        "dip1": f"{d1:.1f}" if d1 is not None else "",
        "rake1": f"{r1:.1f}" if r1 is not None else "",
        "strike2": f"{s2:.1f}" if s2 is not None else "",
        "dip2": f"{d2:.1f}" if d2 is not None else "",
        "rake2": f"{r2:.1f}" if r2 is not None else "",
        "tensor_depth_km": f"{t_depth:.1f}" if t_depth is not None else "",
        "percent_dc": f"{p_dc:.2f}" if p_dc is not None else "",
        "kinematic_style": kin,
    }


def classify_event_mechanism(row: dict, t: dict) -> tuple[str, str, str]:
    status = row["frozen_crosswalk_status_v001"]
    macro = row["frozen_macro_region_v001"]
    subreg = row["frozen_subregion_v001"]
    stratum = row["frozen_depth_tectonic_stratum_v001"]
    disp_1c2 = row["stage1c2_disposition_v001"]
    depth = float(row["depth_km"])
    kin = t["kinematic_style"]

    if status == "FROZEN_OUTSIDE_PILOT_EXCLUDED":
        return "OUTSIDE_PILOT_UNREVIEWED", "RETAIN_OUTSIDE_PILOT_EXCLUDED", "LOW"

    # Depth-anchored strata
    if stratum == "DEEP_SLAB_GE_300KM":
        conf = "HIGH" if t["has_tensor"] else "MEDIUM"
        return f"DEEP_INTRASLAB_{kin}", "VERIFIED_DEPTH_AND_TENSOR" if t["has_tensor"] else "VERIFIED_DEPTH_SLAB_NO_TENSOR", conf

    if stratum == "INTERMEDIATE_SLAB_70_299KM":
        conf = "HIGH" if t["has_tensor"] else "MEDIUM"
        return f"INTERMEDIATE_INTRASLAB_{kin}", "VERIFIED_DEPTH_AND_TENSOR" if t["has_tensor"] else "VERIFIED_DEPTH_SLAB_NO_TENSOR", conf

    if stratum == "OUTER_RISE_TRENCH_SLOPE":
        conf = "HIGH" if t["has_tensor"] else "MEDIUM"
        return f"OUTER_RISE_TRENCH_SLOPE_{kin}", "VERIFIED_OUTER_RISE_TENSOR" if t["has_tensor"] else "PROVISIONAL_OUTER_RISE_GEOMETRY", conf

    if stratum == "OCEANIC_RIDGE_TRANSFORM":
        conf = "HIGH" if t["has_tensor"] else "MEDIUM"
        return f"OCEANIC_RIDGE_TRANSFORM_{kin}", "VERIFIED_RIDGE_TRANSFORM_TENSOR" if t["has_tensor"] else "PROVISIONAL_RIDGE_GEOMETRY", conf

    # Shallow (<70 km) events: separate low-angle megathrust interface vs steep crustal/splay/strike-slip
    d1 = float(t["dip1"]) if t["dip1"] else None
    d2 = float(t["dip2"]) if t["dip2"] else None
    min_dip = min([d for d in (d1, d2) if d is not None]) if (d1 is not None or d2 is not None) else None

    # Pure continental collision / crustal strike-slip zones without oceanic megathrust interface
    if macro == "HIMALAYA_TIBET_PAMIR":
        if not t["has_tensor"]:
            return "CONTINENTAL_COLLISION_UNRESOLVED_NO_TENSOR", "NEEDS_MANUAL_TENSOR_LOOKUP", "LOW"
        if kin == "THRUST_REVERSE" and min_dip is not None and min_dip <= 30.0 and "TIBET" not in subreg:
            return "CONTINENTAL_MEGATHRUST_MHT_CANDIDATE", "VERIFIED_COMCAT_MOMENT_TENSOR", "HIGH"
        return f"CONTINENTAL_CRUSTAL_{kin}", "VERIFIED_COMCAT_MOMENT_TENSOR", "HIGH"

    if macro == "PERSIA_ZAGROS_OROGEN":
        return f"CONTINENTAL_OROGEN_{kin}" if t["has_tensor"] else "CONTINENTAL_OROGEN_NO_TENSOR", "VERIFIED_COMCAT_MOMENT_TENSOR" if t["has_tensor"] else "NEEDS_MANUAL_TENSOR_LOOKUP", "HIGH" if t["has_tensor"] else "LOW"

    if stratum == "SHALLOW_CRUSTAL_OR_STRIKE_SLIP":
        return f"UPPER_PLATE_CRUSTAL_{kin}" if t["has_tensor"] else "UPPER_PLATE_CRUSTAL_NO_TENSOR", "VERIFIED_COMCAT_MOMENT_TENSOR" if t["has_tensor"] else "PROVISIONAL_STRUCTURAL_ASSIGNMENT", "HIGH" if t["has_tensor"] else "MEDIUM"

    # Subduction margin shallow (<70 km)
    if not t["has_tensor"]:
        if disp_1c2.startswith("PROVISIONAL_SOURCE_CLASSIFICATION_SUPPORTED"):
            return "SUBDUCTION_SHALLOW_HAYES2017_NO_COMCAT_MT", "HAYES2017_SUPPORTED_NO_COMCAT_MT", "MEDIUM"
        return "SUBDUCTION_SHALLOW_UNRESOLVED_NO_TENSOR", "NEEDS_MANUAL_TENSOR_LOOKUP", "NONE"

    if kin == "THRUST_REVERSE":
        if min_dip is not None and min_dip <= 38.0 and depth <= 55.0:
            return "MEGATHRUST_INTERFACE_CANDIDATE", "VERIFIED_COMCAT_MOMENT_TENSOR", "HIGH"
        return "SHALLOW_REVERSE_SPLAY_OR_SLAB", "VERIFIED_COMCAT_MOMENT_TENSOR", "HIGH"

    return f"SHALLOW_NON_INTERFACE_{kin}", "VERIFIED_COMCAT_MOMENT_TENSOR", "HIGH"


def main():
    with CW_CSV.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    target_ids = [
        r["event_id"] for r in rows
        if r["frozen_crosswalk_status_v001"] != "FROZEN_OUTSIDE_PILOT_EXCLUDED"
    ]
    print(f"Fetching/loading ComCat details for {len(target_ids)} non-excluded events...")

    details_map = {}
    status_counts = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_event_detail, eid): eid for eid in target_ids}
        for i, fut in enumerate(as_completed(futures), 1):
            eid, data, st = fut.result()
            details_map[eid] = data
            status_counts[st] = status_counts.get(st, 0) + 1
            if i % 100 == 0 or i == len(target_ids):
                print(f"  Progress: {i}/{len(target_ids)} | {status_counts}")

    out_rows = []
    for r in rows:
        eid = r["event_id"]
        t = extract_best_tensor(details_map.get(eid))
        src_class, mech_disp, mech_conf = classify_event_mechanism(r, t)
        merged = dict(r)
        merged.update({
            "comcat_tensor_available_v001": str(t["has_tensor"]),
            "comcat_tensor_product_v001": t["tensor_product_type"],
            "comcat_tensor_source_v001": t["tensor_source"],
            "comcat_np1_strike_deg": t["strike1"],
            "comcat_np1_dip_deg": t["dip1"],
            "comcat_np1_rake_deg": t["rake1"],
            "comcat_np2_strike_deg": t["strike2"],
            "comcat_np2_dip_deg": t["dip2"],
            "comcat_np2_rake_deg": t["rake2"],
            "comcat_tensor_depth_km": t["tensor_depth_km"],
            "comcat_percent_dc": t["percent_dc"],
            "stage1c4_kinematic_style_v001": t["kinematic_style"],
            "stage1c4_final_source_class_v001": src_class,
            "stage1c4_adjudication_status_v001": mech_disp,
            "stage1c4_confidence_v001": mech_conf,
        })
        out_rows.append(merged)

    out_csv = ANALYSIS_DIR / "event_level_mechanism_adjudication_v001.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    # Summary CSV
    summary_counts = {}
    for r in out_rows:
        key = (
            r["frozen_crosswalk_status_v001"],
            r["frozen_macro_region_v001"],
            r["stage1c4_final_source_class_v001"],
            r["stage1c4_adjudication_status_v001"],
        )
        summary_counts[key] = summary_counts.get(key, 0) + 1

    sum_csv = ANALYSIS_DIR / "mechanism_class_summary_v001.csv"
    with sum_csv.open("w", newline="", encoding="utf-8") as f:
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

    md_path = OUT_DIR / "STAGE1C4_MECHANISM_ADJUDICATION_v001.md"
    md_path.write_text(
        "# Stage 1C.4 - ComCat Moment-Tensor & Source-Mechanism Adjudication (v001)\n\n"
        "**Baseline:** `reports/stage1c3/regional_crosswalk_v001/analysis/event_level_regional_crosswalk_v001.csv` (1,186 events)\n"
        "**Enrichment Scope:** All 641 non-excluded events (572 Core Pilot + 69 Separated Adjacent)\n"
        "**Prepared:** 2026-11-14\n",
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
        '$rows = Import-Csv (Join-Path $PackageRoot "analysis\\event_level_mechanism_adjudication_v001.csv")\n'
        'if ($rows.Count -ne 1186 -or ($rows | Select-Object -ExpandProperty event_id -Unique).Count -ne 1186) { throw "Row count mismatch" }\n'
        'Write-Host "ALL CHECKS PASSED (1,186 / 1,186 unique events verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE1C4_MECHANISM_ADJUDICATION_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/event_level_mechanism_adjudication_v001.csv",
        "analysis/mechanism_class_summary_v001.csv",
    ]
    sha_csv = OUT_DIR / "SHA256SUMS.csv"
    with sha_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            digest = hashlib.sha256(fp.read_bytes()).hexdigest().lower()
            writer.writerow([rel, fp.stat().st_size, digest])

    print("Stage 1C.4 generation complete.")


if __name__ == "__main__":
    main()
