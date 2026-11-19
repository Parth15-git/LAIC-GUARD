#!/usr/bin/env python3
"""Stage 6A.1 grouped-LOEO OOF runner, v001.

Runs only the observed grouped leave-one-dependence-component-out fits and
records out-of-fold probabilities plus descriptive ROC AUC / PR AUC.
No bootstrap, permutation test, sign-flip test, paired-model test, or tuning.
Uses the pinned V004 dependencies for the exact estimator and metrics.
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
STRICT_PAIRS = M4_DIR / "m4_strict_target_pairs.csv"
CONSERVATIVE_PAIRS = M4_DIR / "m4_conservative_target_pairs.csv"
OUT_DIR = REPORTS / "model_evaluation_v001" / "grouped_loeo_oof_v001"

EXPECTED = {
    "m4_manifest": "30810D6540541A6B75E7D5F70E2E95F43FE798647A4E799D63176D2A03B72DC3",
    "m4_qa": "7FB292A279B2AC873B28D8D6EE17C321BB8BE9BF27CF8339A6435D92BC06D20F",
    "stage5b": "06BC22ED858D65CB56A0309185E435463817B0F6E8A455F43F6AA7BEE971476C",
    "stage4b": "91F741C1500FB263F229DDF1D69590B357158CBFB42105F3F992AEA0DA3994B0",
    "matrix_hashes": {
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
    },
}

COHORTS = [
    ("STRICT_TARGETS", STRICT_PAIRS, 88, 36),
    ("CONSERVATIVE_TARGETS", CONSERVATIVE_PAIRS, 87, 35),
]
MODELS = ("M2a", "M2c", "M3", "M4")


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


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def finite_float(row: dict[str, str], field: str, context: str) -> float:
    try:
        value = float(row[field])
    except Exception as exc:
        raise ValueError(f"Invalid numeric value {context} {field}={row.get(field)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"Non-finite numeric value {context} {field}={row.get(field)!r}")
    return value


def matrix_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def assert_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} SHA256 mismatch: expected {expected}; got {actual}")
    print(f"Pinned fingerprint PASS: {label} {actual}")
    return actual


def main() -> int:
    print("===== STAGE 6A.1 GROUPED-LOEO OOF RUNNER v001 =====")
    print("Scope: observed grouped-LOEO OOF predictions and descriptive metrics only")
    print("No permutation, bootstrap, sign-flip, paired-model inference, or tuning")

    # Check source identities before importing the pinned implementation.
    stage5b_path = SCRIPTS / "stage5b_hardened_audit_v002.py"
    stage4b_path = SCRIPTS / "stage4b_scale_full_tier1_cohort_v001.py"
    stage5b_sha = assert_hash(stage5b_path, EXPECTED["stage5b"], "Stage 5B")
    stage4b_sha = assert_hash(stage4b_path, EXPECTED["stage4b"], "Stage 4B")
    assert_hash(M4_MANIFEST, EXPECTED["m4_manifest"], "M4 build manifest")
    assert_hash(M4_QA, EXPECTED["m4_qa"], "M4 build QA")

    if not SCRIPTS.is_dir():
        raise FileNotFoundError(f"Scripts directory not found: {SCRIPTS}")
    sys.path.insert(0, str(SCRIPTS))
    from stage5b_hardened_audit_v002 import grouped_loeo, pr_auc
    from stage4b_scale_full_tier1_cohort_v001 import roc_auc

    m2_rows = read_csv(M2_SCORES)
    m2_ledger_rows = read_csv(M2_LEDGER)
    m3_rows = read_csv(M3_SCORES)
    membership_rows = read_csv(MEMBERSHIP)

    m2a: dict[tuple[str, str], dict[str, str]] = {}
    for row in m2_rows:
        if row.get("feature") != "M2a_raw_GNSS_ZTD":
            continue
        key = (row["event_id"], row["target_window"])
        if key in m2a:
            raise ValueError(f"Duplicate M2a source record: {key}")
        m2a[key] = row

    ledger = {row["event_id"]: row for row in m2_ledger_rows}
    m3 = {row["event_id"]: row for row in m3_rows}
    membership = {
        (row["cohort"], row["event_id"]): row for row in membership_rows
    }

    source_paths = [M2_SCORES, M2_LEDGER, M3_SCORES, MEMBERSHIP,
                    M4_MANIFEST, M4_QA, STRICT_PAIRS, CONSERVATIVE_PAIRS]
    source_hashes = {str(p.relative_to(ROOT)): sha256_file(p) for p in source_paths}

    print("M2 feature-score rows:", len(m2_rows))
    print("M2a event-window records:", len(m2a))
    print("M2 ledger events:", len(ledger))
    print("M3 source events:", len(m3))
    print("Frozen membership rows:", len(membership_rows))

    if len(m2a) != 222 or len(ledger) != 111 or len(m3) != 111:
        raise ValueError("Unexpected source row/event counts")

    # Reconstruct exact matrices used by the prior independent preflight.
    prepared: dict[str, dict[str, Any]] = {}
    all_event_sets: dict[str, set[str]] = {}

    for cohort, pair_path, expected_events, expected_groups in COHORTS:
        rows = read_csv(pair_path)
        if len(rows) != 2 * expected_events:
            raise ValueError(f"{cohort}: expected {2*expected_events} rows; found {len(rows)}")

        matrices: dict[str, list[dict[str, Any]]] = {name: [] for name in MODELS}
        samples: dict[str, list[dict[str, Any]]] = {name: [] for name in MODELS}
        pred_meta: list[dict[str, Any]] = []
        group_members: dict[str, set[str]] = defaultdict(set)
        event_order: list[str] = []
        seen: set[str] = set()
        canonical_pairs: list[tuple[str, str, int, str]] = []

        for i in range(0, len(rows), 2):
            w0, w1 = rows[i:i + 2]
            event_id = w0["event_id"]
            if w1["event_id"] != event_id:
                raise ValueError(f"{cohort}: non-adjacent pair identity at row {i}")
            if event_id in seen:
                raise ValueError(f"{cohort}: duplicate event pair {event_id}")
            seen.add(event_id)
            event_order.append(event_id)
            if (w0["analysis_window"], w1["analysis_window"]) != ("W0", "W1"):
                raise ValueError(f"{cohort}: invalid W0/W1 ordering for {event_id}")
            if (w0["label"], w1["label"]) != ("0", "1"):
                raise ValueError(f"{cohort}: invalid W0/W1 labels for {event_id}")
            if w0["component_id"] != w1["component_id"]:
                raise ValueError(f"{cohort}: event split across components: {event_id}")
            if w0["component_size"] != w1["component_size"]:
                raise ValueError(f"{cohort}: inconsistent component size for {event_id}")
            component = w0["component_id"]
            group_members[component].add(event_id)

            frozen = membership.get((cohort, event_id))
            if frozen is None:
                raise ValueError(f"{cohort}: missing frozen membership for {event_id}")
            if frozen["component_id"] != component:
                raise ValueError(f"{cohort}: component mismatch for {event_id}")
            if int(frozen["component_size"]) != int(w0["component_size"]):
                raise ValueError(f"{cohort}: component-size mismatch for {event_id}")
            if frozen["station_id"].strip().upper() != w0["station_id"].strip().upper():
                raise ValueError(f"{cohort}: station mismatch for {event_id}")

            m3row = m3.get(event_id)
            ledgerrow = ledger.get(event_id)
            if m3row is None or ledgerrow is None:
                raise ValueError(f"{cohort}: missing M3 or M2 ledger row for {event_id}")
            if m3row["origin_time_utc"] != w0["origin_time_utc"]:
                raise ValueError(f"{cohort}: M3 timestamp mismatch for {event_id}")
            if m3row["station_id"].strip().upper() != w0["station_id"].strip().upper():
                raise ValueError(f"{cohort}: M3 station mismatch for {event_id}")
            if ledgerrow["origin_time_utc"] != w0["m2_ledger_origin_time_utc_second_precision"]:
                raise ValueError(f"{cohort}: M2 ledger timestamp lineage mismatch for {event_id}")

            for row, window in ((w0, "W0"), (w1, "W1")):
                a = m2a.get((event_id, window))
                if a is None:
                    raise ValueError(f"{cohort}: missing M2a row for {event_id}/{window}")
                if a["status"] != "PASS":
                    raise ValueError(f"{cohort}: M2a row not PASS for {event_id}/{window}: {a['status']}")
                a_max = finite_float(a, "feature_max_abs_robust_z", f"{event_id}/{window}/M2a")
                a_q95 = finite_float(a, "feature_q95_abs_robust_z", f"{event_id}/{window}/M2a")
                c_max = finite_float(row, "m2c_max_abs_robust_z", f"{event_id}/{window}/M2c")
                c_q95 = finite_float(row, "m2c_q95_abs_robust_z", f"{event_id}/{window}/M2c")
                i_max = finite_float(row, "m3_vtec_max_abs_robust_z", f"{event_id}/{window}/M3")
                i_q95 = finite_float(row, "m3_vtec_q95_abs_robust_z", f"{event_id}/{window}/M3")

                feature_values = {
                    "M2a": [a_max, a_q95],
                    "M2c": [c_max, c_q95],
                    "M3": [i_max, i_q95],
                    "M4": [c_max, c_q95, i_max, i_q95],
                }
                label = int(row["label"])
                for model in MODELS:
                    matrix_row = {
                        "event_id": event_id,
                        "analysis_window": window,
                        "label": label,
                        "component_id": component,
                        "features": feature_values[model],
                    }
                    matrices[model].append(matrix_row)
                    sample = {
                        "event_id": event_id,
                        "label": label,
                        "component_id": component,
                    }
                    for j, value in enumerate(feature_values[model]):
                        sample[f"f{j}"] = value
                    samples[model].append(sample)
                pred_meta.append({
                    "event_id": event_id,
                    "origin_time_utc": row["origin_time_utc"],
                    "station_id": row["station_id"],
                    "region": row["region"],
                    "component_id": component,
                    "component_size": int(row["component_size"]),
                    "analysis_window": window,
                    "label": label,
                })
                canonical_pairs.append((event_id, window, label, component))

        if len(event_order) != expected_events:
            raise ValueError(f"{cohort}: wrong event count")
        if len(group_members) != expected_groups:
            raise ValueError(f"{cohort}: wrong component count")
        for comp, ids in group_members.items():
            declared = {int(r["component_size"]) for r in rows if r["component_id"] == comp}
            if declared != {len(ids)}:
                raise ValueError(f"{cohort}: actual/declaration component-size mismatch {comp}")

        # Matrix hashes are pinned to the independently completed preflight.
        for model in MODELS:
            digest = matrix_digest(matrices[model])
            expected_digest = EXPECTED["matrix_hashes"][cohort][model]
            if digest != expected_digest:
                raise ValueError(
                    f"{cohort}/{model} matrix hash mismatch: expected {expected_digest}; got {digest}"
                )
            print(f"Matrix fingerprint PASS: {cohort}/{model} {digest}")

        prepared[cohort] = {
            "samples": samples,
            "pred_meta": pred_meta,
            "rows": rows,
            "n_events": expected_events,
            "n_components": expected_groups,
            "group_members": group_members,
            "matrices": matrices,
            "event_order": event_order,
        }
        all_event_sets[cohort] = set(event_order)
        print(
            f"Preflight PASS: {cohort}: {expected_events} events, "
            f"{2*expected_events} paired rows, {expected_groups} components"
        )

    if not all_event_sets["CONSERVATIVE_TARGETS"].issubset(all_event_sets["STRICT_TARGETS"]):
        raise ValueError("Conservative cohort is not a subset of strict cohort")
    strict_only = all_event_sets["STRICT_TARGETS"] - all_event_sets["CONSERVATIVE_TARGETS"]
    if strict_only != {"us6000nith"}:
        raise ValueError(f"Unexpected strict-only event set: {sorted(strict_only)}")
    print("Cohort nesting PASS: conservative subset; strict-only event us6000nith")

    # Import and hash checks have passed. Never overwrite an earlier evaluation.
    if OUT_DIR.exists():
        raise FileExistsError(
            f"Output directory already exists; refusing to overwrite: {OUT_DIR}"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=False)

    prediction_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    run_records: list[dict[str, Any]] = []

    for cohort, _, _, _ in COHORTS:
        item = prepared[cohort]
        n_samples = 2 * item["n_events"]
        for model in MODELS:
            samples = item["samples"][model]
            fkeys = [f"f{i}" for i in range(len(samples[0]) - 3)]
            # Explicitly check contiguous f0...fN-1 keys.
            expected_fkeys = [f"f{i}" for i in range(len(item["matrices"][model][0]["features"]))]
            if fkeys != expected_fkeys:
                fkeys = expected_fkeys
            if len(samples) != n_samples:
                raise ValueError(f"{cohort}/{model}: unexpected sample count")

            # Call the original pinned V004 dependency implementation.
            predictions = grouped_loeo(samples, fkeys, "component_id")
            labels = [int(s["label"]) for s in samples]
            if len(predictions) != n_samples:
                raise ValueError(f"{cohort}/{model}: OOF prediction count mismatch")
            if any((not math.isfinite(float(p)) or p < 0.0 or p > 1.0) for p in predictions):
                raise ValueError(f"{cohort}/{model}: invalid OOF probability")

            auc = float(roc_auc(predictions, labels))
            pr = float(pr_auc(predictions, labels))
            if not (math.isfinite(auc) and math.isfinite(pr)):
                raise ValueError(f"{cohort}/{model}: non-finite descriptive metric")

            groups = item["group_members"]
            sorted_groups = sorted(groups)
            if len(sorted_groups) != item["n_components"]:
                raise ValueError(f"{cohort}/{model}: fold/component count mismatch")

            fold_info = {}
            for group in sorted_groups:
                test_events = len(groups[group])
                test_rows = 2 * test_events
                train_events = item["n_events"] - test_events
                train_rows = n_samples - test_rows
                fold_info[group] = {
                    "train_events": train_events,
                    "train_rows": train_rows,
                    "test_events": test_events,
                    "test_rows": test_rows,
                }
                fold_rows.append({
                    "cohort": cohort,
                    "model": model,
                    "held_out_component_id": group,
                    "n_train_events": train_events,
                    "n_train_rows": train_rows,
                    "n_test_events": test_events,
                    "n_test_rows": test_rows,
                    "training_components": item["n_components"] - 1,
                    "estimator": "pinned_stage5b_grouped_loeo_custom_logistic_gradient_descent",
                })

            # grouped_loeo preserves the original sample list order.
            for idx, (sample, meta, prediction) in enumerate(
                zip(samples, item["pred_meta"], predictions), start=1
            ):
                if sample["event_id"] != meta["event_id"] or int(sample["label"]) != meta["label"]:
                    raise ValueError(f"{cohort}/{model}: prediction metadata order drift at row {idx}")
                group = meta["component_id"]
                fi = fold_info[group]
                prediction_rows.append({
                    "cohort": cohort,
                    "model": model,
                    "row_order_within_cohort": idx,
                    "event_id": meta["event_id"],
                    "origin_time_utc": meta["origin_time_utc"],
                    "station_id": meta["station_id"],
                    "region": meta["region"],
                    "component_id": group,
                    "component_size": meta["component_size"],
                    "analysis_window": meta["analysis_window"],
                    "label": meta["label"],
                    "prediction_probability_W1": format(float(prediction), ".17g"),
                    "held_out_component_id": group,
                    "n_train_events": fi["train_events"],
                    "n_train_rows": fi["train_rows"],
                    "n_test_events": fi["test_events"],
                    "n_test_rows": fi["test_rows"],
                })

            metric_rows.append({
                "cohort": cohort,
                "model": model,
                "n_events": item["n_events"],
                "n_paired_rows": n_samples,
                "n_components": item["n_components"],
                "n_features": len(fkeys),
                "roc_auc_W1_vs_W0": format(auc, ".17g"),
                "pr_auc_W1": format(pr, ".17g"),
                "status": "OOF_COMPLETED_DESCRIPTIVE_ONLY",
                "bootstrap_ci": "NOT_RUN",
                "permutation_p_value": "NOT_RUN",
                "paired_model_test": "NOT_RUN",
                "physical_endpoint_test": "NOT_RUN",
                "tuning": "NOT_RUN",
            })
            run_records.append({
                "cohort": cohort,
                "model": model,
                "matrix_sha256": matrix_digest(item["matrices"][model]),
                "n_events": item["n_events"],
                "n_rows": n_samples,
                "n_components": item["n_components"],
                "n_features": len(fkeys),
                "folds_completed": len(sorted_groups),
                "roc_auc_W1_vs_W0": auc,
                "pr_auc_W1": pr,
            })
            print(
                f"OOF PASS: {cohort}/{model}: {n_samples} predictions, "
                f"{len(sorted_groups)} component folds, AUC={auc:.6f}, PR-AUC={pr:.6f}"
            )

    pred_path = OUT_DIR / "grouped_loeo_oof_predictions.csv"
    metrics_path = OUT_DIR / "grouped_loeo_observed_metrics.csv"
    folds_path = OUT_DIR / "grouped_loeo_fold_diagnostics.csv"

    write_csv(pred_path, [
        "cohort", "model", "row_order_within_cohort", "event_id", "origin_time_utc",
        "station_id", "region", "component_id", "component_size", "analysis_window",
        "label", "prediction_probability_W1", "held_out_component_id", "n_train_events",
        "n_train_rows", "n_test_events", "n_test_rows",
    ], prediction_rows)
    write_csv(metrics_path, [
        "cohort", "model", "n_events", "n_paired_rows", "n_components", "n_features",
        "roc_auc_W1_vs_W0", "pr_auc_W1", "status", "bootstrap_ci", "permutation_p_value",
        "paired_model_test", "physical_endpoint_test", "tuning",
    ], metric_rows)
    write_csv(folds_path, [
        "cohort", "model", "held_out_component_id", "n_train_events", "n_train_rows",
        "n_test_events", "n_test_rows", "training_components", "estimator",
    ], fold_rows)

    output_hashes = {
        pred_path.name: sha256_file(pred_path),
        metrics_path.name: sha256_file(metrics_path),
        folds_path.name: sha256_file(folds_path),
    }
    input_hashes = {str(p.relative_to(ROOT)): sha256_file(p) for p in source_paths}
    runner_path = Path(__file__).resolve()
    runner_sha = sha256_file(runner_path)

    manifest = {
        "schema": "LAIC_GUARD_STAGE6A1_GROUPED_LOEO_OOF_MANIFEST_V001",
        "status": "COMPLETED_DESCRIPTIVE_OOF_ONLY",
        "runner": runner_path.name,
        "runner_sha256": runner_sha,
        "source_implementation": {
            "grouped_loeo": {
                "file": "scripts/stage5b_hardened_audit_v002.py",
                "sha256": stage5b_sha,
                "function": "grouped_loeo",
            },
            "pr_auc": {
                "file": "scripts/stage5b_hardened_audit_v002.py",
                "sha256": stage5b_sha,
                "function": "pr_auc",
            },
            "roc_auc": {
                "file": "scripts/stage4b_scale_full_tier1_cohort_v001.py",
                "sha256": stage4b_sha,
                "function": "roc_auc",
            },
        },
        "estimator_specification": {
            "description": "Exact pinned stage5b grouped_loeo implementation; not sklearn LogisticRegression",
            "folding": "Leave one frozen dependence component out; both paired rows for every event in that component held out together",
            "training_only_standardization": "per-feature arithmetic mean and sample SD computed from training rows only",
            "standard_deviation_floor": 1e-6,
            "optimizer": "full-batch gradient descent",
            "iterations": 250,
            "learning_rate": 0.08,
            "weight_penalty": "L2 weight penalty added to each weight gradient; intercept unpenalized",
            "logit_clip": [-20.0, 20.0],
            "initial_weights": 0.0,
            "initial_intercept": 0.0,
        },
        "labels": {"W0": 0, "W1": 1},
        "model_features": {
            "M2a": ["M2a raw GNSS ZTD maximum robust-z", "M2a raw GNSS ZTD q95 robust-z"],
            "M2c": ["M2c calibrated ERA5 residual maximum absolute robust-z", "M2c calibrated ERA5 residual q95 absolute robust-z"],
            "M3": ["M3 quiet-adjusted VTEC maximum absolute robust-z", "M3 quiet-adjusted VTEC q95 absolute robust-z"],
            "M4": ["M2c maximum", "M2c q95", "M3 VTEC maximum", "M3 VTEC q95"],
        },
        "cohorts": {
            "STRICT_TARGETS": {"events": 88, "paired_rows": 176, "components": 36},
            "CONSERVATIVE_TARGETS": {"events": 87, "paired_rows": 174, "components": 35},
            "strict_only_event": "us6000nith",
            "physical_controls": "kept outside primary target classifiers",
        },
        "matrix_hashes": EXPECTED["matrix_hashes"],
        "runs": run_records,
        "metrics_interpretation": {
            "roc_auc": "descriptive observed OOF discrimination of W1 versus W0",
            "pr_auc": "descriptive observed OOF precision-recall area for W1 as positive class",
            "not_earthquake_prediction": True,
            "not_prospective_forecast": True,
        },
        "inference_status": {
            "group_bootstrap_ci": "NOT_RUN",
            "primary_component_label_swap_permutations": "NOT_RUN",
            "physical_endpoint_component_sign_flips": "NOT_RUN",
            "paired_model_component_swaps": "NOT_RUN",
            "holm_adjustments": "NOT_RUN",
            "feature_tuning": "NOT_RUN",
        },
        "input_sha256": input_hashes,
        "output_sha256": output_hashes,
    }

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest_sha = sha256_file(manifest_path)

    print("\n===== GROUPED-LOEO OOF BUILD SUMMARY =====")
    print("Output directory:", OUT_DIR.relative_to(ROOT))
    print("OOF prediction rows:", len(prediction_rows), "(expected 1,400)")
    print("Observed metric rows:", len(metric_rows), "(expected 8)")
    print("Fold diagnostic rows:", len(fold_rows), "(expected 284)")
    print("Outputs:")
    for name, digest in output_hashes.items():
        print(f"  {name}: {digest}")
    print("Manifest SHA256:", manifest_sha)
    print("Model/cohort evaluations:", 8, "(4 models x 2 cohorts)")
    print("Fold-level classifier fits:", len(fold_rows))
    print("Bootstrap/permutation/sign-flip inference: NOT RUN")
    print("Tuning: NOT RUN")
    print("BUILD COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"BUILD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
