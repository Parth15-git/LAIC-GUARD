#!/usr/bin/env python3
"""Stage 6A.1 inference runner v001.

Uses the pinned Stage 5B grouped-LOEO estimator and Stage 4B ROC AUC.
AUC permutation patterns are generated sequentially with the V004 RNG order,
then evaluated in parallel. Checkpoint batches are atomic and resumable.

Phases:
  primary_auc       4 strict-target AUC tests, 9,999 full grouped-LOEO refits each
  sensitivity_auc   4 conservative-target sensitivity AUC tests, 9,999 each
  primary_support   strict bootstrap, physical endpoints, paired model comparisons,
                    and primary Holm corrections
  sensitivity_support same support analyses for conservative cohort (no Holm)
  all               all four phases

This script does not tune models and does not evaluate physical controls as a
classifier cohort. Existing source reports are read-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from stage5b_hardened_audit_v002 import grouped_loeo, pr_auc  # noqa: E402
from stage4b_scale_full_tier1_cohort_v001 import roc_auc  # noqa: E402

# ---- Frozen input identities -------------------------------------------------
EXPECTED_SHA = {
    "stage5b": "06BC22ED858D65CB56A0309185E435463817B0F6E8A455F43F6AA7BEE971476C",
    "stage4b": "91F741C1500FB263F229DDF1D69590B357158CBFB42105F3F992AEA0DA3994B0",
    "v004": "4C7DFD199A3C04D82E4850AE487FA5AD1642EE59DF0A51B60948F4B6EE5A68A0",
    "m4_manifest": "30810D6540541A6B75E7D5F70E2E95F43FE798647A4E799D63176D2A03B72DC3",
    "m4_qa": "7FB292A279B2AC873B28D8D6EE17C321BB8BE9BF27CF8339A6435D92BC06D20F",
    "oof_manifest": "6D9BB35B48A326A5D1AB527C1CFD1830979DEADDFC19FD627D1CE662653E8234",
    "oof_predictions": "3FAC2F02C774150A40699786B3A7195012D70BB0301D873F0A6D8D850CC8C5ED",
    "oof_metrics": "99ED42F99CAB46D6A83D23D53DBDC78E08414D6F472743F39CF645E67AD0F5B2",
    "oof_folds": "3E5AE08AFF9EC64AE084193D2A7E26C15458D9EAC92C9F1BB7128D85069BDA61",
    "m4_strict_pairs": "51F07F381452CF2E925B0FF123C6E324B4E28BF82C5A5FF1F0947A5EAED28E23",
    "m4_conservative_pairs": "9C8A962C93E03EAB620B6C898CF6B433FF541D5D04FC567E9A023C7F4F76A268",
}
EXPECTED_MATRIX_SHA = {
    "STRICT_TARGETS": {
        "M2a": "31439CC4498423CA1DA00A9A81B5AA593702BA15B7A182B07AAA8584820B84D5",
        "M2c": "75B80F94692108C4669B6C135A976E1369134B98B302240143265BD0B0D8B486",
        "M3": "34D42FC3FF0EC7FDC8060545393994156C2D80215EF007E1CEEC1259DDEBFCEB",
        "M4": "CBB61A7AC230C1433B399605B673C6026A7B55FCB0C8F1D835B3E3FF12A6DC38",
    },
    "CONSERVATIVE_TARGETS": {
        "M2a": "0E6914B776D6779E929FDB920644D986A7CDD4B8430937EEA36FAA816993956D",
        "M2c": "0716A2D4C401C20F16D8DF01A58D537451C375F1A8F62D186559972E22AC2BC7",
        "M3": "42B313518F6E86C02380162B8408E231C7068CFBB81B71DF5F5576B23B78F647",
        "M4": "C1EEBD1930FD472246A6FDFA23CAC6C6CED608CAD2355BB2122A9DDFA726AFB5",
    },
}

N_PERM = 9999
N_BOOT = 1000
SEED_AUC = 42
SEED_BOOT = 42
SEED_PHYSICAL = 2026
SEED_PAIRED = 2027
DEFAULT_BATCH_SIZE = 250

COHORTS = {
    "STRICT_TARGETS": {
        "pair_file": "m4_strict_target_pairs.csv",
        "n_events": 88,
        "n_components": 36,
        "primary": True,
    },
    "CONSERVATIVE_TARGETS": {
        "pair_file": "m4_conservative_target_pairs.csv",
        "n_events": 87,
        "n_components": 35,
        "primary": False,
    },
}
MODELS = ("M2a", "M2c", "M3", "M4")
MODEL_FEATURE_COUNTS = {"M2a": 2, "M2c": 2, "M3": 2, "M4": 4}
COMPARISONS = (("M2c", "M2a", "M2c_vs_M2a"), ("M4", "M3", "M4_vs_M3"))
PHYSICAL_ENDPOINTS = (
    "raw_gnss_ztd_q95",
    "calibrated_era5_residual_q95",
    "quiet_adjusted_vtec_q95",
)

# ---- Worker process state ----------------------------------------------------
_WORKER_SAMPLES: list[dict[str, Any]] | None = None
_WORKER_FKEYS: list[str] | None = None


def _worker_init(samples: list[dict[str, Any]], fkeys: list[str]) -> None:
    global _WORKER_SAMPLES, _WORKER_FKEYS
    _WORKER_SAMPLES = samples
    _WORKER_FKEYS = fkeys


def _worker_auc_permutation(task: tuple[int, tuple[str, ...]]) -> tuple[int, float, tuple[str, ...]]:
    """Evaluate one pre-generated component label-flip pattern."""
    if _WORKER_SAMPLES is None or _WORKER_FKEYS is None:
        raise RuntimeError("Permutation worker was not initialized")
    permutation_index, flipped_tuple = task
    flipped = set(flipped_tuple)
    permuted = []
    for sample in _WORKER_SAMPLES:
        item = dict(sample)
        if str(item["component_id"]) in flipped:
            item["label"] = 1 - int(item["label"])
        permuted.append(item)
    preds = grouped_loeo(permuted, _WORKER_FKEYS, "component_id")
    labels = [int(s["label"]) for s in permuted]
    value = roc_auc(preds, labels)
    if not math.isfinite(value):
        raise ValueError(f"Permutation {permutation_index} produced non-finite AUC")
    return permutation_index, value, flipped_tuple

# ---- Basic utilities ---------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def json_sha256(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def nearest_rank(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("Cannot summarize an empty distribution")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(p * len(ordered))))
    return ordered[rank - 1]


def distribution_summary(values: list[float]) -> dict[str, float]:
    if len(values) != N_PERM:
        raise ValueError(f"Expected {N_PERM} null values, got {len(values)}")
    return {
        "null_median": float(statistics.median(values)),
        "null_q05_nearest_rank": float(nearest_rank(values, 0.05)),
        "null_q95_nearest_rank": float(nearest_rank(values, 0.95)),
        "null_min": float(min(values)),
        "null_max": float(max(values)),
    }


def source_paths(root: Path) -> dict[str, Path]:
    return {
        "stage5b": root / "scripts/stage5b_hardened_audit_v002.py",
        "stage4b": root / "scripts/stage4b_scale_full_tier1_cohort_v001.py",
        "v004": root / "scripts/stage6a_repaired_benchmark_v004_regionfix_cachefix_distancefix.py",
        "m4_manifest": root / "reports/stage6a1/m4_joint_features_v002/full_v001/manifest.json",
        "m4_qa": root / "reports/stage6a1/m4_joint_features_v002/full_v001/m4_feature_assembly_qa.json",
        "m4_strict_pairs": root / "reports/stage6a1/m4_joint_features_v002/full_v001/m4_strict_target_pairs.csv",
        "m4_conservative_pairs": root / "reports/stage6a1/m4_joint_features_v002/full_v001/m4_conservative_target_pairs.csv",
        "m2_feature_scores": root / "reports/stage6a1/strict_tcwv_v001/full_v001/full_feature_scores.csv",
        "m3_feature_scores": root / "reports/stage6a1/independent_m3_v001/full_v002/m3_event_feature_scores.csv",
        "oof_manifest": root / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001/manifest.json",
        "oof_predictions": root / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001/grouped_loeo_oof_predictions.csv",
        "oof_metrics": root / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001/grouped_loeo_observed_metrics.csv",
        "oof_folds": root / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001/grouped_loeo_fold_diagnostics.csv",
    }


def verify_pinned_files(paths: dict[str, Path]) -> dict[str, str]:
    results = {}
    for key, expected in EXPECTED_SHA.items():
        path = paths[key]
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Pinned fingerprint mismatch for {key}: expected {expected}; got {actual}")
        results[key] = actual
        print(f"Pinned fingerprint PASS: {key} {actual}")
    return results

# ---- Build exact V004-compatible row matrices -------------------------------


def build_sources(root: Path, paths: dict[str, Path]) -> tuple[dict, dict, dict, dict]:
    m2_rows = read_csv(paths["m2_feature_scores"])
    m3_rows = read_csv(paths["m3_feature_scores"])
    oof_rows = read_csv(paths["oof_predictions"])
    oof_metrics = read_csv(paths["oof_metrics"])
    oof_folds = read_csv(paths["oof_folds"])

    m2_index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in m2_rows:
        feature = row["feature"]
        if feature in ("M2a_raw_GNSS_ZTD", "M2c_B0_calibrated_residual", "M2c_B1_calibrated_residual"):
            key = (row["event_id"], feature, row["target_window"])
            if key in m2_index:
                raise RuntimeError(f"Duplicate M2 source record: {key}")
            m2_index[key] = row

    m3_index = {r["event_id"]: r for r in m3_rows}
    if len(m3_index) != 111:
        raise RuntimeError(f"Expected 111 unique M3 events, got {len(m3_index)}")

    oof_index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in oof_rows:
        key = (row["cohort"], row["model"])
        oof_index.setdefault(key, []).append(row)
    for rows in oof_index.values():
        rows.sort(key=lambda r: int(r["row_order_within_cohort"]))

    metric_index = {(r["cohort"], r["model"]): r for r in oof_metrics}
    if len(metric_index) != 8:
        raise RuntimeError(f"Expected 8 OOF metric rows, got {len(metric_index)}")

    matrix_store: dict[tuple[str, str], list[dict[str, Any]]] = {}
    prediction_store: dict[tuple[str, str], list[float]] = {}
    label_store: dict[tuple[str, str], list[int]] = {}
    identity_store: dict[tuple[str, str], list[tuple]] = {}
    group_store: dict[tuple[str, str], list[str]] = {}
    event_store: dict[tuple[str, str], list[str]] = {}
    matrix_hashes: dict[str, dict[str, str]] = {}

    for cohort, info in COHORTS.items():
        pair_path = root / "reports/stage6a1/m4_joint_features_v002/full_v001" / info["pair_file"]
        pair_rows = read_csv(pair_path)
        if len(pair_rows) != info["n_events"] * 2:
            raise RuntimeError(f"{cohort}: wrong pair row count")
        event_seen = set()
        matrices = {model: [] for model in MODELS}
        for i in range(0, len(pair_rows), 2):
            w0, w1 = pair_rows[i:i + 2]
            eid = w0["event_id"]
            if w1["event_id"] != eid or (w0["label"], w1["label"]) != ("0", "1"):
                raise RuntimeError(f"{cohort}: malformed W0/W1 pair at rows {i+1}-{i+2}")
            if (w0["analysis_window"], w1["analysis_window"]) != ("W0", "W1"):
                raise RuntimeError(f"{cohort}: W0/W1 order mismatch for {eid}")
            if eid in event_seen:
                raise RuntimeError(f"{cohort}: duplicate event {eid}")
            event_seen.add(eid)
            if w0["component_id"] != w1["component_id"]:
                raise RuntimeError(f"{cohort}: event pair spans components: {eid}")

            m3 = m3_index.get(eid)
            if m3 is None or m3["origin_time_utc"] != w0["origin_time_utc"]:
                raise RuntimeError(f"{cohort}: M3 timestamp lineage mismatch: {eid}")
            if m3.get("m3_feature_status") != "PASS":
                raise RuntimeError(f"{cohort}: M3 source status is not PASS for {eid}: {m3.get('m3_feature_status')} ")
            if m3["station_id"].strip().upper() != w0["station_id"].strip().upper():
                raise RuntimeError(f"{cohort}: M3 station mismatch: {eid}")

            for row, win, m2a_window, m2c_feature, m3max, m3q95 in (
                (w0, "W0", "W0", "M2c_B0_calibrated_residual", "p_vtec_max", "p_vtec_q95"),
                (w1, "W1", "W1", "M2c_B1_calibrated_residual", "t_vtec_max", "t_vtec_q95"),
            ):
                r_a = m2_index.get((eid, "M2a_raw_GNSS_ZTD", m2a_window))
                r_c = m2_index.get((eid, m2c_feature, win))
                if r_a is None or r_c is None:
                    raise RuntimeError(f"{cohort}: missing M2a/M2c row for {eid}/{win}")
                if r_a["status"] != "PASS" or r_c["status"] != "PASS":
                    raise RuntimeError(f"{cohort}: target M2a/M2c source status failure for {eid}/{win}")
                if r_a["baseline"] != ("B0" if win == "W0" else "B1") or r_a["target_window"] != win:
                    raise RuntimeError(f"{cohort}: M2a baseline/window mismatch for {eid}/{win}")
                if r_c["target_window"] != win:
                    raise RuntimeError(f"{cohort}: M2c target window mismatch for {eid}/{win}")

                a_features = [float(r_a["feature_max_abs_robust_z"]), float(r_a["feature_q95_abs_robust_z"])]
                c_features = [float(r_c["feature_max_abs_robust_z"]), float(r_c["feature_q95_abs_robust_z"])]
                i_features = [float(m3[m3max]), float(m3[m3q95])]
                if not all(math.isfinite(x) for x in a_features + c_features + i_features):
                    raise RuntimeError(f"{cohort}: non-finite feature value for {eid}/{win}")

                # Reconcile the exact stored M2c/M3 values to the M4 pair package.
                if not math.isclose(c_features[0], float(row["m2c_max_abs_robust_z"]), rel_tol=0.0, abs_tol=1e-12):
                    raise RuntimeError(f"{cohort}: M2c max mismatch for {eid}/{win}")
                if not math.isclose(c_features[1], float(row["m2c_q95_abs_robust_z"]), rel_tol=0.0, abs_tol=1e-12):
                    raise RuntimeError(f"{cohort}: M2c q95 mismatch for {eid}/{win}")
                if not math.isclose(i_features[0], float(row["m3_vtec_max_abs_robust_z"]), rel_tol=0.0, abs_tol=1e-12):
                    raise RuntimeError(f"{cohort}: M3 max mismatch for {eid}/{win}")
                if not math.isclose(i_features[1], float(row["m3_vtec_q95_abs_robust_z"]), rel_tol=0.0, abs_tol=1e-12):
                    raise RuntimeError(f"{cohort}: M3 q95 mismatch for {eid}/{win}")

                label = int(row["label"])
                group = row["component_id"]
                for model, feature_values in (
                    ("M2a", a_features), ("M2c", c_features),
                    ("M3", i_features), ("M4", c_features + i_features),
                ):
                    sample = {
                        "event_id": eid,
                        "label": label,
                        "component_id": group,
                    }
                    for j, val in enumerate(feature_values):
                        sample[f"f{j}"] = val
                    matrices[model].append(sample)

        if len(event_seen) != info["n_events"]:
            raise RuntimeError(f"{cohort}: event count mismatch")
        all_groups = {s["component_id"] for s in matrices["M2a"]}
        if len(all_groups) != info["n_components"]:
            raise RuntimeError(f"{cohort}: component count mismatch")
        observed_group_sizes: dict[str, set[int]] = {}
        observed_group_event_counts: dict[str, set[str]] = {}
        for row in pair_rows:
            observed_group_event_counts.setdefault(row["component_id"], set()).add(row["event_id"])
            observed_group_sizes.setdefault(row["component_id"], set()).add(int(row["component_size"]))
        for group, event_ids in observed_group_event_counts.items():
            if observed_group_sizes[group] != {len(event_ids)}:
                raise RuntimeError(f"{cohort}: component size mismatch for {group}")

        matrix_hashes[cohort] = {}
        for model in MODELS:
            # Exactly the matrix-hash serialization used in the passed preflight.
            entries = []
            for sample, pair_row in zip(matrices[model], pair_rows):
                # pair_rows are in the same row order for each model.
                entries.append({
                    "event_id": sample["event_id"],
                    "analysis_window": pair_row["analysis_window"],
                    "label": int(sample["label"]),
                    "component_id": sample["component_id"],
                    "features": [sample[f"f{j}"] for j in range(MODEL_FEATURE_COUNTS[model])],
                })
            digest = json_sha256(entries)
            expected = EXPECTED_MATRIX_SHA[cohort][model]
            if digest != expected:
                raise RuntimeError(f"Matrix fingerprint mismatch {cohort}/{model}: {digest} != {expected}")
            matrix_hashes[cohort][model] = digest
            key = (cohort, model)
            matrix_store[key] = matrices[model]

            oof = oof_index.get(key)
            expected_rows = info["n_events"] * 2
            if oof is None or len(oof) != expected_rows:
                raise RuntimeError(f"{cohort}/{model}: OOF row count mismatch")
            preds, labels, identities, groups, events = [], [], [], [], []
            for ix, (sample, oofrow, pairrow) in enumerate(zip(matrices[model], oof, pair_rows), start=1):
                identity = (sample["event_id"], pairrow["analysis_window"], sample["label"], sample["component_id"])
                oof_identity = (oofrow["event_id"], oofrow["analysis_window"], int(oofrow["label"]), oofrow["component_id"])
                if int(oofrow["row_order_within_cohort"]) != ix or identity != oof_identity:
                    raise RuntimeError(f"{cohort}/{model}: OOF row identity/order mismatch at {ix}")
                if oofrow["held_out_component_id"] != sample["component_id"]:
                    raise RuntimeError(f"{cohort}/{model}: held-out group mismatch at {ix}")
                pred = float(oofrow["prediction_probability_W1"])
                if not math.isfinite(pred) or not 0.0 <= pred <= 1.0:
                    raise RuntimeError(f"{cohort}/{model}: invalid OOF probability at {ix}")
                preds.append(pred)
                labels.append(int(sample["label"]))
                identities.append(identity)
                groups.append(sample["component_id"])
                events.append(sample["event_id"])
            metric = metric_index[key]
            auc = roc_auc(preds, labels)
            pra = pr_auc(preds, labels)
            if not math.isclose(auc, float(metric["roc_auc_W1_vs_W0"]), rel_tol=0.0, abs_tol=1e-14):
                raise RuntimeError(f"{cohort}/{model}: saved ROC AUC mismatch")
            if not math.isclose(pra, float(metric["pr_auc_W1"]), rel_tol=0.0, abs_tol=1e-14):
                raise RuntimeError(f"{cohort}/{model}: saved PR AUC mismatch")
            prediction_store[key] = preds
            label_store[key] = labels
            identity_store[key] = identities
            group_store[key] = groups
            event_store[key] = events
            print(f"Preflight PASS: {cohort}/{model}, matrix={digest}, OOF={expected_rows}")

    if len(oof_rows) != 1400 or len(oof_metrics) != 8 or len(oof_folds) != 284:
        raise RuntimeError("OOF output row-count mismatch")

    # Cross-model exact alignment within each cohort.
    for cohort in COHORTS:
        baseline = identity_store[(cohort, "M2a")]
        for model in MODELS[1:]:
            if identity_store[(cohort, model)] != baseline:
                raise RuntimeError(f"Cross-model alignment failure: {cohort}/{model}")

    stores = {
        "matrices": matrix_store,
        "predictions": prediction_store,
        "labels": label_store,
        "identities": identity_store,
        "groups": group_store,
        "events": event_store,
        "metrics": metric_index,
        "matrix_hashes": matrix_hashes,
    }
    return stores, {"m2_rows": m2_rows, "m3_rows": m3_rows}, oof_rows, oof_folds

# ---- AUC component label-swap full-refit permutation -----------------------


def generate_flip_patterns(samples: list[dict[str, Any]], seed: int, n_perm: int):
    groups = sorted({str(s["component_id"]) for s in samples})
    rng = random.Random(seed)
    for idx in range(n_perm):
        flipped = tuple(group for group in groups if rng.random() < 0.5)
        yield idx, flipped


def run_auc_test(
    out_dir: Path,
    cohort: str,
    model: str,
    samples: list[dict[str, Any]],
    observed_preds: list[float],
    labels: list[int],
    seed: int,
    workers: int,
    batch_size: int,
) -> dict[str, Any]:
    test_dir = out_dir / "checkpoints" / "auc_refit" / cohort / model
    test_dir.mkdir(parents=True, exist_ok=True)
    expected_auc = roc_auc(observed_preds, labels)
    obs_stat = abs(expected_auc - 0.5)
    patterns = iter(generate_flip_patterns(samples, seed, N_PERM))
    all_values: list[float] = []
    chunk_hashes: list[dict[str, Any]] = []
    started = time.perf_counter()
    n_groups = len({s["component_id"] for s in samples})

    print(f"\nAUC refit permutations: {cohort}/{model}; groups={n_groups}; workers={workers}; batch={batch_size}")
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_worker_init,
        initargs=(samples, [f"f{i}" for i in range(MODEL_FEATURE_COUNTS[model])]),
    ) as executor:
        for start in range(0, N_PERM, batch_size):
            stop = min(N_PERM, start + batch_size)
            expected_patterns = [next(patterns) for _ in range(stop - start)]
            checkpoint = test_dir / f"batch_{start:05d}_{stop:05d}.json"
            if checkpoint.exists():
                payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                if payload.get("schema") != "LAIC_GUARD_AUC_REFIT_CHECKPOINT_v001":
                    raise RuntimeError(f"Checkpoint schema mismatch: {checkpoint}")
                if (payload.get("cohort"), payload.get("model"), payload.get("seed"), payload.get("n_perm"), payload.get("start_index_inclusive"), payload.get("stop_index_exclusive")) != (cohort, model, seed, N_PERM, start, stop):
                    raise RuntimeError(f"Checkpoint identity/range mismatch: {checkpoint}")
                entries = payload.get("entries", [])
                if len(entries) != stop - start:
                    raise RuntimeError(f"Checkpoint row count mismatch: {checkpoint}")
                values = []
                for entry, (expected_idx, expected_flips) in zip(entries, expected_patterns):
                    if entry.get("permutation_index") != expected_idx or tuple(entry.get("flipped_components", [])) != expected_flips:
                        raise RuntimeError(f"Checkpoint randomization-sequence mismatch: {checkpoint}")
                    value = float(entry["permuted_auc"])
                    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                        raise RuntimeError(f"Invalid checkpoint AUC value: {checkpoint}")
                    values.append(value)
                all_values.extend(values)
                chunk_hashes.append({"file": checkpoint.name, "sha256": sha256_file(checkpoint), "rows": len(entries)})
                print(f"  RESUME verified batch {start+1}-{stop}/{N_PERM}")
                continue

            tasks = expected_patterns
            results = list(executor.map(_worker_auc_permutation, tasks, chunksize=1))
            entries = []
            for (expected_idx, expected_flips), (result_idx, value, result_flips) in zip(expected_patterns, results):
                if result_idx != expected_idx or result_flips != expected_flips:
                    raise RuntimeError("Parallel worker returned a misordered permutation result")
                entries.append({
                    "permutation_index": result_idx,
                    "flipped_components": list(result_flips),
                    "permuted_auc": value,
                })
                all_values.append(value)
            payload = {
                "schema": "LAIC_GUARD_AUC_REFIT_CHECKPOINT_v001",
                "cohort": cohort,
                "model": model,
                "seed": seed,
                "n_perm": N_PERM,
                "start_index_inclusive": start,
                "stop_index_exclusive": stop,
                "entries": entries,
            }
            write_json_atomic(checkpoint, payload)
            chunk_hashes.append({"file": checkpoint.name, "sha256": sha256_file(checkpoint), "rows": len(entries)})
            elapsed = time.perf_counter() - started
            rate = len(all_values) / elapsed if elapsed else float("nan")
            print(f"  SAVED batch {start+1}-{stop}/{N_PERM}; elapsed={elapsed:.1f}s; this-test rate={rate:.2f} permutations/s")

    if len(all_values) != N_PERM:
        raise RuntimeError(f"{cohort}/{model}: expected {N_PERM} AUC permutations, got {len(all_values)}")
    extreme = sum(1 for value in all_values if abs(value - 0.5) >= obs_stat - 1e-12)
    p_value = (extreme + 1) / (N_PERM + 1)
    summary = {
        "schema": "LAIC_GUARD_AUC_REFIT_RESULT_v001",
        "cohort": cohort,
        "model": model,
        "n_events": len(samples) // 2,
        "n_rows": len(samples),
        "n_components": n_groups,
        "observed_auc_w1_vs_w0": expected_auc,
        "observed_abs_departure_from_0_5": obs_stat,
        "null_distribution": distribution_summary(all_values),
        "extreme_count": extreme,
        "p_value_two_sided_monte_carlo": p_value,
        "permutations": N_PERM,
        "seed": seed,
        "method": "component_level_paired_label_swap_full_grouped_LOEO_refit",
        "component_exchangeability_assumption": True,
        "checkpoint_batches": chunk_hashes,
        "elapsed_seconds_this_invocation": time.perf_counter() - started,
        "status": "COMPLETE",
    }
    write_json_atomic(test_dir / "result.json", summary)
    # Store all null statistics in a compact row-oriented CSV for audit/reanalysis.
    null_rows = [{"permutation_index": i, "permuted_auc": value} for i, value in enumerate(all_values)]
    write_csv_atomic(test_dir / "null_distribution.csv", null_rows, ["permutation_index", "permuted_auc"])
    summary["null_distribution_file"] = "null_distribution.csv"
    summary["null_distribution_sha256"] = sha256_file(test_dir / "null_distribution.csv")
    write_json_atomic(test_dir / "result.json", summary)
    print(f"AUC COMPLETE: {cohort}/{model}: AUC={expected_auc:.6f}; extreme={extreme}/{N_PERM}; p={p_value:.6g}")
    return summary

# ---- Bootstrap and component sign-flip/model-swap helpers -------------------


def bootstrap_auc_ci(samples: list[dict[str, Any]], preds: list[float], seed: int) -> dict[str, Any]:
    if len(samples) != len(preds):
        raise ValueError("Bootstrap sample/prediction length mismatch")
    by_group: dict[str, list[tuple[float, int]]] = {}
    for sample, pred in zip(samples, preds):
        by_group.setdefault(str(sample["component_id"]), []).append((pred, int(sample["label"])))
    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError("At least two groups required for bootstrap")
    for group in groups:
        if {label for _, label in by_group[group]} != {0, 1}:
            raise ValueError(f"Bootstrap group lacks both labels: {group}")
    rng = random.Random(seed)
    aucs = []
    for _ in range(N_BOOT):
        selected = [groups[rng.randrange(len(groups))] for _ in groups]
        scores, labels = [], []
        for group in selected:
            for pred, label in by_group[group]:
                scores.append(pred)
                labels.append(label)
        aucs.append(roc_auc(scores, labels))
    aucs.sort()
    lo = aucs[int(0.025 * len(aucs))]
    hi = aucs[min(len(aucs) - 1, int(0.975 * len(aucs)))]
    return {
        "ci95_low": lo,
        "ci95_high": hi,
        "n_bootstrap": N_BOOT,
        "seed": seed,
        "scope": "component_bootstrap_conditional_on_fixed_OOF_predictions",
        "quantile_rule": "sorted[index=int(p*n_boot)]",
    }


def component_signflip(diffs: list[float], group_ids: list[str], seed: int) -> dict[str, Any]:
    if len(diffs) != len(group_ids) or not diffs:
        raise ValueError("Sign-flip input length mismatch or empty")
    by_group: dict[str, list[float]] = {}
    for diff, group in zip(diffs, group_ids):
        value = float(diff)
        if not math.isfinite(value) or not str(group).strip():
            raise ValueError("Invalid sign-flip value or group")
        by_group.setdefault(str(group).strip(), []).append(value)
    groups = sorted(by_group)
    effects = [sum(by_group[group]) / len(by_group[group]) for group in groups]
    observed = sum(effects) / len(effects)
    if len(groups) <= 16:
        total = 1 << len(groups)
        nulls = []
        for mask in range(total):
            stat = sum((1.0 if (mask >> i) & 1 else -1.0) * effect for i, effect in enumerate(effects)) / len(groups)
            nulls.append(stat)
        method = "EXACT_COMPONENT_SIGN_FLIP"
        actual_seed: int | str = "NA"
        actual_n = total
        extreme = sum(1 for stat in nulls if abs(stat) >= abs(observed) - 1e-12)
        p = extreme / total
    else:
        rng = random.Random(seed)
        nulls = []
        for _ in range(N_PERM):
            stat = sum((1.0 if rng.random() < 0.5 else -1.0) * effect for effect in effects) / len(groups)
            nulls.append(stat)
        extreme = sum(1 for stat in nulls if abs(stat) >= abs(observed) - 1e-12)
        p = (extreme + 1) / (N_PERM + 1)
        method = "MONTE_CARLO_COMPONENT_SIGN_FLIP"
        actual_seed = seed
        actual_n = N_PERM
    return {
        "effect_mean_component_means": observed,
        "component_effects": {g: e for g, e in zip(groups, effects)},
        "p_value_two_sided": p,
        "extreme_count": extreme,
        "null_distribution": distribution_summary(nulls) if actual_n == N_PERM else {
            "null_median": float(statistics.median(nulls)),
            "null_q05_nearest_rank": float(nearest_rank(nulls, 0.05)),
            "null_q95_nearest_rank": float(nearest_rank(nulls, 0.95)),
            "null_min": float(min(nulls)),
            "null_max": float(max(nulls)),
        },
        "n_events": len(diffs),
        "n_components": len(groups),
        "method": method,
        "n_permutations": actual_n,
        "seed": actual_seed,
        "weighting": "equal_weight_per_component",
        "component_exchangeability_assumption": True,
        "null_values": nulls,
    }


def paired_component_model_swap(
    preds_a: list[float], preds_b: list[float], labels: list[int],
    group_ids: list[str], event_ids: list[str], seed: int,
) -> dict[str, Any]:
    n = len(labels)
    if not (len(preds_a) == len(preds_b) == len(group_ids) == len(event_ids) == n):
        raise ValueError("Paired model-swap input length mismatch")
    by_event: dict[str, list[int]] = {}
    by_group: dict[str, list[int]] = {}
    for i in range(n):
        event = str(event_ids[i]).strip()
        group = str(group_ids[i]).strip()
        if not event or not group:
            raise ValueError("Blank event or group ID in paired model swap")
        by_event.setdefault(event, []).append(i)
        by_group.setdefault(group, []).append(i)
    for event, indices in by_event.items():
        if len(indices) != 2 or sorted(labels[i] for i in indices) != [0, 1]:
            raise ValueError(f"Event {event} is not one complete 0/1 pair")
        if group_ids[indices[0]] != group_ids[indices[1]]:
            raise ValueError(f"Event {event} spans multiple components")
    groups = sorted(by_group)
    auc_a = roc_auc(preds_a, labels)
    auc_b = roc_auc(preds_b, labels)
    delta = auc_a - auc_b
    threshold = abs(delta) - 1e-12
    if len(groups) <= 16:
        total = 1 << len(groups)
        nulls = []
        for mask in range(total):
            flipped = {groups[i] for i in range(len(groups)) if (mask >> i) & 1}
            pa, pb = list(preds_a), list(preds_b)
            for group in flipped:
                for i in by_group[group]:
                    pa[i], pb[i] = pb[i], pa[i]
            nulls.append(roc_auc(pa, labels) - roc_auc(pb, labels))
        extreme = sum(1 for value in nulls if abs(value) >= threshold)
        p = extreme / total
        method = "EXACT_COMPONENT_BLOCK_MODEL_SWAP"
        actual_n = total
        actual_seed: int | str = "NA"
    else:
        rng = random.Random(seed)
        nulls = []
        for _ in range(N_PERM):
            flipped = {group for group in groups if rng.random() < 0.5}
            pa, pb = list(preds_a), list(preds_b)
            for group in flipped:
                for i in by_group[group]:
                    pa[i], pb[i] = pb[i], pa[i]
            nulls.append(roc_auc(pa, labels) - roc_auc(pb, labels))
        extreme = sum(1 for value in nulls if abs(value) >= threshold)
        p = (extreme + 1) / (N_PERM + 1)
        method = "MONTE_CARLO_COMPONENT_BLOCK_MODEL_SWAP"
        actual_n = N_PERM
        actual_seed = seed
    return {
        "auc_model_a": auc_a,
        "auc_model_b": auc_b,
        "delta_auc_a_minus_b": delta,
        "p_value_two_sided": p,
        "extreme_count": extreme,
        "null_distribution": distribution_summary(nulls) if actual_n == N_PERM else {
            "null_median": float(statistics.median(nulls)),
            "null_q05_nearest_rank": float(nearest_rank(nulls, 0.05)),
            "null_q95_nearest_rank": float(nearest_rank(nulls, 0.95)),
            "null_min": float(min(nulls)),
            "null_max": float(max(nulls)),
        },
        "n_events": len(by_event),
        "n_components": len(groups),
        "method": method,
        "n_permutations": actual_n,
        "seed": actual_seed,
        "interpretation": "conditional_on_fixed_OOF_predictions",
        "assumption": "model_identity_exchangeable_at_component_level",
        "null_values": nulls,
    }


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    clean = {}
    for key, value in pvalues.items():
        p = float(value)
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"Invalid p-value for {key}: {value}")
        clean[key] = p
    ordered = sorted(clean.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[key] = running
    return {key: adjusted[key] for key in clean}

# ---- Physical endpoint source reconstruction --------------------------------


def build_endpoint_differences(root: Path, cohort: str, pair_rows: list[dict[str, str]], source_data: dict[str, Any]) -> dict[str, tuple[list[float], list[str]]]:
    m2_index = {}
    for row in source_data["m2_rows"]:
        if row["feature"] in ("M2a_raw_GNSS_ZTD", "M2c_B0_calibrated_residual", "M2c_B1_calibrated_residual"):
            m2_index[(row["event_id"], row["feature"], row["target_window"])] = row
    m3_index = {r["event_id"]: r for r in source_data["m3_rows"]}
    by_event: dict[str, dict[str, dict[str, str]]] = {}
    for row in pair_rows:
        by_event.setdefault(row["event_id"], {})[row["analysis_window"]] = row
    specs = {
        "raw_gnss_ztd_q95": ("M2a_raw_GNSS_ZTD", "feature_q95_abs_robust_z", "M2a_raw_GNSS_ZTD"),
        "calibrated_era5_residual_q95": ("M2c_B0_calibrated_residual", "feature_q95_abs_robust_z", "M2c_B1_calibrated_residual"),
    }
    result = {}
    for endpoint in PHYSICAL_ENDPOINTS:
        diffs, groups = [], []
        for eid, windows in by_event.items():
            if set(windows) != {"W0", "W1"}:
                raise RuntimeError(f"Endpoint data lack W0/W1 pair: {cohort}/{eid}")
            if endpoint == "raw_gnss_ztd_q95":
                a = m2_index[(eid, "M2a_raw_GNSS_ZTD", "W0")]
                b = m2_index[(eid, "M2a_raw_GNSS_ZTD", "W1")]
                if a["status"] != "PASS" or b["status"] != "PASS":
                    raise RuntimeError(f"M2a q95 endpoint source not PASS: {eid}")
                v0, v1 = float(a["feature_q95_abs_robust_z"]), float(b["feature_q95_abs_robust_z"])
            elif endpoint == "calibrated_era5_residual_q95":
                a = m2_index[(eid, "M2c_B0_calibrated_residual", "W0")]
                b = m2_index[(eid, "M2c_B1_calibrated_residual", "W1")]
                if a["status"] != "PASS" or b["status"] != "PASS":
                    raise RuntimeError(f"M2c q95 endpoint source not PASS: {eid}")
                v0, v1 = float(a["feature_q95_abs_robust_z"]), float(b["feature_q95_abs_robust_z"])
            else:
                m3 = m3_index[eid]
                v0, v1 = float(m3["p_vtec_q95"]), float(m3["t_vtec_q95"])
            if not math.isfinite(v0) or not math.isfinite(v1):
                raise RuntimeError(f"Non-finite q95 endpoint for {eid}")
            diffs.append(v1 - v0)
            groups.append(windows["W0"]["component_id"])
        result[endpoint] = (diffs, groups)
    return result

# ---- Manifest and phases ------------------------------------------------------


def input_manifest(root: Path, paths: dict[str, Path]) -> dict[str, Any]:
    items = {}
    for name, path in paths.items():
        items[name] = {"path": str(path.relative_to(root)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    return items


def ensure_run_manifest(out_dir: Path, inputs: dict[str, Any], workers: int, batch_size: int) -> dict[str, Any]:
    manifest_path = out_dir / "manifest.json"
    config = {
        "n_auc_permutations_per_model_cohort": N_PERM,
        "n_bootstrap_per_model_cohort": N_BOOT,
        "seeds": {"auc_refit": SEED_AUC, "bootstrap": SEED_BOOT, "physical_signflip": SEED_PHYSICAL, "paired_model_swap": SEED_PAIRED},
        "auc_batch_size": batch_size,
        "models": list(MODELS),
        "cohorts": COHORTS,
        "paired_comparisons": [{"model_a": a, "model_b": b, "name": name} for a, b, name in COMPARISONS],
        "physical_endpoints": list(PHYSICAL_ENDPOINTS),
        "null_quantile_rule": "nearest_rank_ceil(p*n)-1",
        "primary_holm_families": {"auc": 4, "physical_endpoints": 3, "paired_model_comparisons": 2},
    }
    config_hash = json_sha256(config)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "LAIC_GUARD_STAGE6A1_INFERENCE_MANIFEST_v001":
            raise RuntimeError("Existing inference manifest schema mismatch")
        if manifest.get("config_sha256") != config_hash:
            raise RuntimeError("Existing inference package configuration differs; refusing to mix checkpoints")
        if manifest.get("inputs") != inputs:
            raise RuntimeError("Existing inference package input fingerprints differ")
        return manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "LAIC_GUARD_STAGE6A1_INFERENCE_MANIFEST_v001",
        "status": "IN_PROGRESS",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "config_sha256": config_hash,
        "inputs": inputs,
        "completed_phases": [],
        "completed_auc_tests": [],
        "notes": [
            "The strict target cohort is primary; conservative target cohort is sensitivity only.",
            "Physical null controls are not included in target classifier samples.",
            "AUC permutation patterns are drawn sequentially using random.Random(seed) in pinned V004 group order, then parallelized.",
            "Bootstrap intervals are conditional on fixed OOF predictions.",
            "Paired model swaps are conditional on fixed OOF predictions.",
            "Monte Carlo null q05/q95 summaries use nearest-rank quantiles; this descriptive summary rule does not alter p-value calculations.",
        ],
    }
    write_json_atomic(manifest_path, manifest)
    return manifest


def load_pair_rows(root: Path, cohort: str) -> list[dict[str, str]]:
    path = root / "reports/stage6a1/m4_joint_features_v002/full_v001" / COHORTS[cohort]["pair_file"]
    return read_csv(path)


def phase_auc(out_dir: Path, stores: dict, cohort_names: list[str], workers: int, batch_size: int, manifest: dict) -> None:
    summaries = []
    for cohort in cohort_names:
        for model in MODELS:
            key = (cohort, model)
            result = run_auc_test(
                out_dir, cohort, model,
                stores["matrices"][key],
                stores["predictions"][key], stores["labels"][key],
                SEED_AUC, workers, batch_size,
            )
            summaries.append(result)
            completed_key = f"{cohort}/{model}"
            if completed_key not in manifest["completed_auc_tests"]:
                manifest["completed_auc_tests"].append(completed_key)
            write_json_atomic(out_dir / "manifest.json", manifest)
    summary_path = out_dir / ("primary_auc_summary.json" if cohort_names == ["STRICT_TARGETS"] else "sensitivity_auc_summary.json")
    write_json_atomic(summary_path, {"schema": "LAIC_GUARD_AUC_SUMMARY_v001", "tests": summaries})
    phase_name = "primary_auc" if cohort_names == ["STRICT_TARGETS"] else "sensitivity_auc"
    if phase_name not in manifest["completed_phases"]:
        manifest["completed_phases"].append(phase_name)
    write_json_atomic(out_dir / "manifest.json", manifest)


def load_completed_auc(out_dir: Path, cohort: str, model: str) -> dict[str, Any]:
    path = out_dir / "checkpoints" / "auc_refit" / cohort / model / "result.json"
    if not path.exists():
        raise RuntimeError(f"Missing completed AUC result: {cohort}/{model}; run its AUC phase first")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "COMPLETE" or result.get("permutations") != N_PERM:
        raise RuntimeError(f"AUC result incomplete or wrong permutation count: {path}")
    return result


def phase_support(root: Path, out_dir: Path, stores: dict, source_data: dict[str, Any], cohort_names: list[str], manifest: dict) -> None:
    if cohort_names == ["STRICT_TARGETS"]:
        for required_model in MODELS:
            load_completed_auc(out_dir, "STRICT_TARGETS", required_model)
    boot_rows = []
    endpoint_rows = []
    comparison_rows = []
    null_dir = out_dir / "support_null_distributions"
    null_dir.mkdir(parents=True, exist_ok=True)

    for cohort in cohort_names:
        # Bootstrap CIs conditional on fixed OOF scores.
        for model in MODELS:
            key = (cohort, model)
            ci = bootstrap_auc_ci(stores["matrices"][key], stores["predictions"][key], SEED_BOOT)
            auc_result = stores["metrics"][key]
            boot_rows.append({
                "cohort": cohort,
                "model": model,
                "observed_auc": float(auc_result["roc_auc_W1_vs_W0"]),
                **ci,
            })

        # Three distinct q95 W1-W0 physical endpoints.
        pair_rows = load_pair_rows(root, cohort)
        endpoint_inputs = build_endpoint_differences(root, cohort, pair_rows, source_data)
        for endpoint, (diffs, groups) in endpoint_inputs.items():
            result = component_signflip(diffs, groups, SEED_PHYSICAL)
            null_values = result.pop("null_values")
            endpoint_rows.append({
                "cohort": cohort,
                "endpoint": endpoint,
                **{k: v for k, v in result.items() if k not in ("component_effects", "null_distribution")},
                "null_distribution": json.dumps(result["null_distribution"], sort_keys=True, separators=(",", ":")),
                "component_effects": json.dumps(result["component_effects"], sort_keys=True, separators=(",", ":")),
            })
            write_csv_atomic(
                null_dir / f"{cohort}__{endpoint}__signflip_null.csv",
                [{"permutation_or_sign_pattern_index": i, "null_statistic": v} for i, v in enumerate(null_values)],
                ["permutation_or_sign_pattern_index", "null_statistic"],
            )

        # Component-block model swaps, conditional on fixed OOF predictions.
        for model_a, model_b, name in COMPARISONS:
            key_a, key_b = (cohort, model_a), (cohort, model_b)
            for field in ("labels", "groups", "events", "identities"):
                if stores[field][key_a] != stores[field][key_b]:
                    raise RuntimeError(f"Paired comparison alignment failure: {cohort}/{name}/{field}")
            result = paired_component_model_swap(
                stores["predictions"][key_a], stores["predictions"][key_b],
                stores["labels"][key_a], stores["groups"][key_a], stores["events"][key_a],
                SEED_PAIRED,
            )
            null_values = result.pop("null_values")
            comparison_rows.append({
                "cohort": cohort,
                "comparison": name,
                "model_a": model_a,
                "model_b": model_b,
                **{k: v for k, v in result.items() if k != "null_distribution"},
                "null_distribution": json.dumps(result["null_distribution"], sort_keys=True, separators=(",", ":")),
            })
            write_csv_atomic(
                null_dir / f"{cohort}__{name}__model_swap_null.csv",
                [{"permutation_index": i, "delta_auc_a_minus_b": v} for i, v in enumerate(null_values)],
                ["permutation_index", "delta_auc_a_minus_b"],
            )

    # Primary Holm families ONLY: strict target cohort. The conservative phase
    # is sensitivity-only and must never replace or join the primary families.
    if cohort_names == ["STRICT_TARGETS"]:
        strict_auc = {model: load_completed_auc(out_dir, "STRICT_TARGETS", model)["p_value_two_sided_monte_carlo"] for model in MODELS}
        strict_endpoints = {r["endpoint"]: r["p_value_two_sided"] for r in endpoint_rows}
        strict_comparisons = {r["comparison"]: r["p_value_two_sided"] for r in comparison_rows}
        if set(strict_auc) != set(MODELS) or set(strict_endpoints) != set(PHYSICAL_ENDPOINTS) or set(strict_comparisons) != {"M2c_vs_M2a", "M4_vs_M3"}:
            raise RuntimeError("Primary Holm family is incomplete")
        holm = {
            "four_primary_auc_tests": holm_adjust(strict_auc),
            "three_distinct_physical_endpoints": holm_adjust(strict_endpoints),
            "two_primary_model_comparisons": holm_adjust(strict_comparisons),
            "scope": "STRICT_TARGETS only; conservative results are sensitivity analyses and are not included in these Holm families",
        }
        write_json_atomic(out_dir / "holm_adjustments_primary_strict_only.json", holm)

    suffix = "strict_targets" if cohort_names == ["STRICT_TARGETS"] else "conservative_targets_sensitivity"
    write_csv_atomic(out_dir / f"bootstrap_ci_summary__{suffix}.csv", boot_rows, list(boot_rows[0].keys()))
    write_csv_atomic(out_dir / f"physical_endpoint_signflip_summary__{suffix}.csv", endpoint_rows, list(endpoint_rows[0].keys()))
    write_csv_atomic(out_dir / f"paired_model_comparison_summary__{suffix}.csv", comparison_rows, list(comparison_rows[0].keys()))

    phase_name = "primary_support" if cohort_names == ["STRICT_TARGETS"] else "sensitivity_support"
    if phase_name not in manifest["completed_phases"]:
        manifest["completed_phases"].append(phase_name)
    write_json_atomic(out_dir / "manifest.json", manifest)

# ---- Main --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 6A.1 reproducible inference runner")
    parser.add_argument("--phase", choices=("preflight", "primary_auc", "sensitivity_auc", "primary_support", "sensitivity_support", "all"), default="preflight")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 12:
        parser.error("--workers must be between 1 and 12")
    if args.batch_size < 1 or args.batch_size > 1000:
        parser.error("--batch-size must be between 1 and 1000")

    root = Path.cwd()
    paths = source_paths(root)
    print("===== STAGE 6A.1 INFERENCE RUNNER v001 =====")
    print("Phase:", args.phase)
    print("AUC permutations/test:", N_PERM)
    print("Bootstrap reps/model/cohort:", N_BOOT)
    print("Workers:", args.workers, "Batch size:", args.batch_size)
    print("AUC seed:", SEED_AUC, "Bootstrap seed:", SEED_BOOT, "Physical sign-flip seed:", SEED_PHYSICAL, "Paired swap seed:", SEED_PAIRED)
    pinned = verify_pinned_files(paths)

    m4_dir = root / "reports/stage6a1/m4_joint_features_v002/full_v001"
    oof_dir = root / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001"
    if sha256_file(m4_dir / "manifest.json") != EXPECTED_SHA["m4_manifest"]:
        raise RuntimeError("M4 manifest fingerprint mismatch")
    if sha256_file(m4_dir / "m4_feature_assembly_qa.json") != EXPECTED_SHA["m4_qa"]:
        raise RuntimeError("M4 QA fingerprint mismatch")
    if sha256_file(oof_dir / "manifest.json") != EXPECTED_SHA["oof_manifest"]:
        raise RuntimeError("OOF manifest fingerprint mismatch")

    stores, source_data, oof_rows, fold_rows = build_sources(root, paths)
    inputs = input_manifest(root, paths)
    out_dir = root / "reports/stage6a1/inference_v001/full_v001"
    manifest = ensure_run_manifest(out_dir, inputs, args.workers, args.batch_size)
    manifest["last_invocation_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["pinned_source_fingerprints"] = pinned
    manifest["matrix_fingerprints"] = stores["matrix_hashes"]
    manifest["oof_row_count"] = len(oof_rows)
    manifest["fold_diagnostic_row_count"] = len(fold_rows)
    manifest["worker_count_last_invocation"] = args.workers
    write_json_atomic(out_dir / "manifest.json", manifest)

    manifest["preflight_complete"] = True
    if args.phase in ("primary_auc", "all"):
        phase_auc(out_dir, stores, ["STRICT_TARGETS"], args.workers, args.batch_size, manifest)
    if args.phase in ("sensitivity_auc", "all"):
        phase_auc(out_dir, stores, ["CONSERVATIVE_TARGETS"], args.workers, args.batch_size, manifest)
    if args.phase in ("primary_support", "all"):
        phase_support(root, out_dir, stores, source_data, ["STRICT_TARGETS"], manifest)
    if args.phase in ("sensitivity_support", "all"):
        phase_support(root, out_dir, stores, source_data, ["CONSERVATIVE_TARGETS"], manifest)

    # Mark completion only when all four explicitly scoped phases have completed.
    required = {"primary_auc", "sensitivity_auc", "primary_support", "sensitivity_support"}
    manifest["status"] = "COMPLETE" if required.issubset(set(manifest["completed_phases"])) else "PARTIAL_PHASES_COMPLETE_OR_IN_PROGRESS"
    manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(out_dir / "manifest.json", manifest)
    print("\n===== INFERENCE RUNNER STATUS =====")
    print("Output directory:", out_dir.relative_to(root))
    print("Completed phases:", ", ".join(manifest["completed_phases"]) or "none")
    print("Overall status:", manifest["status"])
    if args.phase == "preflight":
        print("Preflight only: no permutation, bootstrap, sign-flip or model-swap tests were run.")
    print("AUC permutations use full grouped-LOEO refits; no tuning was performed.")
    print("Bootstrap intervals are conditional on fixed OOF predictions.")
    print("Paired model comparisons are conditional on fixed OOF predictions.")
    print("Strict cohort alone enters the three primary Holm families.")
    print("INFERENCE PHASE COMPLETE")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
