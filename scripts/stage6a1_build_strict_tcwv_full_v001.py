from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import sys
import types

from collections import Counter
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ENGINE_PATH = ROOT / "scripts/stage6a1_build_strict_tcwv_features_v001.py"

EXPECTED_ENGINE_SHA256 = (
    "F9B9DA0226E313BA211D7ADE8F75FD01B0F7807EB73A351A0C4FD8FA8753BB7D"
)

OUTPUT_DIR = ROOT / "reports/stage6a1/strict_tcwv_v001/full_v001"
TEMP_OUTPUT_DIR = OUTPUT_DIR.with_name(OUTPUT_DIR.name + ".tmp")

EXPECTED_COUNTS = {
    "all_events": 111,
    "original_targets": 90,
    "original_target_components": 38,
    "strict_targets": 88,
    "strict_target_components": 36,
    "conservative_targets": 87,
    "conservative_target_components": 35,
    "strict_controls": 19,
    "strict_control_components": 15,
}

EXPECTED_TARGET_EXCLUSIONS = {
    "us7000lsze",
    "us7000m9g4",
}

EXPECTED_CONTROL_EXCLUSIONS = {
    "us6000m52p",
    "us7000n05d",
}

G088_EVENT_ID = "us6000nith"

UTC = __import__("datetime").timezone.utc


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_engine():
    require(ENGINE_PATH.is_file(), f"Pilot engine missing: {ENGINE_PATH}")

    original_hash = sha256_file(ENGINE_PATH)
    require(
        original_hash == EXPECTED_ENGINE_SHA256,
        f"Pilot engine SHA256 mismatch: {original_hash}",
    )

    source = ENGINE_PATH.read_text(encoding="utf-8-sig")

    # The pilot engine has five event-specific reference-note keys.
    # Use a neutral fallback for other events, in memory only.
    old = '"reference_note_addendum002": reference_notes[eid],'
    new = (
        '"reference_note_addendum002": '
        'reference_notes.get(eid, '
        '"No event-specific pilot reference count supplied."),'
    )

    require(
        source.count(old) == 1,
        "Expected event-reference expression not found exactly once.",
    )

    patched_source = source.replace(old, new, 1)
    ast.parse(patched_source)

    engine = types.ModuleType("stage6a1_full_engine")
    engine.__file__ = str(ENGINE_PATH)
    exec(
        compile(patched_source, str(ENGINE_PATH), "exec"),
        engine.__dict__,
    )

    return engine, original_hash, sha256_bytes(
        patched_source.encode("utf-8")
    )


def primary_components(records, engine):
    ordered = sorted(
        records,
        key=lambda r: engine.parse_utc(r["origin_time_utc"]),
    )

    n = len(ordered)
    if n == 0:
        return {}, [], {
            "time_overlap_pairs": 0,
            "same_station_within_50d_pairs": 0,
            "connected_pairs": 0,
        }

    times = [
        engine.parse_utc(r["origin_time_utc"]).replace(
            minute=0, second=0, microsecond=0
        )
        for r in ordered
    ]

    stations = [
        str(r.get("station_id", "")).strip().upper()
        for r in ordered
    ]

    starts = [t - timedelta(hours=1080) for t in times]
    ends = [t - timedelta(hours=24) for t in times]

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edge_counts = Counter()

    for i in range(n):
        for j in range(i + 1, n):
            overlap = starts[i] < ends[j] and starts[j] < ends[i]

            same_station = (
                bool(stations[i]) and stations[i] == stations[j]
            )

            gap_days = abs(
                (times[j] - times[i]).total_seconds()
            ) / 86400.0

            station_link = same_station and gap_days <= 50.0

            if overlap:
                edge_counts["time_overlap_pairs"] += 1

            if station_link:
                edge_counts["same_station_within_50d_pairs"] += 1

            if overlap or station_link:
                edge_counts["connected_pairs"] += 1
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    members = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    ordered_roots = sorted(
        members,
        key=lambda root: min(members[root]),
    )

    event_to_component = {}
    component_rows = []

    for rank, root in enumerate(ordered_roots, start=1):
        component_id = f"DEP{rank:03d}"
        indices = members[root]
        event_ids = [ordered[i]["event_id"] for i in indices]

        for event_id in event_ids:
            event_to_component[event_id] = component_id

        for i in indices:
            row = ordered[i]
            component_rows.append({
                "event_id": row["event_id"],
                "station_id": row["station_id"],
                "origin_time_utc": row["origin_time_utc"],
                "component_id": component_id,
                "component_size": len(indices),
            })

    return event_to_component, component_rows, dict(edge_counts)


