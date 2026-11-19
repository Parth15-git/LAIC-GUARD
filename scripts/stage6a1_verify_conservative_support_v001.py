#!/usr/bin/env python3
"""Independent, read-only verification of Stage 6A.1 conservative support outputs.

Reconstructs:
- Four component-bootstrap CIs from saved conservative OOF predictions.
- Three component-level q95 W1-W0 sign-flip null distributions from source features.
- Two component-block model-swap null distributions from saved OOF predictions.
- All effects, extreme counts, Monte Carlo p-values, and null summaries.

No output files are written or modified.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "reports/stage6a1/inference_v002/full_v001"
OOF_DIR = ROOT / "reports/stage6a1/model_evaluation_v001/grouped_loeo_oof_v001"
M4_DIR = ROOT / "reports/stage6a1/m4_joint_features_v002/full_v001"
M2_PATH = ROOT / "reports/stage6a1/strict_tcwv_v001/full_v001/full_feature_scores.csv"
M3_PATH = ROOT / "reports/stage6a1/independent_m3_v001/full_v002/m3_event_feature_scores.csv"

COHORT = "CONSERVATIVE_TARGETS"
MODELS = ("M2a", "M2c", "M3", "M4")
N_BOOT = 1000
N_PERM = 9999
SEED_BOOT = 42
SEED_PHYSICAL = 2026
SEED_PAIRED = 2027

PHYSICAL_ENDPOINTS = (
    "raw_gnss_ztd_q95",
    "calibrated_era5_residual_q95",
    "quiet_adjusted_vtec_q95",
)
COMPARISONS = (
    ("M2c", "M2a", "M2c_vs_M2a"),
    ("M4", "M3", "M4_vs_M3"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def assert_close(a: float, b: float, context: str, tol: float = 1e-14) -> None:
    if not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol):
        raise AssertionError(f"{context}: {a!r} != {b!r} (tol={tol})")


def roc_auc(scores: list[float], labels: list[int]) -> float:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def nearest_rank(values: list[float], p: float) -> float:
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(p * len(ordered))))
    return ordered[rank - 1]


def assert_distribution_summary(stored: dict, values: list[float], context: str) -> None:
    if len(values) != N_PERM:
        raise AssertionError(f"{context}: expected {N_PERM} null values, got {len(values)}")
    checks = {
        "null_median": statistics.median(values),
        "null_q05_nearest_rank": nearest_rank(values, 0.05),
        "null_q95_nearest_rank": nearest_rank(values, 0.95),
        "null_min": min(values),
        "null_max": max(values),
    }
    for key, actual in checks.items():
        assert_close(stored[key], actual, f"{context}/{key}")


def verify_bootstrap(oof_rows: list[dict[str, str]]) -> None:
    path = OUT / "bootstrap_ci_summary__conservative_targets_sensitivity.csv"
    rows = read_csv(path)
    if len(rows) != 4:
        raise AssertionError(f"Bootstrap summary should have 4 rows, got {len(rows)}")

    grouped_oof: dict[str, list[dict]] = defaultdict(list)
    for row in oof_rows:
        if row["cohort"] != COHORT:
            continue
        grouped_oof[row["model"]].append({
            "component_id": row["component_id"],
            "label": int(row["label"]),
            "prediction": float(row["prediction_probability_W1"]),
        })

    seen = set()
    print("\n===== CONSERVATIVE COMPONENT BOOTSTRAP =====")
    for row in rows:
        model = row["model"]
        if model not in MODELS or model in seen:
            raise AssertionError(f"Unexpected/duplicate bootstrap model: {model}")
        seen.add(model)
        samples = grouped_oof[model]
        by_group: dict[str, list[tuple[float, int]]] = defaultdict(list)
        for sample in samples:
            by_group[sample["component_id"]].append((sample["prediction"], sample["label"]))
        groups = sorted(by_group)
        if len(samples) != 174 or len(groups) != 35:
            raise AssertionError(f"{model}: expected 174 rows/35 groups; got {len(samples)}/{len(groups)}")
        for group in groups:
            if {label for _, label in by_group[group]} != {0, 1}:
                raise AssertionError(f"{model}/{group}: group does not contain both labels")

        rng = random.Random(SEED_BOOT)
        aucs: list[float] = []
        for _ in range(N_BOOT):
            selected = [groups[rng.randrange(len(groups))] for _ in groups]
            scores: list[float] = []
            labels: list[int] = []
            for group in selected:
                for pred, label in by_group[group]:
                    scores.append(pred)
                    labels.append(label)
            aucs.append(roc_auc(scores, labels))
        aucs.sort()
        # Exact V002 quantile rule: sorted[index=int(p*n_boot)].
        low = aucs[int(0.025 * len(aucs))]
        high = aucs[min(len(aucs) - 1, int(0.975 * len(aucs)))]

        if int(row["n_bootstrap"]) != N_BOOT or int(row["seed"]) != SEED_BOOT:
            raise AssertionError(f"{model}: bootstrap count/seed mismatch")
        if row["scope"] != "component_bootstrap_conditional_on_fixed_OOF_predictions":
            raise AssertionError(f"{model}: bootstrap scope mismatch")
        if row["quantile_rule"] != "sorted[index=int(p*n_boot)]":
            raise AssertionError(f"{model}: bootstrap quantile rule mismatch")
        saved_auc = float(row["observed_auc"])
        observed_auc = roc_auc(
            [s["prediction"] for s in samples],
            [s["label"] for s in samples],
        )
        assert_close(saved_auc, observed_auc, f"{model}/observed AUC")
        assert_close(row["ci95_low"], low, f"{model}/CI low")
        assert_close(row["ci95_high"], high, f"{model}/CI high")
        print(f"{model}: CI [{low:.6f}, {high:.6f}] | 1,000 resamples | seed 42 PASS")

    if seen != set(MODELS):
        raise AssertionError(f"Bootstrap models incomplete: {seen}")


def build_endpoint_diffs(pair_rows: list[dict[str, str]], m2_rows: list[dict[str, str]], m3_rows: list[dict[str, str]]):
    m2_index = {}
    for row in m2_rows:
        if row["feature"] in (
            "M2a_raw_GNSS_ZTD",
            "M2c_B0_calibrated_residual",
            "M2c_B1_calibrated_residual",
        ):
            m2_index[(row["event_id"], row["feature"], row["target_window"])] = row
    m3_index = {r["event_id"]: r for r in m3_rows}
    by_event: dict[str, dict[str, dict[str, str]]] = {}
    event_order: list[str] = []
    for row in pair_rows:
        eid = row["event_id"]
        if eid not in by_event:
            by_event[eid] = {}
            event_order.append(eid)
        if row["analysis_window"] in by_event[eid]:
            raise AssertionError(f"Duplicate window for {eid}/{row['analysis_window']}")
        by_event[eid][row["analysis_window"]] = row

    specs = {
        "raw_gnss_ztd_q95": ("M2a_raw_GNSS_ZTD",),
        "calibrated_era5_residual_q95": ("M2c_B0_calibrated_residual", "M2c_B1_calibrated_residual"),
        "quiet_adjusted_vtec_q95": (),
    }
    results = {}
    for endpoint in PHYSICAL_ENDPOINTS:
        diffs: list[float] = []
        groups: list[str] = []
        for eid in event_order:
            windows = by_event[eid]
            if set(windows) != {"W0", "W1"}:
                raise AssertionError(f"{endpoint}/{eid}: missing W0/W1")
            if endpoint == "raw_gnss_ztd_q95":
                a = m2_index[(eid, "M2a_raw_GNSS_ZTD", "W0")]
                b = m2_index[(eid, "M2a_raw_GNSS_ZTD", "W1")]
                if a["status"] != "PASS" or b["status"] != "PASS":
                    raise AssertionError(f"M2a q95 source status failure for {eid}")
                v0, v1 = float(a["feature_q95_abs_robust_z"]), float(b["feature_q95_abs_robust_z"])
            elif endpoint == "calibrated_era5_residual_q95":
                a = m2_index[(eid, "M2c_B0_calibrated_residual", "W0")]
                b = m2_index[(eid, "M2c_B1_calibrated_residual", "W1")]
                if a["status"] != "PASS" or b["status"] != "PASS":
                    raise AssertionError(f"M2c q95 source status failure for {eid}")
                v0, v1 = float(a["feature_q95_abs_robust_z"]), float(b["feature_q95_abs_robust_z"])
            else:
                m3 = m3_index[eid]
                if m3.get("m3_feature_status") != "M3_FEATURE_ELIGIBLE":
                    raise AssertionError(f"M3 status not eligible for {eid}: {m3.get('m3_feature_status')}")
                v0, v1 = float(m3["p_vtec_q95"]), float(m3["t_vtec_q95"])
            if not (math.isfinite(v0) and math.isfinite(v1)):
                raise AssertionError(f"Non-finite endpoint value for {eid}")
            diffs.append(v1 - v0)
            groups.append(windows["W0"]["component_id"])
        results[endpoint] = (diffs, groups)
    return results


def verify_physical_endpoints(pair_rows, m2_rows, m3_rows) -> None:
    summary_path = OUT / "physical_endpoint_signflip_summary__conservative_targets_sensitivity.csv"
    summary_rows = read_csv(summary_path)
    if len(summary_rows) != 3:
        raise AssertionError(f"Expected 3 physical endpoint rows, got {len(summary_rows)}")
    source_inputs = build_endpoint_diffs(pair_rows, m2_rows, m3_rows)
    seen = set()
    print("\n===== CONSERVATIVE PHYSICAL Q95 SIGN-FLIP TESTS =====")

    for row in summary_rows:
        endpoint = row["endpoint"]
        if endpoint not in PHYSICAL_ENDPOINTS or endpoint in seen:
            raise AssertionError(f"Unexpected/duplicate endpoint: {endpoint}")
        seen.add(endpoint)
        diffs, group_ids = source_inputs[endpoint]
        by_group: dict[str, list[float]] = defaultdict(list)
        for diff, group in zip(diffs, group_ids):
            by_group[group].append(diff)
        groups = sorted(by_group)
        effects = [sum(by_group[g]) / len(by_group[g]) for g in groups]
        observed = sum(effects) / len(effects)

        rng = random.Random(SEED_PHYSICAL)
        nulls = []
        for _ in range(N_PERM):
            stat = sum(
                (1.0 if rng.random() < 0.5 else -1.0) * effect
                for effect in effects
            ) / len(effects)
            nulls.append(stat)

        extreme = sum(abs(v) >= abs(observed) - 1e-12 for v in nulls)
        p = (extreme + 1) / (N_PERM + 1)
        saved_component_effects = json.loads(row["component_effects"])
        if set(saved_component_effects) != set(groups):
            raise AssertionError(f"{endpoint}: component-effect keys mismatch")
        for group, effect in zip(groups, effects):
            assert_close(saved_component_effects[group], effect, f"{endpoint}/{group} component effect")

        null_path = OUT / "support_null_distributions" / f"{COHORT}__{endpoint}__signflip_null.csv"
        null_rows = read_csv(null_path)
        if len(null_rows) != N_PERM:
            raise AssertionError(f"{endpoint}: null CSV expected {N_PERM} rows")
        saved_nulls = []
        for i, null_row in enumerate(null_rows):
            if int(null_row["permutation_or_sign_pattern_index"]) != i:
                raise AssertionError(f"{endpoint}: null index mismatch at {i}")
            val = float(null_row["null_statistic"])
            assert_close(val, nulls[i], f"{endpoint}/null[{i}]")
            saved_nulls.append(val)

        if int(row["n_events"]) != 87 or int(row["n_components"]) != 35:
            raise AssertionError(f"{endpoint}: cohort size mismatch")
        if row["method"] != "MONTE_CARLO_COMPONENT_SIGN_FLIP":
            raise AssertionError(f"{endpoint}: method mismatch")
        if int(row["n_permutations"]) != N_PERM or int(row["seed"]) != SEED_PHYSICAL:
            raise AssertionError(f"{endpoint}: permutation count/seed mismatch")
        if row["weighting"] != "equal_weight_per_component" or row["component_exchangeability_assumption"] not in ("True", "true"):
            raise AssertionError(f"{endpoint}: weighting/assumption mismatch")
        assert_close(row["effect_mean_component_means"], observed, f"{endpoint}/observed effect")
        if extreme != int(row["extreme_count"]):
            raise AssertionError(f"{endpoint}: extreme-count mismatch {extreme} != {row['extreme_count']}")
        assert_close(row["p_value_two_sided"], p, f"{endpoint}/p")
        assert_distribution_summary(json.loads(row["null_distribution"]), nulls, endpoint)
        print(f"{endpoint}: effect={observed:+.6f}; extreme={extreme}/9999; p={p:.5f}; exact null sequence PASS")

    if seen != set(PHYSICAL_ENDPOINTS):
        raise AssertionError("Physical endpoint family incomplete")


def verify_paired_comparisons(oof_rows: list[dict[str, str]]) -> None:
    summary_path = OUT / "paired_model_comparison_summary__conservative_targets_sensitivity.csv"
    summary_rows = read_csv(summary_path)
    if len(summary_rows) != 2:
        raise AssertionError(f"Expected 2 paired comparison rows, got {len(summary_rows)}")

    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in oof_rows:
        if row["cohort"] == COHORT:
            by_model[row["model"]].append({
                "event_id": row["event_id"],
                "component_id": row["component_id"],
                "label": int(row["label"]),
                "prediction": float(row["prediction_probability_W1"]),
            })

    expected = {name: (a, b) for a, b, name in COMPARISONS}
    seen = set()
    print("\n===== CONSERVATIVE PAIRED MODEL-BLOCK SWAPS =====")

    for row in summary_rows:
        name = row["comparison"]
        if name not in expected or name in seen:
            raise AssertionError(f"Unexpected/duplicate comparison: {name}")
        seen.add(name)
        model_a, model_b = expected[name]
        a_rows, b_rows = by_model[model_a], by_model[model_b]
        if len(a_rows) != 174 or len(b_rows) != 174:
            raise AssertionError(f"{name}: OOF row count mismatch")

        identities_a = [(r["event_id"], r["component_id"], r["label"]) for r in a_rows]
        identities_b = [(r["event_id"], r["component_id"], r["label"]) for r in b_rows]
        if identities_a != identities_b:
            raise AssertionError(f"{name}: paired model rows are not aligned")

        labels = [r["label"] for r in a_rows]
        groups_per_row = [r["component_id"] for r in a_rows]
        events = [r["event_id"] for r in a_rows]
        preds_a = [r["prediction"] for r in a_rows]
        preds_b = [r["prediction"] for r in b_rows]
        groups = sorted(set(groups_per_row))
        if len(groups) != 35:
            raise AssertionError(f"{name}: expected 35 components")
        auc_a = roc_auc(preds_a, labels)
        auc_b = roc_auc(preds_b, labels)
        observed_delta = auc_a - auc_b
        threshold = abs(observed_delta) - 1e-12

        by_group_indices: dict[str, list[int]] = defaultdict(list)
        for i, group in enumerate(groups_per_row):
            by_group_indices[group].append(i)

        rng = random.Random(SEED_PAIRED)
        nulls = []
        for _ in range(N_PERM):
            flipped = {group for group in groups if rng.random() < 0.5}
            pa, pb = list(preds_a), list(preds_b)
            for group in flipped:
                for i in by_group_indices[group]:
                    pa[i], pb[i] = pb[i], pa[i]
            nulls.append(roc_auc(pa, labels) - roc_auc(pb, labels))

        extreme = sum(abs(v) >= threshold for v in nulls)
        p = (extreme + 1) / (N_PERM + 1)

        null_path = OUT / "support_null_distributions" / f"{COHORT}__{name}__model_swap_null.csv"
        null_rows = read_csv(null_path)
        if len(null_rows) != N_PERM:
            raise AssertionError(f"{name}: null CSV expected {N_PERM} rows")
        for i, null_row in enumerate(null_rows):
            if int(null_row["permutation_index"]) != i:
                raise AssertionError(f"{name}: null index mismatch at {i}")
            assert_close(null_row["delta_auc_a_minus_b"], nulls[i], f"{name}/null[{i}]")

        if (row["model_a"], row["model_b"]) != (model_a, model_b):
            raise AssertionError(f"{name}: model identity mismatch")
        if int(row["n_events"]) != 87 or int(row["n_components"]) != 35:
            raise AssertionError(f"{name}: cohort size mismatch")
        if row["method"] != "MONTE_CARLO_COMPONENT_BLOCK_MODEL_SWAP":
            raise AssertionError(f"{name}: method mismatch")
        if int(row["n_permutations"]) != N_PERM or int(row["seed"]) != SEED_PAIRED:
            raise AssertionError(f"{name}: count/seed mismatch")
        if row["interpretation"] != "conditional_on_fixed_OOF_predictions":
            raise AssertionError(f"{name}: interpretation mismatch")
        if row["assumption"] != "model_identity_exchangeable_at_component_level":
            raise AssertionError(f"{name}: exchangeability assumption mismatch")
        assert_close(row["auc_model_a"], auc_a, f"{name}/AUC A")
        assert_close(row["auc_model_b"], auc_b, f"{name}/AUC B")
        assert_close(row["delta_auc_a_minus_b"], observed_delta, f"{name}/delta")
        if extreme != int(row["extreme_count"]):
            raise AssertionError(f"{name}: extreme-count mismatch")
        assert_close(row["p_value_two_sided"], p, f"{name}/p")
        assert_distribution_summary(json.loads(row["null_distribution"]), nulls, name)
        print(f"{name}: delta={observed_delta:+.6f}; extreme={extreme}/9999; p={p:.5f}; exact null sequence PASS")

    if seen != set(expected):
        raise AssertionError("Paired comparison family incomplete")


def main() -> None:
    print("===== STAGE 6A.1 CONSERVATIVE SUPPORT INDEPENDENT VERIFICATION v001 =====")
    print("Mode: read-only; no inference, no file modifications")
    print("Repository:", ROOT)
    if not (ROOT / "scripts/stage6a1_run_inference_v002.py").exists():
        raise RuntimeError("Not running from LAIC-GUARD repository root")

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE":
        raise AssertionError(f"Inference manifest is not COMPLETE: {manifest.get('status')}")
    required_phases = {"primary_auc", "primary_support", "sensitivity_auc", "sensitivity_support"}
    if not required_phases.issubset(set(manifest.get("completed_phases", []))):
        raise AssertionError("Manifest does not declare all four phases complete")
    for model in MODELS:
        if f"{COHORT}/{model}" not in set(manifest.get("completed_auc_tests", [])):
            raise AssertionError(f"Manifest missing conservative AUC completion: {model}")
    print("Manifest status/phases/AUC test records: PASS")

    oof_path = OOF_DIR / "grouped_loeo_oof_predictions.csv"
    oof_rows = read_csv(oof_path)
    if len(oof_rows) != 1400:
        raise AssertionError(f"Expected 1,400 total OOF rows, got {len(oof_rows)}")
    conservative_oof = [r for r in oof_rows if r["cohort"] == COHORT]
    if len(conservative_oof) != 4 * 174:
        raise AssertionError(f"Expected 696 conservative model OOF rows, got {len(conservative_oof)}")

    pairs_path = M4_DIR / "m4_conservative_target_pairs.csv"
    pair_rows = read_csv(pairs_path)
    if len(pair_rows) != 174:
        raise AssertionError(f"Expected 174 conservative pair rows, got {len(pair_rows)}")
    event_ids = {r["event_id"] for r in pair_rows}
    component_ids = {r["component_id"] for r in pair_rows}
    if len(event_ids) != 87 or len(component_ids) != 35:
        raise AssertionError(f"Conservative cohort mismatch: {len(event_ids)} events/{len(component_ids)} components")

    m2_rows = read_csv(M2_PATH)
    m3_rows = read_csv(M3_PATH)

    verify_bootstrap(oof_rows)
    verify_physical_endpoints(pair_rows, m2_rows, m3_rows)
    verify_paired_comparisons(oof_rows)

    print("\n===== CONSERVATIVE SUPPORT VERIFICATION SUMMARY =====")
    for filename in (
        "bootstrap_ci_summary__conservative_targets_sensitivity.csv",
        "physical_endpoint_signflip_summary__conservative_targets_sensitivity.csv",
        "paired_model_comparison_summary__conservative_targets_sensitivity.csv",
    ):
        path = OUT / filename
        print(f"{filename}: PASS SHA256={sha256(path)}")
    print("Bootstrap CIs: 4/4 independently reproduced")
    print("Physical endpoint tests: 3/3 exact null sequences and p-values reproduced")
    print("Paired model swaps: 2/2 exact null sequences and p-values reproduced")
    print("No conservative Holm family applied, as required for sensitivity analyses")
    print("ALL CONSERVATIVE SUPPORT OUTPUTS INDEPENDENTLY VERIFIED")
    print("Read-only: no files modified.")


if __name__ == "__main__":
    main()
