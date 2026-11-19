#!/usr/bin/env python3
"""Independent read-only verifier for Stage 6A.1 M4 feature package v002."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M2_DIR = ROOT / "reports/stage6a1/strict_tcwv_v001/full_v001"
M3_DIR = ROOT / "reports/stage6a1/independent_m3_v001/full_v002"
M4_DIR = ROOT / "reports/stage6a1/m4_joint_features_v002/full_v001"
BUILDER = ROOT / "scripts/stage6a1_build_m4_joint_features_v002.py"

INPUTS = {
    "m2_feature_scores": M2_DIR / "full_feature_scores.csv",
    "m2_event_eligibility_ledger": M2_DIR / "full_event_eligibility_ledger.csv",
    "m3_event_feature_scores": M3_DIR / "m3_event_feature_scores.csv",
    "frozen_component_membership": M2_DIR / "full_dependency_component_membership.csv",
    "v004_event_features_timestamp_crosscheck": ROOT / "reports/stage6a/audit_repaired_v004_regionfix_cachefix_distancefix/analysis/stage6a_v004_event_features.csv",
    "stage1d_frozen_catalogue_timestamp_crosscheck": ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv",
}

OUTPUTS = {
    "m4_event_feature_join.csv": 111,
    "m4_strict_target_pairs.csv": 176,
    "m4_conservative_target_pairs.csv": 174,
    "m4_physical_control_feature_audit.csv": 19,
    "m4_target_component_membership.csv": 175,
    "m4_feature_assembly_qa.json": None,
}
EXPECTED_BUILDER_SHA = "DB8E678570715CBE90D2503E15E891C6F00A3DF42793D8CBD25677A6D0C14592"
EXPECTED_MANIFEST_SHA = "30810D6540541A6B75E7D5F70E2E95F43FE798647A4E799D63176D2A03B72DC3"
EXPECTED_QA_SHA = "7FB292A279B2AC873B28D8D6EE17C321BB8BE9BF27CF8339A6435D92BC06D20F"
EXPECTED_COHORTS = {
    "STRICT_TARGETS": (88, 36),
    "CONSERVATIVE_TARGETS": (87, 35),
    "STRICT_PHYSICAL_CONTROLS": (19, 15),
}
M2_SPECS = {
    ("M2c_B0_calibrated_residual", "B0", "W0"): "p",
    ("M2c_B1_calibrated_residual", "B1", "W1"): "t",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")
        return list(reader), list(reader.fieldnames)


def unique_index(rows: list[dict[str, str]], name: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        event_id = (row.get("event_id") or "").strip()
        if not event_id or event_id in result:
            raise ValueError(f"{name}: blank or duplicate event_id {event_id!r}")
        result[event_id] = row
    return result


def parse_utc(value: str, context: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"Blank timestamp: {context}")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Naive timestamp: {context}={value!r}")
    return dt.astimezone(timezone.utc)


def require_equal(actual: str, expected: str, context: str) -> None:
    if actual != expected:
        raise ValueError(f"Value mismatch at {context}: actual={actual!r}, expected={expected!r}")


def finite(value: str, context: str, allow_blank: bool = False) -> None:
    if value is None or str(value).strip() == "":
        if allow_blank:
            return
        raise ValueError(f"Blank numeric value at {context}")
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"Non-numeric value at {context}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Non-finite value at {context}: {value!r}")


def component_stats(rows: list[dict[str, str]]) -> tuple[int, int, int, dict[str, int]]:
    by_component: dict[str, set[str]] = defaultdict(set)
    declared: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        cid = row["component_id"].strip()
        eid = row["event_id"].strip()
        by_component[cid].add(eid)
        declared[cid].add(int(row["component_size"]))
    for cid, event_ids in by_component.items():
        if declared[cid] != {len(event_ids)}:
            raise ValueError(
                f"Component size mismatch: {cid}; actual={len(event_ids)}; declared={declared[cid]}"
            )
    dist = Counter(len(event_ids) for event_ids in by_component.values())
    return (
        sum(len(v) for v in by_component.values()),
        len(by_component),
        max((len(v) for v in by_component.values()), default=0),
        {str(k): dist[k] for k in sorted(dist)},
    )


def compare_rows(actual_rows, expected_rows, key_fields, fields, label):
    actual_by_key = {}
    for row in actual_rows:
        key = tuple(row.get(k, "") for k in key_fields)
        if key in actual_by_key:
            raise ValueError(f"{label}: duplicate output key {key}")
        actual_by_key[key] = row
    expected_by_key = {}
    for row in expected_rows:
        key = tuple(row.get(k, "") for k in key_fields)
        if key in expected_by_key:
            raise ValueError(f"{label}: duplicate reconstructed key {key}")
        expected_by_key[key] = row
    if set(actual_by_key) != set(expected_by_key):
        raise ValueError(
            f"{label}: key population differs; actual-only={len(set(actual_by_key)-set(expected_by_key))}, "
            f"expected-only={len(set(expected_by_key)-set(actual_by_key))}"
        )
    for key in expected_by_key:
        for field in fields:
            a = actual_by_key[key].get(field, "")
            e = expected_by_key[key].get(field, "")
            if a != e:
                raise ValueError(f"{label}: mismatch key={key}, field={field}, actual={a!r}, expected={e!r}")


def main() -> int:
    print("===== STAGE 6A.1 M4 PACKAGE INDEPENDENT VERIFICATION v001 =====")
    print("Mode: read-only; no fitting, OOF prediction, or inference")
    if not M4_DIR.is_dir():
        raise FileNotFoundError(f"M4 package directory missing: {M4_DIR}")
    if not BUILDER.is_file():
        raise FileNotFoundError(f"M4 builder missing: {BUILDER}")

    builder_sha = sha256(BUILDER)
    if builder_sha != EXPECTED_BUILDER_SHA:
        raise ValueError(f"Builder SHA mismatch: {builder_sha}")
    print("Builder SHA256: PASS", builder_sha)

    manifest_path = M4_DIR / "manifest.json"
    manifest_sha = sha256(manifest_path)
    if manifest_sha != EXPECTED_MANIFEST_SHA:
        raise ValueError(f"Manifest SHA256 differs from the completed build record: {manifest_sha}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "LAIC_GUARD_M4_FEATURE_PACKAGE_MANIFEST_v002":
        raise ValueError("Unexpected M4 manifest schema")
    if manifest.get("build_status") != "PASS":
        raise ValueError("Manifest build_status is not PASS")
    if manifest.get("builder", {}).get("sha256") != builder_sha:
        raise ValueError("Manifest builder SHA does not match installed builder")
    if manifest.get("inference_run") is not False or manifest.get("classifier_fit") is not False:
        raise ValueError("Manifest unexpectedly indicates model fitting/inference")
    print("Manifest schema/status/flags: PASS")

    # Verify all pinned inputs against the manifest.
    if set(manifest.get("inputs", {})) != {str(p.relative_to(ROOT)) for p in INPUTS.values()}:
        raise ValueError("Manifest input path set differs from the six expected source files")
    for name, path in INPUTS.items():
        key = str(path.relative_to(ROOT))
        info = manifest["inputs"][key]
        if sha256(path) != info.get("sha256"):
            raise ValueError(f"Input hash mismatch: {name}")
        if path.stat().st_size != info.get("bytes"):
            raise ValueError(f"Input byte-size mismatch: {name}")
        print(f"Input fingerprint PASS: {name}")

    # Verify package inventory and each output fingerprint/row count.
    expected_files = set(OUTPUTS) | {"manifest.json"}
    actual_files = {p.name for p in M4_DIR.iterdir() if p.is_file()}
    if actual_files != expected_files:
        raise ValueError(
            f"Package file inventory mismatch: missing={sorted(expected_files-actual_files)}, "
            f"unexpected={sorted(actual_files-expected_files)}"
        )
    if set(manifest.get("outputs", {})) != set(OUTPUTS):
        raise ValueError("Manifest output set differs from expected outputs")

    output_data = {}
    for filename, expected_count in OUTPUTS.items():
        path = M4_DIR / filename
        info = manifest["outputs"][filename]
        if sha256(path) != info.get("sha256"):
            raise ValueError(f"Output hash mismatch: {filename}")
        if path.stat().st_size != info.get("bytes"):
            raise ValueError(f"Output byte-size mismatch: {filename}")
        if filename.endswith(".csv"):
            rows, fields = read_csv(path)
            if len(rows) != info.get("data_rows"):
                raise ValueError(f"Manifest row-count mismatch: {filename}")
            if expected_count is not None and len(rows) != expected_count:
                raise ValueError(f"Unexpected row count for {filename}: {len(rows)}")
            output_data[filename] = (rows, fields)
        else:
            if filename == "m4_feature_assembly_qa.json" and sha256(path) != EXPECTED_QA_SHA:
                raise ValueError(f"QA SHA256 differs from the completed build record: {sha256(path)}")
            output_data[filename] = json.loads(path.read_text(encoding="utf-8"))
        print(f"Output fingerprint PASS: {filename}")

    qa = output_data["m4_feature_assembly_qa.json"]
    if qa.get("schema") != "LAIC_GUARD_M4_FEATURE_ASSEMBLY_QA_v002" or qa.get("build_status") != "PASS":
        raise ValueError("Unexpected QA schema/status")
    for flag in (
        "m2c_and_m3_event_ids_match",
        "m3_v004_and_stage1d_full_precision_timestamps_match",
        "m2_ledger_is_authoritative_whole_second_truncation",
        "membership_timestamp_matches_m2_ledger_and_m3_hour",
        "exactly_two_m2c_rows_per_event",
        "frozen_membership_counts_match",
        "frozen_component_ids_reused_without_rebuilding",
        "target_and_control_populations_kept_separate",
        "all_strict_target_features_finite",
        "all_conservative_target_features_finite",
        "each_target_event_has_exactly_one_w0_and_one_w1_row",
        "paired_rows_share_component_id",
        "conservative_population_is_subset_of_strict",
    ):
        if qa.get("checks", {}).get(flag) is not True:
            raise ValueError(f"QA check is not true: {flag}")
    if qa.get("inference_run") is not False or qa.get("classifier_fit") is not False or qa.get("oof_predictions_created") is not False or qa.get("permutation_tests_run") is not False:
        raise ValueError("QA model/inference flags are not all false")
    print("QA structure and all declared PASS flags: PASS")

    # Read the frozen source material and independently reconstruct the joins.
    src = {}
    for name, path in INPUTS.items():
        src[name] = read_csv(path)[0]
    m2_rows = src["m2_feature_scores"]
    ledger_rows = src["m2_event_eligibility_ledger"]
    m3_rows = src["m3_event_feature_scores"]
    membership_rows = src["frozen_component_membership"]
    v004_rows = src["v004_event_features_timestamp_crosscheck"]
    catalogue_rows = src["stage1d_frozen_catalogue_timestamp_crosscheck"]

    if (len(m2_rows), len(ledger_rows), len(m3_rows), len(membership_rows), len(v004_rows), len(catalogue_rows)) != (666, 111, 111, 284, 111, 1186):
        raise ValueError("Source row counts differ from the validated build inputs")
    m3 = unique_index(m3_rows, "M3")
    ledger = unique_index(ledger_rows, "M2 ledger")
    v004 = unique_index(v004_rows, "V004 features")
    catalogue = unique_index(catalogue_rows, "Stage 1D catalogue")
    if not (set(m3) == set(ledger) == set(v004)) or not set(m3).issubset(catalogue):
        raise ValueError("Source event ID populations do not align")

    timestamp_delta = {}
    for eid, mr in m3.items():
        t_m3 = parse_utc(mr["origin_time_utc"], f"M3 {eid}")
        t_v004 = parse_utc(v004[eid]["origin_time_utc"], f"V004 {eid}")
        t_cat = parse_utc(catalogue[eid]["origin_time_utc"], f"Stage1D {eid}")
        t_ledger = parse_utc(ledger[eid]["origin_time_utc"], f"M2 ledger {eid}")
        if not (t_m3 == t_v004 == t_cat):
            raise ValueError(f"Full precision timestamp disagreement for {eid}")
        if t_ledger != t_m3.replace(microsecond=0):
            raise ValueError(f"Ledger is not whole-second truncation for {eid}")
        if ledger[eid]["station_id"].strip().upper() != mr["station_id"].strip().upper() or v004[eid]["station_id"].strip().upper() != mr["station_id"].strip().upper():
            raise ValueError(f"Station identity mismatch for {eid}")
        event_hour = parse_utc(mr["event_hour_utc"], f"event_hour {eid}")
        if event_hour != t_m3.replace(minute=0, second=0, microsecond=0):
            raise ValueError(f"event_hour_utc mismatch for {eid}")
        timestamp_delta[eid] = (t_m3 - t_ledger).total_seconds()
    print("Independent source timestamp/station lineage: PASS 111/111")

    m2c = defaultdict(dict)
    for row in m2_rows:
        feature = row["feature"].strip()
        if feature not in {"M2c_B0_calibrated_residual", "M2c_B1_calibrated_residual"}:
            continue
        spec = (feature, row["baseline"].strip(), row["target_window"].strip())
        if spec not in M2_SPECS:
            raise ValueError(f"Unexpected M2c mapping: {spec}")
        side = M2_SPECS[spec]
        eid = row["event_id"].strip()
        if side in m2c[eid]:
            raise ValueError(f"Duplicate M2c feature row for {eid} / {side}")
        m2c[eid][side] = row
    if set(m2c) != set(m3) or any(set(sides) != {"p", "t"} for sides in m2c.values()):
        raise ValueError("M2c rows are not exactly two per M3 event")

    joined_rows, joined_fields = output_data["m4_event_feature_join.csv"]
    joined = unique_index(joined_rows, "M4 event join")
    if set(joined) != set(m3):
        raise ValueError("M4 event join ID set differs from M3")
    m3_meta_fields = [
        "origin_time_utc", "event_hour_utc", "latitude_deg", "longitude_deg",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "m3_feature_status", "p_vtec_score_n", "t_vtec_score_n",
        "p_vtec_baseline_n", "t_vtec_baseline_n",
    ]
    for eid, mr in m3.items():
        out = joined[eid]
        for f in m3_meta_fields:
            require_equal(out.get(f, ""), mr.get(f, ""), f"event_join {eid}.{f}")
        require_equal(out["m2_ledger_origin_time_utc_second_precision"], ledger[eid]["origin_time_utc"], f"event_join {eid}.ledger_time")
        require_equal(out["v004_origin_time_utc_full_precision"], v004[eid]["origin_time_utc"], f"event_join {eid}.v004_time")
        require_equal(out["stage1d_origin_time_utc_full_precision"], catalogue[eid]["origin_time_utc"], f"event_join {eid}.catalogue_time")
        require_equal(out["m3_minus_m2_ledger_time_seconds"], f"{timestamp_delta[eid]:.6f}", f"event_join {eid}.timestamp_delta")
        for side, prefix in (("p", "m2c_p"), ("t", "m2c_t")):
            source_row = m2c[eid][side]
            for out_field, source_field in (
                (f"{prefix}_status", "status"),
                (f"{prefix}_failure_reason", "failure_reason"),
                (f"{prefix}_max_abs_robust_z", "feature_max_abs_robust_z"),
                (f"{prefix}_q95_abs_robust_z", "feature_q95_abs_robust_z"),
            ):
                expected = source_row.get(source_field, "")
                actual = out.get(out_field, "")
                # Builder intentionally normalizes non-finite or empty numeric values to blank.
                if "max_abs" in out_field or "q95_abs" in out_field:
                    if expected.strip().lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
                        expected = ""
                require_equal(actual, expected, f"event_join {eid}.{out_field}")
        for out_field, m3_field in (
            ("m3_p_max_abs_robust_z", "p_vtec_max"),
            ("m3_p_q95_abs_robust_z", "p_vtec_q95"),
            ("m3_t_max_abs_robust_z", "t_vtec_max"),
            ("m3_t_q95_abs_robust_z", "t_vtec_q95"),
        ):
            require_equal(out[out_field], mr[m3_field], f"event_join {eid}.{out_field}")
    print("Independent M2c/M3 event-join reconstruction: PASS 111/111")

    # Validate exact source membership subsets and cohort component structures.
    allowed = {"STRICT_TARGETS", "CONSERVATIVE_TARGETS", "STRICT_PHYSICAL_CONTROLS"}
    member_by_cohort = defaultdict(list)
    seen = set()
    for row in membership_rows:
        cohort = row["cohort"].strip()
        if cohort not in allowed:
            continue
        eid = row["event_id"].strip()
        key = (cohort, eid)
        if key in seen:
            raise ValueError(f"Duplicate frozen membership row: {key}")
        seen.add(key)
        member_by_cohort[cohort].append(row)
        if eid not in joined:
            raise ValueError(f"Membership event absent from M4 join: {eid}")
        if row["station_id"].strip().upper() != m3[eid]["station_id"].strip().upper():
            raise ValueError(f"Membership station mismatch: {cohort}/{eid}")
        mt = parse_utc(row["origin_time_utc"], f"membership {cohort}/{eid}")
        if mt != parse_utc(ledger[eid]["origin_time_utc"], f"ledger {eid}"):
            raise ValueError(f"Membership/ledger full-second mismatch: {cohort}/{eid}")
        if mt != parse_utc(m3[eid]["origin_time_utc"], f"M3 {eid}").replace(microsecond=0):
            raise ValueError(f"Membership/M3 truncation mismatch: {cohort}/{eid}")
        if mt.replace(minute=0, second=0, microsecond=0) != parse_utc(m3[eid]["event_hour_utc"], f"M3 hour {eid}"):
            raise ValueError(f"Membership and M3 floored hour mismatch: {cohort}/{eid}")

    cohort_ids = {c: {r["event_id"].strip() for r in member_by_cohort[c]} for c in allowed}
    for cohort, (n_events, n_components) in EXPECTED_COHORTS.items():
        stats = component_stats(member_by_cohort[cohort])
        if stats[0] != n_events or stats[1] != n_components:
            raise ValueError(f"Frozen cohort component structure mismatch: {cohort} {stats}")
        print(f"Frozen cohort PASS: {cohort}: events={stats[0]}, components={stats[1]}, largest={stats[2]}")
    if not cohort_ids["CONSERVATIVE_TARGETS"].issubset(cohort_ids["STRICT_TARGETS"]):
        raise ValueError("Conservative target cohort is not a subset of strict")
    if cohort_ids["STRICT_TARGETS"] & cohort_ids["STRICT_PHYSICAL_CONTROLS"]:
        raise ValueError("Target/control overlap detected")

    # Reconstruct expected W0/W1 paired rows exactly from source event and membership tables.
    pair_fields = [
        "cohort", "event_id", "origin_time_utc",
        "m2_ledger_origin_time_utc_second_precision",
        "membership_origin_time_utc_second_precision",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "component_id", "component_size", "label", "analysis_window",
        "m2c_max_abs_robust_z", "m2c_q95_abs_robust_z",
        "m3_vtec_max_abs_robust_z", "m3_vtec_q95_abs_robust_z",
    ]

    def reconstruct_pairs(cohort):
        result = []
        ordered = sorted(member_by_cohort[cohort], key=lambda r: (r["origin_time_utc"], r["event_id"]))
        for member in ordered:
            eid = member["event_id"].strip()
            event = joined[eid]
            common = {
                "cohort": cohort,
                "event_id": eid,
                "origin_time_utc": event["origin_time_utc"],
                "m2_ledger_origin_time_utc_second_precision": ledger[eid]["origin_time_utc"],
                "membership_origin_time_utc_second_precision": member["origin_time_utc"],
                "station_id": event["station_id"],
                "region": event["region"],
                "role": event["role"],
                "source_class": event["source_class"],
                "magnitude": event["magnitude"],
                "depth_km": event["depth_km"],
                "component_id": member["component_id"],
                "component_size": member["component_size"],
            }
            for label, window, side in (("0", "W0", "p"), ("1", "W1", "t")):
                pfx = "m2c_p" if side == "p" else "m2c_t"
                m3p = "m3_p" if side == "p" else "m3_t"
                result.append({
                    **common,
                    "label": label,
                    "analysis_window": window,
                    "m2c_max_abs_robust_z": event[f"{pfx}_max_abs_robust_z"],
                    "m2c_q95_abs_robust_z": event[f"{pfx}_q95_abs_robust_z"],
                    "m3_vtec_max_abs_robust_z": event[f"{m3p}_max_abs_robust_z"],
                    "m3_vtec_q95_abs_robust_z": event[f"{m3p}_q95_abs_robust_z"],
                })
        return result

    strict_expected = reconstruct_pairs("STRICT_TARGETS")
    conservative_expected = reconstruct_pairs("CONSERVATIVE_TARGETS")
    strict_actual = output_data["m4_strict_target_pairs.csv"][0]
    conservative_actual = output_data["m4_conservative_target_pairs.csv"][0]
    compare_rows(strict_actual, strict_expected, ["event_id", "label"], pair_fields, "strict paired dataset")
    compare_rows(conservative_actual, conservative_expected, ["event_id", "label"], pair_fields, "conservative paired dataset")
    if [(r["event_id"], r["label"]) for r in strict_actual] != [(r["event_id"], r["label"]) for r in strict_expected]:
        raise ValueError("Strict target pair row order differs from deterministic frozen-membership order")
    if [(r["event_id"], r["label"]) for r in conservative_actual] != [(r["event_id"], r["label"]) for r in conservative_expected]:
        raise ValueError("Conservative target pair row order differs from deterministic frozen-membership order")
    print("Strict W0/W1 pairs independently reconstructed: PASS 176/176 rows")
    print("Conservative W0/W1 pairs independently reconstructed: PASS 174/174 rows")

    # Pair cardinality, order, labels and component integrity.
    for name, rows, expected_n in (
        ("STRICT_TARGETS", strict_actual, 88),
        ("CONSERVATIVE_TARGETS", conservative_actual, 87),
    ):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["event_id"]].append(row)
            for f in ("m2c_max_abs_robust_z", "m2c_q95_abs_robust_z", "m3_vtec_max_abs_robust_z", "m3_vtec_q95_abs_robust_z"):
                finite(row[f], f"{name}/{row['event_id']}/{row['analysis_window']}/{f}")
        if len(grouped) != expected_n:
            raise ValueError(f"{name}: wrong number of unique event pairs")
        for eid, pair in grouped.items():
            if len(pair) != 2 or {(r["label"], r["analysis_window"]) for r in pair} != {("0", "W0"), ("1", "W1")}:
                raise ValueError(f"{name}: incomplete or invalid W0/W1 pair for {eid}")
            if len({r["component_id"] for r in pair}) != 1:
                raise ValueError(f"{name}: paired rows split across components for {eid}")

    # Control audit must match the frozen 19-event control population and must stay separate.
    control_actual = output_data["m4_physical_control_feature_audit.csv"][0]
    control_by_id = unique_index(control_actual, "M4 control audit")
    if set(control_by_id) != cohort_ids["STRICT_PHYSICAL_CONTROLS"]:
        raise ValueError("M4 control audit IDs differ from frozen physical-control cohort")
    control_expected = []
    control_members = sorted(
        member_by_cohort["STRICT_PHYSICAL_CONTROLS"],
        key=lambda r: (r["origin_time_utc"], r["event_id"]),
    )
    control_fields = [
        "cohort", "event_id", "origin_time_utc",
        "m2_ledger_origin_time_utc_second_precision",
        "membership_origin_time_utc_second_precision",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "component_id", "component_size", "m3_feature_status",
        "m2c_p_status", "m2c_p_failure_reason", "m2c_p_max_abs_robust_z",
        "m2c_p_q95_abs_robust_z", "m2c_t_status", "m2c_t_failure_reason",
        "m2c_t_max_abs_robust_z", "m2c_t_q95_abs_robust_z",
        "m3_p_max_abs_robust_z", "m3_p_q95_abs_robust_z",
        "m3_t_max_abs_robust_z", "m3_t_q95_abs_robust_z",
    ]
    for member in control_members:
        eid = member["event_id"].strip()
        event = joined[eid]
        expected_row = {
            "cohort": "STRICT_PHYSICAL_CONTROLS",
            "event_id": eid,
            "origin_time_utc": event["origin_time_utc"],
            "m2_ledger_origin_time_utc_second_precision": ledger[eid]["origin_time_utc"],
            "membership_origin_time_utc_second_precision": member["origin_time_utc"],
            "station_id": event["station_id"],
            "region": event["region"],
            "role": event["role"],
            "source_class": event["source_class"],
            "magnitude": event["magnitude"],
            "depth_km": event["depth_km"],
            "component_id": member["component_id"],
            "component_size": member["component_size"],
            **{field: event.get(field, "") for field in control_fields if field in event},
        }
        control_expected.append(expected_row)
    compare_rows(control_actual, control_expected, ["event_id"], control_fields, "physical-control feature audit")
    if set(control_by_id) & cohort_ids["STRICT_TARGETS"]:
        raise ValueError("Control audit rows overlap primary target classifier")
    print("Separate physical-control audit: PASS 19 events / 15 components")

    # Verify membership crosswalk contains strict+conservative memberships only.
    cross_actual = output_data["m4_target_component_membership.csv"][0]
    expected_cross = []
    for cohort in ("STRICT_TARGETS", "CONSERVATIVE_TARGETS"):
        for member in member_by_cohort[cohort]:
            eid = member["event_id"].strip()
            expected_cross.append({
                "cohort": cohort,
                "event_id": eid,
                "station_id": member["station_id"],
                "membership_origin_time_utc_second_precision": member["origin_time_utc"],
                "feature_origin_time_utc_full_precision": m3[eid]["origin_time_utc"],
                "event_hour_utc": m3[eid]["event_hour_utc"],
                "component_id": member["component_id"],
                "component_size": member["component_size"],
            })
    cross_fields = [
        "cohort", "event_id", "station_id", "membership_origin_time_utc_second_precision",
        "feature_origin_time_utc_full_precision", "event_hour_utc", "component_id", "component_size",
    ]
    compare_rows(cross_actual, expected_cross, ["cohort", "event_id"], cross_fields, "target component crosswalk")
    print("Target component timestamp crosswalk: PASS 175 rows")

    # Confirm QA summaries are numerically consistent with independently reconstructed cohorts.
    populations = qa.get("populations", {})
    expected_population_values = {
        "all_joined_events": 111,
        "strict_pair_rows": 176,
        "conservative_pair_rows": 174,
        "control_audit_rows": 19,
    }
    for field, expected in expected_population_values.items():
        if populations.get(field) != expected:
            raise ValueError(f"QA population mismatch: {field}={populations.get(field)!r}")
    for cohort, (n, groups) in EXPECTED_COHORTS.items():
        key = {
            "STRICT_TARGETS": "strict_targets",
            "CONSERVATIVE_TARGETS": "conservative_targets",
            "STRICT_PHYSICAL_CONTROLS": "strict_physical_controls_separate_audit_only",
        }[cohort]
        summary = populations.get(key, {})
        stats = component_stats(member_by_cohort[cohort])
        if summary.get("event_count") != n or summary.get("component_count") != groups or summary.get("largest_component") != stats[2]:
            raise ValueError(f"QA summary mismatch for {cohort}")

    print("\n===== INDEPENDENT VERIFICATION SUMMARY =====")
    print("M4 package files: PASS", len(expected_files), "(5 CSV + QA JSON + manifest)")
    print("Completed-build manifest SHA: PASS", manifest_sha)
    print("Completed-build QA SHA: PASS", EXPECTED_QA_SHA)
    print("Six input fingerprints: PASS")
    print("Six output fingerprints: PASS")
    print("M2c/M3 source join: PASS 111 events")
    print("Strict target pairs: PASS 88 events / 176 rows / 36 components")
    print("Conservative target pairs: PASS 87 events / 174 rows / 35 components")
    print("Separate physical controls: PASS 19 events / 15 components")
    print("Target/control separation: PASS")
    print("Classifier fit: NOT RUN")
    print("Inference: NOT RUN")
    print("ALL INDEPENDENT M4 PACKAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"INDEPENDENT VERIFICATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
