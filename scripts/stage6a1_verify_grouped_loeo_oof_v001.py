#!/usr/bin/env python3
"""Read-only independent verifier for Stage 6A.1 grouped-LOEO OOF v001.

Checks runner identity, pinned dependencies, source/output hashes, manifest,
OOF row pairing, held-out component folds, fold diagnostics, recomputed metrics,
and deterministic reproduction of OOF probabilities using the pinned Stage 5B
implementation. Does not write or modify project files and performs no inference.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REPORTS = ROOT / "reports" / "stage6a1"
M2_SCORES = REPORTS / "strict_tcwv_v001" / "full_v001" / "full_feature_scores.csv"
M2_LEDGER = REPORTS / "strict_tcwv_v001" / "full_v001" / "full_event_eligibility_ledger.csv"
M3_SCORES = REPORTS / "independent_m3_v001" / "full_v002" / "m3_event_feature_scores.csv"
MEMBERSHIP = REPORTS / "strict_tcwv_v001" / "full_v001" / "full_dependency_component_membership.csv"
M4_DIR = REPORTS / "m4_joint_features_v002" / "full_v001"
M4_MANIFEST = M4_DIR / "manifest.json"
M4_QA = M4_DIR / "m4_feature_assembly_qa.json"
COHORTS = [
    ("STRICT_TARGETS", M4_DIR / "m4_strict_target_pairs.csv", 88, 36),
    ("CONSERVATIVE_TARGETS", M4_DIR / "m4_conservative_target_pairs.csv", 87, 35),
]
OUT_DIR = REPORTS / "model_evaluation_v001" / "grouped_loeo_oof_v001"
RUNNER = SCRIPTS / "stage6a1_run_grouped_loeo_oof_v001.py"
PREDICTIONS = OUT_DIR / "grouped_loeo_oof_predictions.csv"
METRICS = OUT_DIR / "grouped_loeo_observed_metrics.csv"
FOLDS = OUT_DIR / "grouped_loeo_fold_diagnostics.csv"
MANIFEST = OUT_DIR / "manifest.json"

EXPECTED = {
    "runner": "7C807880BEBA6996CFC9BA8AC95A77753222C186C3B7E90DED68167595360B4D",
    "manifest": "6D9BB35B48A326A5D1AB527C1CFD1830979DEADDFC19FD627D1CE662653E8234",
    "outputs": {
        "grouped_loeo_oof_predictions.csv": "3FAC2F02C774150A40699786B3A7195012D70BB0301D873F0A6D8D850CC8C5ED",
        "grouped_loeo_observed_metrics.csv": "99ED42F99CAB46D6A83D23D53DBDC78E08414D6F472743F39CF645E67AD0F5B2",
        "grouped_loeo_fold_diagnostics.csv": "3E5AE08AFF9EC64AE084193D2A7E26C15458D9EAC92C9F1BB7128D85069BDA61",
    },
    "stage5b": "06BC22ED858D65CB56A0309185E435463817B0F6E8A455F43F6AA7BEE971476C",
    "stage4b": "91F741C1500FB263F229DDF1D69590B357158CBFB42105F3F992AEA0DA3994B0",
    "m4_manifest": "30810D6540541A6B75E7D5F70E2E95F43FE798647A4E799D63176D2A03B72DC3",
    "m4_qa": "7FB292A279B2AC873B28D8D6EE17C321BB8BE9BF27CF8339A6435D92BC06D20F",
}
MODELS = ("M2a", "M2c", "M3", "M4")
EXPECTED_N = {"STRICT_TARGETS": (88, 36), "CONSERVATIVE_TARGETS": (87, 35)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def ffloat(row: dict[str, str], field: str, context: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"Non-finite {context}/{field}: {row[field]!r}")
    return value


def matrix_auc(scores: list[float], labels: list[int]) -> float:
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    require(bool(positives) and bool(negatives), "AUC requires both labels")
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def matrix_pr_auc(scores: list[float], labels: list[int]) -> float:
    n_pos = sum(labels)
    require(n_pos > 0, "PR-AUC requires positive labels")
    tp = fp = 0
    prev_recall = area = 0.0
    for _, y in sorted(zip(scores, labels), key=lambda x: -x[0]):
        tp += int(y == 1)
        fp += int(y == 0)
        recall = tp / n_pos
        area += (tp / (tp + fp)) * (recall - prev_recall)
        prev_recall = recall
    return area


def main() -> int:
    print("===== STAGE 6A.1 GROUPED-LOEO OOF INDEPENDENT VERIFICATION v001 =====")
    print("Mode: read-only; no new model outputs, no inference, no file modification")

    # Exact runner identity: this is the corrected checksum supplied with the file.
    runner_sha = sha256_file(RUNNER)
    require(runner_sha == EXPECTED["runner"],
            f"Runner SHA mismatch: expected {EXPECTED['runner']}, got {runner_sha}")
    print("Runner identity PASS:", runner_sha)

    stage5b = SCRIPTS / "stage5b_hardened_audit_v002.py"
    stage4b = SCRIPTS / "stage4b_scale_full_tier1_cohort_v001.py"
    require(sha256_file(stage5b) == EXPECTED["stage5b"], "Stage 5B source hash mismatch")
    require(sha256_file(stage4b) == EXPECTED["stage4b"], "Stage 4B source hash mismatch")
    require(sha256_file(M4_MANIFEST) == EXPECTED["m4_manifest"], "M4 manifest hash mismatch")
    require(sha256_file(M4_QA) == EXPECTED["m4_qa"], "M4 QA hash mismatch")
    print("Pinned Stage 5B/Stage 4B and M4 provenance fingerprints PASS")

    require(sha256_file(MANIFEST) == EXPECTED["manifest"], "OOF manifest SHA mismatch")
    print("OOF manifest SHA256 PASS:", EXPECTED["manifest"])

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "LAIC_GUARD_STAGE6A1_GROUPED_LOEO_OOF_MANIFEST_V001", "Unexpected OOF manifest schema")
    require(manifest.get("status") == "COMPLETED_DESCRIPTIVE_OOF_ONLY", "Unexpected OOF manifest status")
    require(manifest.get("runner_sha256") == runner_sha, "Manifest runner hash does not match script")
    require(manifest.get("inference_status", {}).get("primary_component_label_swap_permutations") == "NOT_RUN", "Permutation status is not NOT_RUN")
    require(manifest.get("inference_status", {}).get("group_bootstrap_ci") == "NOT_RUN", "Bootstrap status is not NOT_RUN")
    require(manifest.get("inference_status", {}).get("physical_endpoint_component_sign_flips") == "NOT_RUN", "Physical sign-flip status is not NOT_RUN")
    require(manifest.get("inference_status", {}).get("paired_model_component_swaps") == "NOT_RUN", "Paired comparison status is not NOT_RUN")
    print("Manifest schema, status, runner lineage and inference flags PASS")

    # Verify all recorded input hashes against the present source files.
    input_paths = {
        "reports/stage6a1/strict_tcwv_v001/full_v001/full_feature_scores.csv": REPORTS / "strict_tcwv_v001/full_v001/full_feature_scores.csv",
        "reports/stage6a1/strict_tcwv_v001/full_v001/full_event_eligibility_ledger.csv": M2_LEDGER,
        "reports/stage6a1/independent_m3_v001/full_v002/m3_event_feature_scores.csv": M3_SCORES,
        "reports/stage6a1/strict_tcwv_v001/full_v001/full_dependency_component_membership.csv": MEMBERSHIP,
        "reports/stage6a1/strict_tcwv_v001/full_v001/full_dependency_component_membership.csv": MEMBERSHIP,
        "reports/stage6a1/m4_joint_features_v002/full_v001/manifest.json": M4_MANIFEST,
        "reports/stage6a1/m4_joint_features_v002/full_v001/m4_feature_assembly_qa.json": M4_QA,
        "reports/stage6a1/m4_joint_features_v002/full_v001/m4_strict_target_pairs.csv": M4_DIR / "m4_strict_target_pairs.csv",
        "reports/stage6a1/m4_joint_features_v002/full_v001/m4_conservative_target_pairs.csv": M4_DIR / "m4_conservative_target_pairs.csv",
    }
    for rel, path in input_paths.items():
        expected_hash = manifest.get("input_sha256", {}).get(rel)
        if expected_hash is not None:
            require(sha256_file(path) == expected_hash, f"Input file fingerprint mismatch: {rel}")
    print("Manifest-recorded input fingerprints PASS")

    # Exact contents and hashes of generated files.
    expected_files = {
        "grouped_loeo_oof_predictions.csv": PREDICTIONS,
        "grouped_loeo_observed_metrics.csv": METRICS,
        "grouped_loeo_fold_diagnostics.csv": FOLDS,
        "manifest.json": MANIFEST,
    }
    actual_files = {p.name for p in OUT_DIR.iterdir() if p.is_file()}
    require(actual_files == set(expected_files), f"Unexpected OOF package file set: {sorted(actual_files)}")
    for name, path in expected_files.items():
        if name == "manifest.json":
            actual_hash = sha256_file(path)
        else:
            actual_hash = sha256_file(path)
            require(actual_hash == EXPECTED["outputs"][name], f"Output SHA mismatch: {name}; got {actual_hash}")
            require(manifest.get("output_sha256", {}).get(name) == actual_hash, f"Manifest output hash mismatch: {name}")
        print(f"Output fingerprint PASS: {name} {actual_hash}")

    pred_rows = read_csv(PREDICTIONS)
    metric_rows = read_csv(METRICS)
    fold_rows = read_csv(FOLDS)
    require(len(pred_rows) == 1400, f"Expected 1400 prediction rows, got {len(pred_rows)}")
    require(len(metric_rows) == 8, f"Expected 8 metric rows, got {len(metric_rows)}")
    require(len(fold_rows) == 284, f"Expected 284 fold rows, got {len(fold_rows)}")
    print("Output row counts PASS: predictions=1400, metrics=8, folds=284")

    # Validate exact dependencies and load the original grouped-LOEO routine.
    sys.path.insert(0, str(SCRIPTS))
    from stage5b_hardened_audit_v002 import grouped_loeo

    m2_rows = read_csv(M2_SCORES)
    m2a: dict[tuple[str, str], dict[str, str]] = {}
    for row in m2_rows:
        if row.get("feature") == "M2a_raw_GNSS_ZTD":
            key = (row["event_id"], row["target_window"])
            require(key not in m2a, f"Duplicate M2a record {key}")
            m2a[key] = row

    pred_grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    metric_index: dict[tuple[str, str], dict[str, str]] = {}
    fold_index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in pred_rows:
        key = (row["cohort"], row["model"])
        pred_grouped[key].append(row)
    for row in metric_rows:
        key = (row["cohort"], row["model"])
        require(key not in metric_index, f"Duplicate metric row {key}")
        metric_index[key] = row
    for row in fold_rows:
        key = (row["cohort"], row["model"], row["held_out_component_id"])
        require(key not in fold_index, f"Duplicate fold row {key}")
        fold_index[key] = row

    # Ensure the 8 evaluations exactly match the expected cohort/model grid.
    expected_eval_keys = {(c, m) for c, _, _, _ in COHORTS for m in MODELS}
    require(set(pred_grouped) == expected_eval_keys, "Prediction cohort/model grid mismatch")
    require(set(metric_index) == expected_eval_keys, "Metric cohort/model grid mismatch")

    # Deterministically reconstruct each model matrix, reproduce the exact OOF
    # calls, and check saved probabilities and descriptive metrics.
    total_reproduced = 0
    expected_fold_keys = set()
    for cohort, pair_path, n_events, n_components in COHORTS:
        pair_rows = read_csv(pair_path)
        require(len(pair_rows) == 2 * n_events, f"{cohort}: M4 pair row count mismatch")
        cohort_event_order: list[str] = []
        cohort_groups: dict[str, set[str]] = defaultdict(set)
        cohort_pair_order: list[tuple[str, str, int, str]] = []
        for i in range(0, len(pair_rows), 2):
            a, b = pair_rows[i:i+2]
            eid = a["event_id"]
            require(b["event_id"] == eid, f"{cohort}: pair identity mismatch at {i}")
            require((a["analysis_window"], b["analysis_window"]) == ("W0", "W1"), f"{cohort}: bad windows for {eid}")
            require((a["label"], b["label"]) == ("0", "1"), f"{cohort}: bad labels for {eid}")
            require(a["component_id"] == b["component_id"], f"{cohort}: event spans components {eid}")
            cohort_event_order.append(eid)
            cohort_groups[a["component_id"]].add(eid)
            cohort_pair_order.extend([
                (eid, "W0", 0, a["component_id"]),
                (eid, "W1", 1, b["component_id"]),
            ])
        require(len(set(cohort_event_order)) == n_events, f"{cohort}: duplicate/missing event pair")
        require(len(cohort_groups) == n_components, f"{cohort}: component count mismatch")

        for model in MODELS:
            saved = sorted(pred_grouped[(cohort, model)], key=lambda r: int(r["row_order_within_cohort"]))
            require(len(saved) == 2 * n_events, f"{cohort}/{model}: prediction row count mismatch")
            require([int(r["row_order_within_cohort"]) for r in saved] == list(range(1, 2*n_events+1)), f"{cohort}/{model}: row-order sequence mismatch")

            samples: list[dict[str, Any]] = []
            labels: list[int] = []
            for i, pair in enumerate(range(0, len(pair_rows), 2)):
                w0, w1 = pair_rows[pair:pair+2]
                eid = w0["event_id"]
                for source_row, window in ((w0, "W0"), (w1, "W1")):
                    arow = m2a.get((eid, window))
                    require(arow is not None, f"{cohort}/{model}: missing M2a source {eid}/{window}")
                    if model == "M2a":
                        require(arow["status"] == "PASS", f"{cohort}: target M2a source not PASS {eid}/{window}")
                        feats = [
                            ffloat(arow, "feature_max_abs_robust_z", f"{eid}/{window}/M2a"),
                            ffloat(arow, "feature_q95_abs_robust_z", f"{eid}/{window}/M2a"),
                        ]
                    elif model == "M2c":
                        feats = [
                            ffloat(source_row, "m2c_max_abs_robust_z", f"{eid}/{window}/M2c"),
                            ffloat(source_row, "m2c_q95_abs_robust_z", f"{eid}/{window}/M2c"),
                        ]
                    elif model == "M3":
                        feats = [
                            ffloat(source_row, "m3_vtec_max_abs_robust_z", f"{eid}/{window}/M3"),
                            ffloat(source_row, "m3_vtec_q95_abs_robust_z", f"{eid}/{window}/M3"),
                        ]
                    else:
                        feats = [
                            ffloat(source_row, "m2c_max_abs_robust_z", f"{eid}/{window}/M4"),
                            ffloat(source_row, "m2c_q95_abs_robust_z", f"{eid}/{window}/M4"),
                            ffloat(source_row, "m3_vtec_max_abs_robust_z", f"{eid}/{window}/M4"),
                            ffloat(source_row, "m3_vtec_q95_abs_robust_z", f"{eid}/{window}/M4"),
                        ]
                    sample: dict[str, Any] = {
                        "event_id": eid,
                        "label": int(source_row["label"]),
                        "component_id": source_row["component_id"],
                    }
                    for j, value in enumerate(feats):
                        sample[f"f{j}"] = value
                    samples.append(sample)
                    labels.append(int(source_row["label"]))

            fkeys = [f"f{i}" for i in range(len(samples[0]) - 3)]
            # len(sample)-3 equals feature count because metadata has 3 keys.
            preds = grouped_loeo(samples, fkeys, "component_id")
            require(len(preds) == len(saved), f"{cohort}/{model}: reproduced prediction count mismatch")

            for idx, (sample, saved_row, pred) in enumerate(zip(samples, saved, preds), start=1):
                expected_meta = (
                    sample["event_id"], sample["label"], sample["component_id"]
                )
                actual_meta = (
                    saved_row["event_id"], int(saved_row["label"]), saved_row["component_id"]
                )
                require(actual_meta == expected_meta, f"{cohort}/{model}: prediction row provenance mismatch at {idx}")
                require(saved_row["analysis_window"] == ("W0" if sample["label"] == 0 else "W1"), f"{cohort}/{model}: window/label mismatch at {idx}")
                saved_p = float(saved_row["prediction_probability_W1"])
                require(math.isfinite(saved_p) and 0.0 <= saved_p <= 1.0, f"{cohort}/{model}: invalid probability at {idx}")
                require(saved_p == float(format(float(pred), ".17g")), f"{cohort}/{model}: exact OOF probability mismatch at {idx}: {saved_p} vs {pred}")
                require(saved_row["held_out_component_id"] == sample["component_id"], f"{cohort}/{model}: held-out component mismatch at {idx}")
                total_reproduced += 1

            scores = [float(r["prediction_probability_W1"]) for r in saved]
            auc = matrix_auc(scores, labels)
            pr = matrix_pr_auc(scores, labels)
            metric = metric_index[(cohort, model)]
            require(int(metric["n_events"]) == n_events, f"{cohort}/{model}: metric event count mismatch")
            require(int(metric["n_paired_rows"]) == 2*n_events, f"{cohort}/{model}: metric row count mismatch")
            require(int(metric["n_components"]) == n_components, f"{cohort}/{model}: metric component count mismatch")
            require(int(metric["n_features"]) == len(fkeys), f"{cohort}/{model}: metric feature count mismatch")
            require(math.isclose(float(metric["roc_auc_W1_vs_W0"]), auc, rel_tol=0.0, abs_tol=1e-15), f"{cohort}/{model}: ROC AUC does not reproduce")
            require(math.isclose(float(metric["pr_auc_W1"]), pr, rel_tol=0.0, abs_tol=1e-15), f"{cohort}/{model}: PR AUC does not reproduce")
            require(metric["status"] == "OOF_COMPLETED_DESCRIPTIVE_ONLY", f"{cohort}/{model}: wrong metric status")
            require(metric["bootstrap_ci"] == "NOT_RUN" and metric["permutation_p_value"] == "NOT_RUN" and metric["paired_model_test"] == "NOT_RUN" and metric["physical_endpoint_test"] == "NOT_RUN" and metric["tuning"] == "NOT_RUN", f"{cohort}/{model}: an inferential/tuning field is not NOT_RUN")

            # Fold diagnostics must exactly match groups and held-out membership.
            for group, event_ids in cohort_groups.items():
                key = (cohort, model, group)
                expected_fold_keys.add(key)
                fold = fold_index.get(key)
                require(fold is not None, f"{cohort}/{model}: missing fold diagnostic {group}")
                test_events = len(event_ids)
                train_events = n_events - test_events
                require(int(fold["n_train_events"]) == train_events, f"{cohort}/{model}/{group}: train event count mismatch")
                require(int(fold["n_train_rows"]) == 2*train_events, f"{cohort}/{model}/{group}: train row count mismatch")
                require(int(fold["n_test_events"]) == test_events, f"{cohort}/{model}/{group}: test event count mismatch")
                require(int(fold["n_test_rows"]) == 2*test_events, f"{cohort}/{model}/{group}: test row count mismatch")
                require(int(fold["training_components"]) == n_components-1, f"{cohort}/{model}/{group}: training component count mismatch")
            print(
                f"Reproduction PASS: {cohort}/{model}: {2*n_events} probabilities; "
                f"AUC={auc:.6f}; PR-AUC={pr:.6f}; {n_components} folds"
            )

    require(set(fold_index) == expected_fold_keys, "Fold diagnostics contain missing or extra fold rows")
    require(total_reproduced == 1400, f"Expected 1400 reproduced probabilities, got {total_reproduced}")
    print("OOF probabilities exactly reproduced from pinned grouped_loeo:", total_reproduced)
    print("Fold diagnostics and held-out component separation PASS")
    print("Observed ROC AUC / PR AUC independently recomputed: PASS")
    print("All inference and tuning flags remain NOT_RUN: PASS")
    print("\n===== INDEPENDENT VERIFICATION SUMMARY =====")
    print("Runner identity: PASS")
    print("Manifest and file hashes: PASS")
    print("Source fingerprints: PASS")
    print("OOF rows/metrics/folds: PASS 1400 / 8 / 284")
    print("Exact OOF prediction reproduction: PASS")
    print("Metric reproduction: PASS")
    print("ALL GROUPED-LOEO OOF INDEPENDENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"VERIFICATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
