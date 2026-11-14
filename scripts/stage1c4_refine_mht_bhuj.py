import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
CACHE_DIR = ROOT / "data/external/tectonics/stage1c4_comcat_details_v001"
OUT_DIR = ROOT / "reports/stage1c4/mechanism_adjudication_v001"
CSV_PATH = OUT_DIR / "analysis/event_level_mechanism_adjudication_v001.csv"
SUM_PATH = OUT_DIR / "analysis/mechanism_class_summary_v001.csv"

with CSV_PATH.open("r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

print("===== 1. NON-EXCLUDED EVENTS WITHOUT COMCAT TENSOR =====")
no_mt = [
    r for r in rows
    if r["frozen_crosswalk_status_v001"] != "FROZEN_OUTSIDE_PILOT_EXCLUDED"
    and r["comcat_tensor_available_v001"] == "False"
]
print(f"Total non-excluded events lacking ComCat tensor: {len(no_mt)}")
for r in sorted(no_mt, key=lambda x: x["origin_time_utc"]):
    jfile = CACHE_DIR / f"{r['event_id']}.json"
    prods = []
    if jfile.exists():
        data = json.loads(jfile.read_text(encoding="utf-8"))
        prods = sorted(data.get("properties", {}).get("products", {}).keys())
    print(
        f"  {r['event_id']:14s} | {r['origin_time_utc'][:10]} | M{r['magnitude']} | "
        f"z={r['depth_km']}km | {r['frozen_macro_region_v001']} | {r['place']} | products={';'.join(prods)}"
    )

# Refine Himalayan MHT vs 2001 Bhuj intraplate reverse
mht_ids = {"us20002926", "us2000292y", "us200029bt", "us20002ejl", "usp000e12e"}
refined_count = 0
for r in rows:
    eid = r["event_id"]
    if eid == "usp000a8ds":
        r["frozen_macro_region_v001"] = "NON_PILOT_OCEANIC_OR_ADJACENT"
        r["frozen_crosswalk_status_v001"] = "FROZEN_SEPARATED_ADJACENT_STRATUM"
        r["frozen_subregion_v001"] = "INDIAN_CRATON_KUTCH_INTRAPLATE"
        r["frozen_depth_tectonic_stratum_v001"] = "SHALLOW_CRUSTAL_OR_STRIKE_SLIP"
        r["stage1c4_final_source_class_v001"] = "INDIAN_CRATON_INTRAPLATE_REVERSE"
        r["stage1c4_adjudication_status_v001"] = "VERIFIED_COMCAT_MOMENT_TENSOR"
        r["stage1c4_confidence_v001"] = "HIGH"
        refined_count += 1
    elif eid in mht_ids:
        r["frozen_subregion_v001"] = "HIMALAYA_MAIN_HIMALAYAN_THRUST"
        r["stage1c4_final_source_class_v001"] = "CONTINENTAL_MEGATHRUST_MHT"
        r["stage1c4_adjudication_status_v001"] = "VERIFIED_COMCAT_MOMENT_TENSOR"
        r["stage1c4_confidence_v001"] = "HIGH"
        refined_count += 1

print(f"\nRefined {refined_count} Himalayan MHT / Bhuj intraplate records.")

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

# Recompute SHA256SUMS.csv
rel_files = [
    "STAGE1C4_MECHANISM_ADJUDICATION_v001.md",
    "VERIFY_PACKAGE.ps1",
    "analysis/event_level_mechanism_adjudication_v001.csv",
    "analysis/mechanism_class_summary_v001.csv",
]
with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["relative_path", "size_bytes", "sha256"])
    for rel in rel_files:
        fp = OUT_DIR / rel
        writer.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])