def component_summary(cohort_name, records, components, edges):
    unique_components = {}

    for row in components:
        component_id = row["component_id"]
        component_size = int(row["component_size"])

        if component_id in unique_components:
            if unique_components[component_id] != component_size:
                raise RuntimeError(
                    f"Inconsistent size for component {component_id}"
                )
        else:
            unique_components[component_id] = component_size

    sizes = Counter(unique_components.values())

    return {
        "cohort": cohort_name,
        "event_count": len(records),
        "component_count": len(unique_components),
        "component_size_distribution": json.dumps(
            dict(sorted(sizes.items())), sort_keys=True
        ),
        "largest_component": max(unique_components.values(), default=0),
        "edge_diagnostics": json.dumps(edges, sort_keys=True),
    }


def write_csv(path, rows):
    require(bool(rows), f"Refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )


def main():
    require(not OUTPUT_DIR.exists(),
            f"Output already exists; refusing overwrite: {OUTPUT_DIR}")
    require(not TEMP_OUTPUT_DIR.exists(),
            f"Temporary output already exists: {TEMP_OUTPUT_DIR}")

    engine, engine_hash, patched_engine_hash = load_engine()

    print("ENGINE_SHA256:", engine_hash)
    print("IN_MEMORY_COMPATIBILITY_PATCH: VERIFIED")
    print("ENGINE_SYNTAX: PASS")

    tests = engine.run_unit_tests()
    require(
        all(row["status"] == "PASS" for row in tests),
        "One or more physical unit tests failed.",
    )

    data, input_hashes = engine.load_and_verify_inputs()

    print("\n===== VERIFIED INPUTS =====")
    print("V004 events:", len(data["v004"]))
    print("Stage 4B events:", len(data["stage4b"]))
    print("Stage 2C rows:", len(data["stage2c"]))
    print("Station registry rows:", data["registry_rows"])
    print("ERA5 manifest records:", len(data["manifest"]["records"]))

    event_rows = list(data["v004"].values())
    require(len(event_rows) == EXPECTED_COUNTS["all_events"],
            "Full input event count is not 111.")

    ledgers = []
    hourly_rows = []
    calibration_rows = []
    score_rows = []
    hour_stat_rows = []
    daily_rows = []
    parser_rows = []
    cache_provenance = {}

    print("\n===== FULL 111-EVENT FEATURE GENERATION =====")

    for index, event in enumerate(event_rows, start=1):
        eid = event["event_id"]
        sid = event["station_id"].strip().upper()

        result = engine.process_pilot_event(
            event,
            data["registry"][sid][0],
            data["stage2c"][eid],
            data["manifest"],
        )

        ledger = result["ledger"]

        # Preserve the pre-existing V004 component labels as provenance only.
        ledger["v004_time_component_provenance"] = event.get(
            "dep_component_time_v004", ""
        )
        ledger["v004_primary_component_provenance"] = event.get(
            "dep_component_primary_v004", ""
        )
        ledger["v004_station_any_component_provenance"] = event.get(
            "dep_component_station_any_v004", ""
        )

        ledger["dependency_component_original_target"] = ""
        ledger["dependency_component_strict_target"] = ""
        ledger["dependency_component_conservative_target"] = ""
        ledger["dependency_component_strict_control"] = ""

        ledgers.append(ledger)
        hourly_rows.extend(result["hourly"])
        calibration_rows.extend(result["calibrations"])
        score_rows.extend(result["scores"])
        hour_stat_rows.extend(result["hour_stats"])
        daily_rows.extend(result["daily"])
        parser_rows.append(result["parser_audit"])

        cache_provenance[eid] = {
            "station_id": sid,
            "era5_cache_sha256": result["era5"]["cache_sha256"],
            "era5_cache_path": result["era5"]["cache_path"],
            "gnss_archives": result["gnss"]["archive_records"],
        }

        status = ledger["eligibility_status"]
        print(
            f"[{index:03d}/{len(event_rows)}] "
            f"{eid}/{sid} {status}"
        )

        del result

    require(len(ledgers) == 111, "Full ledger does not contain 111 events.")
    require(
        len({r["event_id"] for r in ledgers}) == 111,
        "Duplicate or missing event IDs in full ledger.",
    )

    ledger_by_id = {r["event_id"]: r for r in ledgers}

    original_targets = [
        r for r in ledgers
        if r["role"] == "PRIMARY_SHALLOW_TARGET"
    ]

    original_controls = [
        r for r in ledgers
        if r["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"
    ]

    strict_targets = [
        r for r in original_targets
        if r["strict_m2c_feature_eligible"]
    ]

    strict_controls = [
        r for r in original_controls
        if r["strict_m2c_feature_eligible"]
    ]

    ineligible_targets = {
        r["event_id"] for r in original_targets
        if not r["strict_m2c_feature_eligible"]
    }

    ineligible_controls = {
        r["event_id"] for r in original_controls
        if not r["strict_m2c_feature_eligible"]
    }

    require(
        ineligible_targets == EXPECTED_TARGET_EXCLUSIONS,
        f"Unexpected strict-target exclusions: {sorted(ineligible_targets)}",
    )
    require(
        ineligible_controls == EXPECTED_CONTROL_EXCLUSIONS,
        f"Unexpected strict-control exclusions: {sorted(ineligible_controls)}",
    )

    # Rebuild all evaluation-specific primary dependency groups.
    original_map, original_components, original_edges = (
        primary_components(original_targets, engine)
    )

    strict_map, strict_components, strict_edges = (
        primary_components(strict_targets, engine)
    )

    require(
        G088_EVENT_ID in strict_map,
        "G088 is absent from the strict target population.",
    )

    g088_component = strict_map[G088_EVENT_ID]

    g088_component_members = {
        event_id
        for event_id, component_id in strict_map.items()
        if component_id == g088_component
    }

    conservative_targets = [
        r for r in strict_targets
        if r["event_id"] not in g088_component_members
    ]

    conservative_map, conservative_components, conservative_edges = (
        primary_components(conservative_targets, engine)
    )

    control_map, control_components, control_edges = (
        primary_components(strict_controls, engine)
    )

    cohort_results = [
        (
            "ORIGINAL_TARGETS",
            original_targets,
            original_map,
            original_components,
            original_edges,
            "dependency_component_original_target",
        ),
        (
            "STRICT_TARGETS",
            strict_targets,
            strict_map,
            strict_components,
            strict_edges,
            "dependency_component_strict_target",
        ),
        (
            "CONSERVATIVE_TARGETS",
            conservative_targets,
            conservative_map,
            conservative_components,
            conservative_edges,
            "dependency_component_conservative_target",
        ),
        (
            "STRICT_PHYSICAL_CONTROLS",
            strict_controls,
            control_map,
            control_components,
            control_edges,
            "dependency_component_strict_control",
        ),
    ]

    membership_rows = []
    summary_rows = []
    edge_rows = []

    for (
        cohort_name,
        population,
        mapping,
        components,
        edges,
        ledger_field,
    ) in cohort_results:

        for record in population:
            eid = record["event_id"]
            component_id = mapping[eid]
            ledger_by_id[eid][ledger_field] = component_id

        for component in components:
            component["cohort"] = cohort_name
            membership_rows.append({
                "cohort": cohort_name,
                **component,
            })

        summary_rows.append(
            component_summary(
                cohort_name, population, components, edges
            )
        )

        edge_rows.append({
            "cohort": cohort_name,
            "time_overlap_pairs": edges.get("time_overlap_pairs", 0),
            "same_station_within_50d_pairs":
                edges.get("same_station_within_50d_pairs", 0),
            "connected_pairs": edges.get("connected_pairs", 0),
        })

    observed_counts = {
        "all_events": len(ledgers),
        "original_targets": len(original_targets),
        "original_target_components": len({
            row["component_id"] for row in original_components
        }),
        "strict_targets": len(strict_targets),
        "strict_target_components": len({
            row["component_id"] for row in strict_components
        }),
        "conservative_targets": len(conservative_targets),
        "conservative_target_components": len({
            row["component_id"] for row in conservative_components
        }),
        "strict_controls": len(strict_controls),
        "strict_control_components": len({
            row["component_id"] for row in control_components
        }),
    }

    print("\n===== FULL COHORT AND DEPENDENCY GATES =====")
    for name, expected in EXPECTED_COUNTS.items():
        observed = observed_counts[name]
        passed = observed == expected
        print(
            name,
            "EXPECTED=", expected,
            "OBSERVED=", observed,
            "PASS" if passed else "FAIL",
        )
        require(passed, f"Frozen cohort gate failed: {name}")

    print(
        "G088 component:",
        g088_component,
        "members:",
        sorted(g088_component_members),
    )

    require(
        len(hourly_rows) == 111 * 1081,
        f"Unexpected full hourly row count: {len(hourly_rows)}",
    )
    require(len(calibration_rows) == 222,
            "Expected 222 calibration rows.")
    require(len(score_rows) == 111 * 6,
            "Expected six feature-score rows per event.")
    require(len(parser_rows) == 111,
            "Expected one GNSS parser audit row per event.")

    qa = {
        "schema": "LAIC_GUARD_STAGE6A1_FULL_FEATURE_QA_v001",
        "status": "FULL_FEATURE_GENERATION_COMPLETED",
        "script": Path(__file__).name,
        "engine_script": ENGINE_PATH.name,
        "engine_original_sha256": engine_hash,
        "engine_in_memory_compatibility_patch_sha256":
            patched_engine_hash,
        "events_processed": len(ledgers),
        "hourly_feature_rows": len(hourly_rows),
        "calibration_rows": len(calibration_rows),
        "feature_score_rows": len(score_rows),
        "hourly_baseline_stat_rows": len(hour_stat_rows),
        "daily_coverage_rows": len(daily_rows),
        "gnss_parser_audit_rows": len(parser_rows),
        "unit_tests_passed": len(tests),
        "cohort_counts": observed_counts,
        "ineligible_target_ids": sorted(ineligible_targets),
        "ineligible_control_ids": sorted(ineligible_controls),
        "G088_primary_component": g088_component,
        "G088_component_members": sorted(g088_component_members),
        "dependency_population_summaries": summary_rows,
        "expected_reference_counts": EXPECTED_COUNTS,
        "input_hashes": input_hashes,
        "statistical_inference_run": False,
        "benchmark_run": False,
        "notes": [
            "This package contains feature generation and eligibility only.",
            "No AUC, model fitting, cross-validation or permutations were run.",
            "Strict populations were recalculated from all 111 pinned caches.",
            "Dependence components were rebuilt for each exact evaluation subset.",
            "V004 component labels are provenance only, not evaluation groups.",
            "G088 remains in the main strict target population and is excluded from the conservative target population by its complete component.",
            "Direct TCWV only; no dew-point fallback or TCWV imputation.",
            "NGL legacy time scale remains LEGACY_SINEX_UTC_INFERRED.",
            "ERA5 model was requested explicitly; API response metadata is not independent model attestation.",
        ],
    }

    # Write only after all 111 events and all frozen cohort gates pass.
    TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=False)

    try:
        outputs = {
            "full_event_eligibility_ledger.csv": ledgers,
            "full_hourly_features.csv": hourly_rows,
            "full_calibration_diagnostics.csv": calibration_rows,
            "full_feature_scores.csv": score_rows,
            "full_hourly_baseline_stats.csv": hour_stat_rows,
            "full_daily_coverage.csv": daily_rows,
            "full_gnss_parser_audit.csv": parser_rows,
            "full_unit_tests.csv": tests,
            "full_dependency_component_membership.csv": membership_rows,
            "full_dependency_population_summary.csv": summary_rows,
            "full_dependency_edge_diagnostics.csv": edge_rows,
        }

        for filename, rows in outputs.items():
            write_csv(TEMP_OUTPUT_DIR / filename, rows)

        write_json(TEMP_OUTPUT_DIR / "full_qa.json", qa)

        output_hashes = {}
        for path in sorted(TEMP_OUTPUT_DIR.iterdir()):
            if path.is_file():
                output_hashes[path.name] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }

        manifest = {
            "schema": "LAIC_GUARD_STAGE6A1_FULL_FEATURE_MANIFEST_v001",
            "created_at_utc": __import__("datetime").datetime.now(UTC).isoformat(),
            "script_sha256": sha256_file(Path(__file__)),
            "engine_original_sha256": engine_hash,
            "engine_in_memory_compatibility_patch_sha256":
                patched_engine_hash,
            "input_sha256": input_hashes,
            "cohort_counts": observed_counts,
            "event_cache_and_archive_provenance": cache_provenance,
            "statistical_inference_run": False,
            "benchmark_run": False,
            "output_files": output_hashes,
        }

        write_json(TEMP_OUTPUT_DIR / "manifest.json", manifest)

        require(
            not OUTPUT_DIR.exists(),
            f"Output appeared during run; refusing overwrite: {OUTPUT_DIR}",
        )
        os.replace(TEMP_OUTPUT_DIR, OUTPUT_DIR)

    except Exception:
        print(
            "Temporary output retained for inspection:",
            TEMP_OUTPUT_DIR,
            file=sys.stderr,
        )
        raise

    print("\n===== FULL STAGE 6A.1 FEATURE BUILD COMPLETE =====")
    print("Output:", OUTPUT_DIR)
    print("Events:", len(ledgers))
    print("Hourly rows:", len(hourly_rows))
    print("Strict targets:", len(strict_targets))
    print("Conservative targets:", len(conservative_targets))
    print("Strict physical controls:", len(strict_controls))
    print("Statistical inference: NOT RUN")
    print("Benchmark: NOT RUN")
    print("Original V004, ERA5 caches and pilot package: unchanged")


if __name__ == "__main__":
    main()
