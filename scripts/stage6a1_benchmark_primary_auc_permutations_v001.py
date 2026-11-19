#!/usr/bin/env python3
"""Stage 6A.1 primary AUC permutation timing pilot, v001.

Runs only five component-label-swap / full grouped-LOEO refits for each of
M2a, M2c, M3 and M4 on STRICT_TARGETS. The resulting pilot p-values are
explicitly non-inferential and must never be reported as final results.

No files are created or modified. The script verifies pinned source and
package fingerprints, reconstructs the strict model inputs, aligns them to
the saved OOF probabilities, and measures runtime using the exact V004
perm_auc_pvalue_group_refit implementation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REPORTS = ROOT / "reports" / "stage6a1"
M2_SCORES = REPORTS / "strict_tcwv_v001" / "full_v001" / "full_feature_scores.csv"
M4_DIR = REPORTS / "m4_joint_features_v002" / "full_v001"
STRICT_PAIRS = M4_DIR / "m4_strict_target_pairs.csv"
M4_MANIFEST = M4_DIR / "manifest.json"
M4_QA = M4_DIR / "m4_feature_assembly_qa.json"
OOF_DIR = REPORTS / "model_evaluation_v001" / "grouped_loeo_oof_v001"
OOF_MANIFEST = OOF_DIR / "manifest.json"
OOF_PREDICTIONS = OOF_DIR / "grouped_loeo_oof_predictions.csv"

EXPECTED = {
    "stage5b": "06BC22ED858D65CB56A0309185E435463817B0F6E8A455F43F6AA7BEE971476C",
    "stage4b": "91F741C1500FB263F229DDF1D69590B357158CBFB42105F3F992AEA0DA3994B0",
    "v004": "4C7DFD199A3C04D82E4850AE487FA5AD1642EE59DF0A51B60948F4B6EE5A68A0",
    "m4_manifest": "30810D6540541A6B75E7D5F70E2E95F43FE798647A4E799D63176D2A03B72DC3",
    "m4_qa": "7FB292A279B2AC873B28D8D6EE17C321BB8BE9BF27CF8339A6435D92BC06D20F",
    "oof_manifest": "6D9BB35B48A326A5D1AB527C1CFD1830979DEADDFC19FD627D1CE662653E8234",
    "oof_predictions": "3FAC2F02C774150A40699786B3A7195012D70BB0301D873F0A6D8D850CC8C5ED",
}

MODELS = ("M2a", "M2c", "M3", "M4")
PILOT_PERMUTATIONS = 5
SEED = 42
STRICT_MATRIX_HASHES = {
    "M2a": "31439CC4498423CA1DA00A9A81B5AA593702BA15B7A182B07AAA8584820B84D5",
    "M2c": "75B80F94692108C4669B6C135A976E1369134B98B302240143265BD0B0D8B486",
    "M3": "34D42FC3FF0EC7FDC8060545393994156C2D80215EF007E1CEEC1259DDEBFCEB",
    "M4": "CBB61A7AC230C1433B399605B673C6026A7B55FCB0C8F1D835B3E3FF12A6DC38",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def require_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} SHA256 mismatch: expected {expected}; got {actual}")
    print(f"Fingerprint PASS: {label} {actual}")
    return actual


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def finite(row: dict[str, str], field: str, context: str) -> float:
    try:
        v = float(row[field])
    except Exception as exc:
        raise ValueError(f"Invalid numeric value {context}/{field}: {row.get(field)!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"Non-finite numeric value {context}/{field}: {v!r}")
    return v


def matrix_digest(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def main() -> int:
    print("===== STAGE 6A.1 PRIMARY AUC PERMUTATION TIMING PILOT v001 =====")
    print("Purpose: estimate full-refit runtime only; no inferential result is produced")
    print(f"Pilot permutations per model: {PILOT_PERMUTATIONS}")
    print("Intended primary test: 9,999 component-level label swaps with full grouped-LOEO refit")
    print("Cohort: STRICT_TARGETS only (88 events / 36 components)")
    print("No files will be written or modified.")

    stage5b_path = SCRIPTS / "stage5b_hardened_audit_v002.py"
    stage4b_path = SCRIPTS / "stage4b_scale_full_tier1_cohort_v001.py"
    v004_path = SCRIPTS / "stage6a_repaired_benchmark_v004_regionfix_cachefix_distancefix.py"

    require_hash(stage5b_path, EXPECTED["stage5b"], "Stage 5B")
    require_hash(stage4b_path, EXPECTED["stage4b"], "Stage 4B")
    require_hash(v004_path, EXPECTED["v004"], "V004")
    require_hash(M4_MANIFEST, EXPECTED["m4_manifest"], "M4 manifest")
    require_hash(M4_QA, EXPECTED["m4_qa"], "M4 QA")
    require_hash(OOF_MANIFEST, EXPECTED["oof_manifest"], "OOF manifest")
    require_hash(OOF_PREDICTIONS, EXPECTED["oof_predictions"], "OOF predictions")

    sys.path.insert(0, str(SCRIPTS))
    from stage6a_repaired_benchmark_v004_regionfix_cachefix_distancefix import (
        perm_auc_pvalue_group_refit,
    )

    m2_rows = read_csv(M2_SCORES)
    pair_rows = read_csv(STRICT_PAIRS)
    oof_rows = read_csv(OOF_PREDICTIONS)

    m2a: dict[tuple[str, str], dict[str, str]] = {}
    for row in m2_rows:
        if row.get("feature") != "M2a_raw_GNSS_ZTD":
            continue
        key = (row["event_id"], row["target_window"])
        if key in m2a:
            raise ValueError(f"Duplicate M2a source row: {key}")
        if row.get("status") != "PASS":
            raise ValueError(f"M2a source row not PASS: {key} {row.get('status')}")
        m2a[key] = row

    if len(pair_rows) != 176:
        raise ValueError(f"Expected 176 strict M4 pair rows; found {len(pair_rows)}")
    if len(m2a) != 222:
        raise ValueError(f"Expected 222 M2a source rows; found {len(m2a)}")

    prepared: dict[str, list[dict]] = {name: [] for name in MODELS}
    canonical = []
    seen = set()
    component_members: dict[str, set[str]] = {}

    for i in range(0, len(pair_rows), 2):
        w0, w1 = pair_rows[i:i + 2]
        event_id = w0["event_id"]
        if w1["event_id"] != event_id or event_id in seen:
            raise ValueError(f"Invalid or duplicate strict event pair: {event_id}")
        seen.add(event_id)
        if (w0["analysis_window"], w1["analysis_window"]) != ("W0", "W1"):
            raise ValueError(f"Invalid W0/W1 order for {event_id}")
        if (w0["label"], w1["label"]) != ("0", "1"):
            raise ValueError(f"Invalid pair labels for {event_id}")
        if w0["component_id"] != w1["component_id"]:
            raise ValueError(f"Event crosses components: {event_id}")
        comp = w0["component_id"]
        component_members.setdefault(comp, set()).add(event_id)

        for row, window in ((w0, "W0"), (w1, "W1")):
            a = m2a.get((event_id, window))
            if a is None:
                raise ValueError(f"Missing M2a feature row: {event_id}/{window}")
            if a.get("status") != "PASS":
                raise ValueError(f"M2a not PASS: {event_id}/{window}")
            a_features = [
                finite(a, "feature_max_abs_robust_z", f"{event_id}/{window}/M2a"),
                finite(a, "feature_q95_abs_robust_z", f"{event_id}/{window}/M2a"),
            ]
            c_features = [
                finite(row, "m2c_max_abs_robust_z", f"{event_id}/{window}/M2c"),
                finite(row, "m2c_q95_abs_robust_z", f"{event_id}/{window}/M2c"),
            ]
            i_features = [
                finite(row, "m3_vtec_max_abs_robust_z", f"{event_id}/{window}/M3"),
                finite(row, "m3_vtec_q95_abs_robust_z", f"{event_id}/{window}/M3"),
            ]
            feature_sets = {
                "M2a": a_features,
                "M2c": c_features,
                "M3": i_features,
                "M4": c_features + i_features,
            }
            label = int(row["label"])
            for model in MODELS:
                sample = {
                    "event_id": event_id,
                    "label": label,
                    "component_id": comp,
                }
                for j, value in enumerate(feature_sets[model]):
                    sample[f"f{j}"] = value
                prepared[model].append(sample)
            canonical.append((event_id, window, label, comp))

    if len(seen) != 88 or len(component_members) != 36:
        raise ValueError("Strict cohort event/component counts do not match frozen values")

    # Confirm exact feature matrices match the previously independently audited digests.
    for model in MODELS:
        matrix_rows = []
        for sample, (eid, window, label, comp) in zip(prepared[model], canonical):
            n_features = len([k for k in sample if k.startswith("f")])
            matrix_rows.append({
                "event_id": eid,
                "analysis_window": window,
                "label": label,
                "component_id": comp,
                "features": [sample[f"f{j}"] for j in range(n_features)],
            })
        digest = matrix_digest(matrix_rows)
        expected = STRICT_MATRIX_HASHES[model]
        if digest != expected:
            raise ValueError(f"Strict {model} matrix hash mismatch: expected {expected}; got {digest}")
        print(f"Strict matrix PASS: {model} {digest}")

    # Align saved OOF arrays to the reconstructed matrix identity, exactly.
    observed: dict[str, list[float]] = {}
    for model in MODELS:
        rows = [r for r in oof_rows if r["cohort"] == "STRICT_TARGETS" and r["model"] == model]
        rows.sort(key=lambda r: int(r["row_order_within_cohort"]))
        if len(rows) != 176:
            raise ValueError(f"Expected 176 OOF predictions for {model}; found {len(rows)}")
        predictions: list[float] = []
        for idx, (row, (eid, window, label, comp)) in enumerate(zip(rows, canonical), start=1):
            expected_key = (eid, window, label, comp)
            actual_key = (
                row["event_id"], row["analysis_window"], int(row["label"]), row["component_id"]
            )
            if actual_key != expected_key:
                raise ValueError(f"OOF alignment mismatch {model} row {idx}: {actual_key} != {expected_key}")
            p = float(row["prediction_probability_W1"])
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError(f"Invalid OOF probability for {model} row {idx}: {p}")
            predictions.append(p)
        observed[model] = predictions
        print(f"OOF alignment PASS: {model} 176 probabilities")

    print("\n===== ENVIRONMENT =====")
    print("Python:", platform.python_version())
    print("Platform:", platform.platform())
    print("Processor:", platform.processor() or "not reported")
    print("Logical CPUs:", os.cpu_count())

    benchmark_rows = []
    total_estimated_seconds = 0.0
    for model in MODELS:
        fkeys = [f"f{i}" for i in range(2 if model != "M4" else 4)]
        print(f"\nStarting {PILOT_PERMUTATIONS}-permutation timing pilot: STRICT_TARGETS/{model}")
        start = time.perf_counter()
        _pilot_p_discarded = perm_auc_pvalue_group_refit(
            prepared[model],
            fkeys,
            "component_id",
            observed[model],
            n_perm=PILOT_PERMUTATIONS,
            seed=SEED,
        )
        elapsed = time.perf_counter() - start
        per_perm = elapsed / PILOT_PERMUTATIONS
        estimated = per_perm * 9999
        total_estimated_seconds += estimated
        benchmark_rows.append((model, elapsed, per_perm, estimated))
        print(
            f"Completed {model}: elapsed={elapsed:.3f}s; "
            f"seconds/permutation={per_perm:.3f}; "
            f"estimated 9,999-permutation time={estimated/3600:.2f}h"
        )

    print("\n===== RUNTIME ESTIMATE =====")
    for model, elapsed, per_perm, estimated in benchmark_rows:
        print(
            f"{model}: {PILOT_PERMUTATIONS} pilots in {elapsed:.2f}s; "
            f"9,999 estimate {estimated/60:.1f} min"
        )
    print(f"Four strict primary AUC tests estimated total: {total_estimated_seconds/3600:.2f} hours")
    print("Estimate is a linear extrapolation from five pilot permutations/model; actual time may vary.")
    print("Pilot p-values are discarded and are not inferential results.")
    print("No source or report files were written or modified.")
    print("TIMING PILOT COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"TIMING PILOT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
