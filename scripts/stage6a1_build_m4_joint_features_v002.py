#!/usr/bin/env python3
"""Build the Stage 6A.1 M4 joint-feature package from frozen M2c/M3 outputs.

This is a feature-assembly step only. It does not fit models, calculate OOF
predictions, run permutations, or perform statistical inference.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
M2_DIR = ROOT / "reports/stage6a1/strict_tcwv_v001/full_v001"
M3_DIR = ROOT / "reports/stage6a1/independent_m3_v001/full_v002"
MEMBERSHIP_PATH = M2_DIR / "full_dependency_component_membership.csv"
M2_SCORES_PATH = M2_DIR / "full_feature_scores.csv"
M2_LEDGER_PATH = M2_DIR / "full_event_eligibility_ledger.csv"
M3_SCORES_PATH = M3_DIR / "m3_event_feature_scores.csv"
V004_FEATURES_PATH = ROOT / "reports/stage6a/audit_repaired_v004_regionfix_cachefix_distancefix/analysis/stage6a_v004_event_features.csv"
STAGE1D_CATALOGUE_PATH = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
OUT_DIR = ROOT / "reports/stage6a1/m4_joint_features_v002/full_v001"
TEMP_DIR = OUT_DIR.with_name(OUT_DIR.name + ".building")

M2_SPECS = {
    ("M2c_B0_calibrated_residual", "B0", "W0"): ("p", "W0"),
    ("M2c_B1_calibrated_residual", "B1", "W1"): ("t", "W1"),
}
M3_VALUE_FIELDS = {
    "p": ("p_vtec_max", "p_vtec_q95"),
    "t": ("t_vtec_max", "t_vtec_q95"),
}
EXPECTED = {
    "all_events": 111,
    "strict_targets": 88,
    "strict_components": 36,
    "conservative_targets": 87,
    "conservative_components": 35,
    "strict_controls": 19,
    "control_components": 15,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = list(reader)
        return rows, list(reader.fieldnames)


def require_columns(path: Path, fields: list[str], required: set[str]) -> None:
    missing = sorted(required - set(fields))
    if missing:
        raise ValueError(f"{path.name} missing required columns: {missing}")


def parse_utc(value: Any, context: str) -> datetime:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"Blank UTC timestamp: {context}")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid UTC timestamp {value!r}: {context}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp is not accepted: {value!r} ({context})")
    return parsed.astimezone(timezone.utc)


def finite_text(value: Any, context: str, allow_blank: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        if allow_blank:
            return ""
        raise ValueError(f"Blank numeric value: {context}")
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        if allow_blank and text.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            return ""
        raise ValueError(f"Non-numeric value {text!r}: {context}") from exc
    if not math.isfinite(number):
        if allow_blank:
            return ""
        raise ValueError(f"Non-finite numeric value {text!r}: {context}")
    return text


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def component_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    sizes: dict[str, set[str]] = defaultdict(set)
    declared_sizes: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        cid = row["component_id"]
        sizes[cid].add(row["event_id"])
        declared_sizes[cid].add(int(row["component_size"]))
    for cid, event_ids in sizes.items():
        if declared_sizes[cid] != {len(event_ids)}:
            raise ValueError(
                f"Component size declaration mismatch for {cid}: "
                f"actual={len(event_ids)}, declared={sorted(declared_sizes[cid])}"
            )
    distribution = Counter(len(event_ids) for event_ids in sizes.values())
    return {
        "event_count": sum(len(v) for v in sizes.values()),
        "component_count": len(sizes),
        "largest_component": max((len(v) for v in sizes.values()), default=0),
        "component_size_distribution": {
            str(k): distribution[k] for k in sorted(distribution)
        },
    }


def main() -> int:
    print("===== STAGE 6A.1 M4 JOINT FEATURE BUILD v002 =====")
    print("Purpose: feature assembly and cohort/label validation only")
    print("No classifier fitting or inferential statistics will be run.")

    # Refuse to overwrite or mix with a partial previous build.
    if OUT_DIR.exists():
        raise FileExistsError(f"Output already exists; refusing overwrite: {OUT_DIR}")
    if TEMP_DIR.exists():
        raise FileExistsError(
            f"Temporary build directory already exists; inspect it before retrying: {TEMP_DIR}"
        )

    m2_rows, m2_fields = read_csv(M2_SCORES_PATH)
    ledger_rows, ledger_fields = read_csv(M2_LEDGER_PATH)
    m3_rows, m3_fields = read_csv(M3_SCORES_PATH)
    membership_rows, membership_fields = read_csv(MEMBERSHIP_PATH)
    v004_rows, v004_fields = read_csv(V004_FEATURES_PATH)
    catalogue_rows, catalogue_fields = read_csv(STAGE1D_CATALOGUE_PATH)

    require_columns(
        M2_SCORES_PATH, m2_fields,
        {
            "event_id", "feature", "baseline", "target_window",
            "feature_max_abs_robust_z", "feature_q95_abs_robust_z",
            "status", "failure_reason",
        },
    )
    require_columns(
        M2_LEDGER_PATH, ledger_fields,
        {"event_id", "station_id", "origin_time_utc"},
    )
    require_columns(
        M3_SCORES_PATH, m3_fields,
        {
            "event_id", "origin_time_utc", "event_hour_utc", "latitude_deg",
            "longitude_deg", "station_id", "region", "role", "source_class",
            "magnitude", "depth_km", "m3_feature_status",
            "p_vtec_score_n", "t_vtec_score_n", "p_vtec_baseline_n",
            "t_vtec_baseline_n", "p_vtec_max", "p_vtec_q95",
            "t_vtec_max", "t_vtec_q95", "p_vpos_max", "p_vpos_q95",
            "t_vpos_max", "t_vpos_q95",
        },
    )
    require_columns(
        MEMBERSHIP_PATH, membership_fields,
        {"cohort", "event_id", "station_id", "origin_time_utc", "component_id", "component_size"},
    )
    require_columns(
        V004_FEATURES_PATH, v004_fields,
        {"event_id", "origin_time_utc", "station_id"},
    )
    require_columns(
        STAGE1D_CATALOGUE_PATH, catalogue_fields,
        {"event_id", "origin_time_utc"},
    )

    print(f"M2 feature-score rows: {len(m2_rows)}")
    print(f"M2 eligibility-ledger rows: {len(ledger_rows)}")
    print(f"M3 event-score rows: {len(m3_rows)}")
    print(f"Frozen membership rows: {len(membership_rows)}")
    print(f"V004 source event rows: {len(v004_rows)}")
    print(f"Stage 1D catalogue rows: {len(catalogue_rows)}")
    if len(m2_rows) != 666:
        raise ValueError(f"Expected 666 M2 feature-score rows, got {len(m2_rows)}")
    if len(m3_rows) != EXPECTED["all_events"]:
        raise ValueError(f"Expected 111 M3 event-score rows, got {len(m3_rows)}")

    # M3 is the one-row-per-event metadata and event-level feature source.
    m3_by_id: dict[str, dict[str, str]] = {}
    for row in m3_rows:
        event_id = row["event_id"].strip()
        if not event_id or event_id in m3_by_id:
            raise ValueError(f"Blank or duplicate M3 event_id: {event_id!r}")
        m3_by_id[event_id] = row
        if not row.get("m3_feature_status", "").strip():
            raise ValueError(f"Blank M3 feature status for {event_id}")
        for field in M3_VALUE_FIELDS["p"] + M3_VALUE_FIELDS["t"]:
            finite_text(row.get(field), f"M3 {event_id} {field}")

    if len(m3_by_id) != EXPECTED["all_events"]:
        raise ValueError(
            f"Expected {EXPECTED['all_events']} unique M3 events, got {len(m3_by_id)}"
        )

    def unique_event_index(rows: list[dict[str, str]], source_name: str) -> dict[str, dict[str, str]]:
        indexed: dict[str, dict[str, str]] = {}
        for source_row in rows:
            event_id = (source_row.get("event_id") or "").strip()
            if not event_id or event_id in indexed:
                raise ValueError(f"Blank or duplicate event_id in {source_name}: {event_id!r}")
            indexed[event_id] = source_row
        return indexed

    ledger_by_id = unique_event_index(ledger_rows, "M2 eligibility ledger")
    v004_by_id = unique_event_index(v004_rows, "V004 event features")
    catalogue_by_id = unique_event_index(catalogue_rows, "Stage 1D frozen catalogue")

    if set(ledger_by_id) != set(m3_by_id):
        raise ValueError("M2 ledger and M3 event ID populations differ")
    if set(v004_by_id) != set(m3_by_id):
        raise ValueError("V004 feature table and M3 event ID populations differ")
    if not set(m3_by_id).issubset(catalogue_by_id):
        raise ValueError("One or more M3 event IDs are absent from Stage 1D frozen catalogue")

    # Timestamp lineage: M3, V004 and Stage 1D retain the authoritative
    # millisecond-capable origin instant. The M2 eligibility ledger and its
    # dependency-membership export store the same instant at whole-second
    # precision. The frozen component algorithm floors all origins to UTC hour,
    # so the subsecond serialization loss cannot change its interval endpoints.
    m3_utc_by_id: dict[str, datetime] = {}
    timestamp_deltas: list[float] = []
    for event_id, m3_row in m3_by_id.items():
        m3_dt = parse_utc(m3_row["origin_time_utc"], f"M3 {event_id}")
        v004_dt = parse_utc(v004_by_id[event_id]["origin_time_utc"], f"V004 {event_id}")
        catalogue_dt = parse_utc(catalogue_by_id[event_id]["origin_time_utc"], f"Stage 1D {event_id}")
        ledger_dt = parse_utc(ledger_by_id[event_id]["origin_time_utc"], f"M2 ledger {event_id}")
        if m3_dt != v004_dt:
            raise ValueError(f"M3/V004 full-precision origin-time mismatch for {event_id}")
        if m3_dt != catalogue_dt:
            raise ValueError(f"M3/Stage 1D full-precision origin-time mismatch for {event_id}")
        if ledger_dt != m3_dt.replace(microsecond=0):
            raise ValueError(
                f"M2 ledger is not the whole-second truncation of authoritative origin time for {event_id}: "
                f"M2={ledger_dt.isoformat()} M3={m3_dt.isoformat()}"
            )
        if ledger_by_id[event_id]["station_id"].strip().upper() != m3_row["station_id"].strip().upper():
            raise ValueError(f"M2 ledger/M3 station mismatch for {event_id}")
        if v004_by_id[event_id]["station_id"].strip().upper() != m3_row["station_id"].strip().upper():
            raise ValueError(f"V004/M3 station mismatch for {event_id}")
        event_hour = parse_utc(m3_row["event_hour_utc"], f"M3 event hour {event_id}")
        if event_hour != m3_dt.replace(minute=0, second=0, microsecond=0):
            raise ValueError(f"M3 event_hour_utc is inconsistent with full origin time for {event_id}")
        delta = (m3_dt - ledger_dt).total_seconds()
        if not (0.0 <= delta < 1.0):
            raise ValueError(f"Unexpected M3-minus-M2 timestamp precision delta for {event_id}: {delta}")
        timestamp_deltas.append(delta)
        m3_utc_by_id[event_id] = m3_dt

    if len(timestamp_deltas) != EXPECTED["all_events"]:
        raise ValueError("Timestamp lineage did not validate all 111 M3 events")
    print("Timestamp lineage: M3=V004=Stage 1D exact for 111/111 events")
    print("Timestamp lineage: M2 ledger=whole-second truncation for 111/111 events")
    print(
        "M3 minus M2 truncation delta (seconds):",
        f"min={min(timestamp_deltas):.6f}",
        f"max={max(timestamp_deltas):.6f}",
        f"nonzero={sum(delta > 0 for delta in timestamp_deltas)}",
    )

    # Keep exactly the two frozen M2c rows per event, in their declared windows.
    m2c_by_id: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in m2_rows:
        if row["feature"].strip() not in {
            "M2c_B0_calibrated_residual", "M2c_B1_calibrated_residual"
        }:
            continue
        spec = (
            row["feature"].strip(),
            row["baseline"].strip(),
            row["target_window"].strip(),
        )
        if spec not in M2_SPECS:
            raise ValueError(f"Unexpected M2c feature/window mapping: {spec}")
        event_id = row["event_id"].strip()
        side, expected_window = M2_SPECS[spec]
        if row["target_window"].strip() != expected_window:
            raise ValueError(f"M2c window mapping inconsistency for {event_id}: {spec}")
        if side in m2c_by_id[event_id]:
            raise ValueError(f"Duplicate M2c {side} row for {event_id}")
        m2c_by_id[event_id][side] = row

    if set(m2c_by_id) != set(m3_by_id):
        raise ValueError(
            "M2c/M3 event populations differ; "
            f"M2c-only={sorted(set(m2c_by_id)-set(m3_by_id))[:10]}, "
            f"M3-only={sorted(set(m3_by_id)-set(m2c_by_id))[:10]}"
        )
    if sum(len(sides) for sides in m2c_by_id.values()) != 222:
        raise ValueError("Expected exactly 222 M2c feature rows (two per event)")
    for event_id, sides in m2c_by_id.items():
        if set(sides) != {"p", "t"}:
            raise ValueError(f"Expected exactly one M2c W0 and W1 row for {event_id}")

    # Build an event-level joined feature audit. Excluded M2c values may remain blank,
    # but any value that is present must be a finite number.
    join_fields = [
        "event_id", "origin_time_utc", "event_hour_utc",
        "m2_ledger_origin_time_utc_second_precision",
        "v004_origin_time_utc_full_precision", "stage1d_origin_time_utc_full_precision",
        "m3_minus_m2_ledger_time_seconds",
        "latitude_deg", "longitude_deg",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "m3_feature_status", "p_vtec_score_n", "t_vtec_score_n",
        "p_vtec_baseline_n", "t_vtec_baseline_n",
        "m2c_p_status", "m2c_p_failure_reason", "m2c_p_max_abs_robust_z",
        "m2c_p_q95_abs_robust_z", "m2c_t_status", "m2c_t_failure_reason",
        "m2c_t_max_abs_robust_z", "m2c_t_q95_abs_robust_z",
        "m3_p_max_abs_robust_z", "m3_p_q95_abs_robust_z",
        "m3_t_max_abs_robust_z", "m3_t_q95_abs_robust_z",
    ]
    joined_by_id: dict[str, dict[str, str]] = {}
    for event_id, m3 in m3_by_id.items():
        p = m2c_by_id[event_id]["p"]
        t = m2c_by_id[event_id]["t"]
        joined = {
            "event_id": event_id,
            **{field: m3.get(field, "") for field in [
                "origin_time_utc", "event_hour_utc", "latitude_deg", "longitude_deg",
                "station_id", "region", "role", "source_class", "magnitude", "depth_km",
                "m3_feature_status", "p_vtec_score_n", "t_vtec_score_n",
                "p_vtec_baseline_n", "t_vtec_baseline_n",
            ]},
            "m2_ledger_origin_time_utc_second_precision": ledger_by_id[event_id]["origin_time_utc"],
            "v004_origin_time_utc_full_precision": v004_by_id[event_id]["origin_time_utc"],
            "stage1d_origin_time_utc_full_precision": catalogue_by_id[event_id]["origin_time_utc"],
            "m3_minus_m2_ledger_time_seconds": f"{(m3_utc_by_id[event_id] - parse_utc(ledger_by_id[event_id]['origin_time_utc'], f'M2 ledger {event_id}')).total_seconds():.6f}",
            "m2c_p_status": p.get("status", ""),
            "m2c_p_failure_reason": p.get("failure_reason", ""),
            "m2c_p_max_abs_robust_z": p.get("feature_max_abs_robust_z", ""),
            "m2c_p_q95_abs_robust_z": p.get("feature_q95_abs_robust_z", ""),
            "m2c_t_status": t.get("status", ""),
            "m2c_t_failure_reason": t.get("failure_reason", ""),
            "m2c_t_max_abs_robust_z": t.get("feature_max_abs_robust_z", ""),
            "m2c_t_q95_abs_robust_z": t.get("feature_q95_abs_robust_z", ""),
            "m3_p_max_abs_robust_z": m3["p_vtec_max"],
            "m3_p_q95_abs_robust_z": m3["p_vtec_q95"],
            "m3_t_max_abs_robust_z": m3["t_vtec_max"],
            "m3_t_q95_abs_robust_z": m3["t_vtec_q95"],
        }
        for field in (
            "m2c_p_max_abs_robust_z", "m2c_p_q95_abs_robust_z",
            "m2c_t_max_abs_robust_z", "m2c_t_q95_abs_robust_z",
        ):
            joined[field] = finite_text(joined[field], f"M2c {event_id} {field}", allow_blank=True)
        joined_by_id[event_id] = joined

    # Reuse only the exact frozen target/control membership rows. Do not rebuild or
    # cross-join target and control components.
    allowed_cohorts = {
        "STRICT_TARGETS", "CONSERVATIVE_TARGETS", "STRICT_PHYSICAL_CONTROLS"
    }
    membership_by_cohort: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    for row in membership_rows:
        cohort = row["cohort"].strip()
        event_id = row["event_id"].strip()
        if cohort not in allowed_cohorts:
            continue
        key = (cohort, event_id)
        if key in seen_pairs:
            raise ValueError(f"Duplicate membership row: {key}")
        seen_pairs.add(key)
        if event_id not in joined_by_id:
            raise ValueError(f"Membership event missing from feature join: {event_id}")
        ledger_row = ledger_by_id[event_id]
        m3_row = m3_by_id[event_id]
        member_dt = parse_utc(row["origin_time_utc"], f"membership {cohort} {event_id}")
        ledger_dt = parse_utc(ledger_row["origin_time_utc"], f"M2 ledger {event_id}")
        feature_dt = m3_utc_by_id[event_id]
        if member_dt != ledger_dt:
            raise ValueError(f"Membership/M2 ledger origin-time mismatch for {cohort} {event_id}")
        if member_dt != feature_dt.replace(microsecond=0):
            raise ValueError(f"Membership timestamp is not the whole-second truncation of M3 for {cohort} {event_id}")
        if row["station_id"].strip().upper() != m3_row["station_id"].strip().upper():
            raise ValueError(f"Membership/M3 station mismatch for {cohort} {event_id}")
        if member_dt.replace(minute=0, second=0, microsecond=0) != feature_dt.replace(minute=0, second=0, microsecond=0):
            raise ValueError(f"Membership/M3 floored-hour mismatch for {cohort} {event_id}")
        membership_by_cohort[cohort].append(row)

    print("Frozen membership timestamp rows cross-checked against M2 ledger and M3: PASS")

    def membership_event_ids(cohort: str) -> set[str]:
        return {row["event_id"] for row in membership_by_cohort[cohort]}

    strict_ids = membership_event_ids("STRICT_TARGETS")
    conservative_ids = membership_event_ids("CONSERVATIVE_TARGETS")
    control_ids = membership_event_ids("STRICT_PHYSICAL_CONTROLS")
    if len(strict_ids) != EXPECTED["strict_targets"]:
        raise ValueError(f"Strict target count mismatch: {len(strict_ids)}")
    if len(conservative_ids) != EXPECTED["conservative_targets"]:
        raise ValueError(f"Conservative target count mismatch: {len(conservative_ids)}")
    if len(control_ids) != EXPECTED["strict_controls"]:
        raise ValueError(f"Strict control count mismatch: {len(control_ids)}")
    if not conservative_ids.issubset(strict_ids):
        raise ValueError("Conservative targets are not a subset of strict targets")
    if strict_ids & control_ids:
        raise ValueError("A target event is also listed as a physical control")

    strict_component = component_summary(membership_by_cohort["STRICT_TARGETS"])
    conservative_component = component_summary(membership_by_cohort["CONSERVATIVE_TARGETS"])
    control_component = component_summary(membership_by_cohort["STRICT_PHYSICAL_CONTROLS"])
    expected_summaries = [
        ("STRICT_TARGETS", strict_component, EXPECTED["strict_targets"], EXPECTED["strict_components"]),
        ("CONSERVATIVE_TARGETS", conservative_component, EXPECTED["conservative_targets"], EXPECTED["conservative_components"]),
        ("STRICT_PHYSICAL_CONTROLS", control_component, EXPECTED["strict_controls"], EXPECTED["control_components"]),
    ]
    for name, summary, n_events, n_components in expected_summaries:
        if summary["event_count"] != n_events or summary["component_count"] != n_components:
            raise ValueError(f"Frozen {name} component summary mismatch: {summary}")

    # Every strict/conservative target event must have all four finite M2c/M3 inputs.
    for cohort, event_ids in (("STRICT_TARGETS", strict_ids), ("CONSERVATIVE_TARGETS", conservative_ids)):
        for event_id in event_ids:
            row = joined_by_id[event_id]
            for field in (
                "m2c_p_max_abs_robust_z", "m2c_p_q95_abs_robust_z",
                "m2c_t_max_abs_robust_z", "m2c_t_q95_abs_robust_z",
                "m3_p_max_abs_robust_z", "m3_p_q95_abs_robust_z",
                "m3_t_max_abs_robust_z", "m3_t_q95_abs_robust_z",
            ):
                finite_text(row[field], f"{cohort} {event_id} {field}")

    pair_fields = [
        "cohort", "event_id", "origin_time_utc",
        "m2_ledger_origin_time_utc_second_precision",
        "membership_origin_time_utc_second_precision",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "component_id", "component_size",
        "label", "analysis_window", "m2c_max_abs_robust_z", "m2c_q95_abs_robust_z",
        "m3_vtec_max_abs_robust_z", "m3_vtec_q95_abs_robust_z",
    ]

    def make_pairs(cohort: str) -> list[dict[str, str]]:
        pairs: list[dict[str, str]] = []
        for member in sorted(
            membership_by_cohort[cohort],
            key=lambda r: (r["origin_time_utc"], r["event_id"]),
        ):
            event_id = member["event_id"]
            event = joined_by_id[event_id]
            # Membership and feature-source event identity metadata must agree.
            common = {
                "cohort": cohort,
                "event_id": event_id,
                "origin_time_utc": event["origin_time_utc"],
                "m2_ledger_origin_time_utc_second_precision": ledger_by_id[event_id]["origin_time_utc"],
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
            pairs.append({
                **common,
                "label": "0",
                "analysis_window": "W0",
                "m2c_max_abs_robust_z": event["m2c_p_max_abs_robust_z"],
                "m2c_q95_abs_robust_z": event["m2c_p_q95_abs_robust_z"],
                "m3_vtec_max_abs_robust_z": event["m3_p_max_abs_robust_z"],
                "m3_vtec_q95_abs_robust_z": event["m3_p_q95_abs_robust_z"],
            })
            pairs.append({
                **common,
                "label": "1",
                "analysis_window": "W1",
                "m2c_max_abs_robust_z": event["m2c_t_max_abs_robust_z"],
                "m2c_q95_abs_robust_z": event["m2c_t_q95_abs_robust_z"],
                "m3_vtec_max_abs_robust_z": event["m3_t_max_abs_robust_z"],
                "m3_vtec_q95_abs_robust_z": event["m3_t_q95_abs_robust_z"],
            })

        # Enforce exactly one W0/label-0 and one W1/label-1 row per event,
        # with the same frozen component assignment.
        per_event: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in pairs:
            per_event[row["event_id"]].append(row)
        if len(pairs) != 2 * len(per_event):
            raise ValueError(f"{cohort}: paired-row count mismatch")
        for event_id, rows in per_event.items():
            if sorted(r["label"] for r in rows) != ["0", "1"]:
                raise ValueError(f"{cohort}: invalid paired labels for {event_id}")
            if {r["analysis_window"] for r in rows} != {"W0", "W1"}:
                raise ValueError(f"{cohort}: invalid windows for {event_id}")
            if len({r["component_id"] for r in rows}) != 1:
                raise ValueError(f"{cohort}: pair split across components for {event_id}")
        return pairs

    strict_pairs = make_pairs("STRICT_TARGETS")
    conservative_pairs = make_pairs("CONSERVATIVE_TARGETS")

    control_fields = [
        "cohort", "event_id", "origin_time_utc",
        "m2_ledger_origin_time_utc_second_precision",
        "membership_origin_time_utc_second_precision",
        "station_id", "region", "role", "source_class", "magnitude", "depth_km",
        "component_id", "component_size",
        "m3_feature_status", "m2c_p_status", "m2c_p_failure_reason",
        "m2c_p_max_abs_robust_z", "m2c_p_q95_abs_robust_z", "m2c_t_status",
        "m2c_t_failure_reason", "m2c_t_max_abs_robust_z", "m2c_t_q95_abs_robust_z",
        "m3_p_max_abs_robust_z", "m3_p_q95_abs_robust_z",
        "m3_t_max_abs_robust_z", "m3_t_q95_abs_robust_z",
    ]
    control_audit: list[dict[str, str]] = []
    for member in sorted(
        membership_by_cohort["STRICT_PHYSICAL_CONTROLS"],
        key=lambda r: (r["origin_time_utc"], r["event_id"]),
    ):
        event_id = member["event_id"]
        event = joined_by_id[event_id]
        control_audit.append({
            "cohort": "STRICT_PHYSICAL_CONTROLS",
            "event_id": event_id,
            "origin_time_utc": event["origin_time_utc"],
            "m2_ledger_origin_time_utc_second_precision": ledger_by_id[event_id]["origin_time_utc"],
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
        })

    # Keep the frozen membership values, while exposing the full-precision
    # timestamp crosswalk used for M4 event metadata.
    membership_crosswalk_fields = [
        "cohort", "event_id", "station_id",
        "membership_origin_time_utc_second_precision",
        "feature_origin_time_utc_full_precision", "event_hour_utc",
        "component_id", "component_size",
    ]
    membership_crosswalk_rows = []
    for cohort in ("STRICT_TARGETS", "CONSERVATIVE_TARGETS"):
        for member in membership_by_cohort[cohort]:
            event = joined_by_id[member["event_id"]]
            membership_crosswalk_rows.append({
                "cohort": cohort,
                "event_id": member["event_id"],
                "station_id": member["station_id"],
                "membership_origin_time_utc_second_precision": member["origin_time_utc"],
                "feature_origin_time_utc_full_precision": event["origin_time_utc"],
                "event_hour_utc": event["event_hour_utc"],
                "component_id": member["component_id"],
                "component_size": member["component_size"],
            })

    # Create a manifest with exact input and output fingerprints. Build in a
    # temporary sibling directory and rename only after all outputs are complete.
    TEMP_DIR.mkdir(parents=True, exist_ok=False)
    output_rows = {
        "m4_event_feature_join.csv": (list(joined_by_id.values()), join_fields),
        "m4_strict_target_pairs.csv": (strict_pairs, pair_fields),
        "m4_conservative_target_pairs.csv": (conservative_pairs, pair_fields),
        "m4_physical_control_feature_audit.csv": (control_audit, control_fields),
        "m4_target_component_membership.csv": (
            membership_crosswalk_rows, membership_crosswalk_fields,
        ),
    }
    for filename, (rows, fields) in output_rows.items():
        write_csv(TEMP_DIR / filename, rows, fields)

    qa = {
        "schema": "LAIC_GUARD_M4_FEATURE_ASSEMBLY_QA_v002",
        "build_status": "PASS",
        "inference_run": False,
        "classifier_fit": False,
        "oof_predictions_created": False,
        "permutation_tests_run": False,
        "purpose": "M2c plus M3 feature assembly; strict and conservative target-only paired datasets",
        "label_definition": {
            "0": "W0 feature row",
            "1": "W1 feature row",
            "note": "Each event contributes one W0/W1 pair; labels are not target-versus-control labels.",
        },
        "inputs": {
            "m2_feature_scores": str(M2_SCORES_PATH.relative_to(ROOT)),
            "m2_event_eligibility_ledger": str(M2_LEDGER_PATH.relative_to(ROOT)),
            "m3_event_feature_scores": str(M3_SCORES_PATH.relative_to(ROOT)),
            "frozen_component_membership": str(MEMBERSHIP_PATH.relative_to(ROOT)),
            "v004_event_features_timestamp_crosscheck": str(V004_FEATURES_PATH.relative_to(ROOT)),
            "stage1d_frozen_catalogue_timestamp_crosscheck": str(STAGE1D_CATALOGUE_PATH.relative_to(ROOT)),
        },
        "timestamp_lineage": {
            "authoritative_full_precision_sources": ["M3 event features", "V004 event features", "Stage 1D frozen catalogue"],
            "full_precision_sources_agree_exactly_for_all_111_events": True,
            "m2_ledger_and_membership_precision": "whole-second truncation of the authoritative timestamp",
            "m2_ledger_matches_authoritative_whole_second_for_all_111_events": True,
            "membership_matches_m2_ledger_and_authoritative_whole_second_for_all_membership_rows": True,
            "all_membership_and_m3_timestamps_have_same_floored_utc_hour": True,
            "dependency_algorithm_uses_floored_utc_hour": True,
            "full_precision_event_timestamp_retained_in_m4_outputs": True,
            "m2_minus_feature_timestamp_precision_difference_changes_component_hour": False,
        },
        "populations": {
            "all_joined_events": len(joined_by_id),
            "strict_targets": strict_component,
            "conservative_targets": conservative_component,
            "strict_physical_controls_separate_audit_only": control_component,
            "strict_pair_rows": len(strict_pairs),
            "conservative_pair_rows": len(conservative_pairs),
            "control_audit_rows": len(control_audit),
        },
        "checks": {
            "m2c_and_m3_event_ids_match": True,
            "m3_v004_and_stage1d_full_precision_timestamps_match": True,
            "m2_ledger_is_authoritative_whole_second_truncation": True,
            "membership_timestamp_matches_m2_ledger_and_m3_hour": True,
            "exactly_two_m2c_rows_per_event": True,
            "frozen_membership_counts_match": True,
            "frozen_component_ids_reused_without_rebuilding": True,
            "target_and_control_populations_kept_separate": True,
            "all_strict_target_features_finite": True,
            "all_conservative_target_features_finite": True,
            "each_target_event_has_exactly_one_w0_and_one_w1_row": True,
            "paired_rows_share_component_id": True,
            "conservative_population_is_subset_of_strict": True,
        },
        "feature_columns_per_window": [
            "m2c_max_abs_robust_z",
            "m2c_q95_abs_robust_z",
            "m3_vtec_max_abs_robust_z",
            "m3_vtec_q95_abs_robust_z",
        ],
        "notes": [
            "The 111-event event-level join is a provenance/availability audit, not a classifier population.",
            "Only STRICT_TARGETS and CONSERVATIVE_TARGETS are written as classifier pair datasets.",
            "STRICT_PHYSICAL_CONTROLS are emitted as a separate event-level feature audit and are not pooled with targets.",
            "Component IDs are copied from the validated M2 frozen membership file, separately by cohort.",
            "M3, V004 and Stage 1D full-precision origin timestamps agree; M2 ledger/membership timestamps are verified whole-second truncations.",
            "The frozen dependency algorithm floors origin times to UTC hour before constructing intervals; subsecond serialization loss does not alter component membership.",
            "This package does not establish predictive skill or a precursor mechanism.",
        ],
    }
    qa_path = TEMP_DIR / "m4_feature_assembly_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    input_paths = [
        M2_SCORES_PATH, M2_LEDGER_PATH, M3_SCORES_PATH, MEMBERSHIP_PATH,
        V004_FEATURES_PATH, STAGE1D_CATALOGUE_PATH,
    ]
    input_info = {
        str(path.relative_to(ROOT)): {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in input_paths
    }
    output_info = {}
    for filename, (rows, _fields) in output_rows.items():
        path = TEMP_DIR / filename
        output_info[filename] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "data_rows": len(rows),
        }
    output_info["m4_feature_assembly_qa.json"] = {
        "sha256": sha256(qa_path),
        "bytes": qa_path.stat().st_size,
        "data_rows": None,
    }

    script_path = Path(__file__).resolve()
    manifest = {
        "schema": "LAIC_GUARD_M4_FEATURE_PACKAGE_MANIFEST_v002",
        "build_status": "PASS",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "builder": {
            "path": str(script_path.relative_to(ROOT)),
            "sha256": sha256(script_path),
        },
        "inputs": input_info,
        "outputs": output_info,
        "inference_run": False,
        "classifier_fit": False,
    }
    manifest_path = TEMP_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Atomic finalization; no existing package is overwritten.
    OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DIR.exists():
        raise FileExistsError(f"Output appeared during build; refusing overwrite: {OUT_DIR}")
    TEMP_DIR.rename(OUT_DIR)

    print("\n===== BUILD RESULTS =====")
    print("Output directory:", OUT_DIR.relative_to(ROOT))
    print("M4 event-level feature join:", len(joined_by_id), "events")
    print("Strict target M4 pairs:", len(strict_pairs), "rows /", len(strict_ids), "events /", strict_component["component_count"], "components")
    print("Conservative target M4 pairs:", len(conservative_pairs), "rows /", len(conservative_ids), "events /", conservative_component["component_count"], "components")
    print("Separate physical-control audit:", len(control_audit), "events /", control_component["component_count"], "components")
    print("Inference run: False")
    print("Classifier fit: False")
    print("Manifest SHA256:", sha256(OUT_DIR / "manifest.json"))
    print("QA SHA256:", sha256(OUT_DIR / "m4_feature_assembly_qa.json"))
    print("BUILD COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"BUILD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
