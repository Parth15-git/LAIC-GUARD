#!/usr/bin/env python3
"""Build the LAIC-GUARD Stage 1C.2 pilot target-region crosswalk.

Offline-only. This script does not contact USGS, download events, modify the
frozen target catalogue, or assign sequence IDs/event roles.

Expected input: metadata/event_catalogue_v002.csv with the frozen SHA-256 below.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = "0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315"
EXPECTED_ROWS = 1186
SCRIPT_VERSION = "v001"

# These are the same exploratory bounding boxes used in Stage 1C.1.
# They are operational count windows, NOT tectonic-region polygons.
PILOT_BOXES = {
    "HIMALAYA_TIBET": {"west": 60.0, "east": 105.0, "south": 20.0, "north": 42.0},
    "JAPAN_KURIL": {"west": 125.0, "east": 180.0, "south": 30.0, "north": 60.0},
    "SUNDA_INDONESIA": {"west": 90.0, "east": 145.0, "south": -15.0, "north": 25.0},
    "ANDES": {"west": -85.0, "east": -55.0, "south": -60.0, "north": 15.0},
}

# Exact intersection of the two overlapping pilot rectangles.
OVERLAP_BOX = {"west": 90.0, "east": 105.0, "south": 20.0, "north": 25.0}
PERIODS = {
    "2000_2009": (2000, 2009),
    "2010_2019": (2010, 2019),
    "2020_2025": (2020, 2025),
}
EXPLICIT_MW_TYPES = {"mww", "mwc", "mwb", "mwr"}
GENERIC_MW_TYPES = {"mw"}
REQUIRED_COLUMNS = {
    "event_id", "origin_time_utc", "latitude_deg", "longitude_deg",
    "depth_km", "magnitude", "magnitude_type", "event_type", "place"
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def as_float(value: str, field: str, event_id: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field} for event {event_id}: {value!r}") from exc
    if not math.isfinite(x):
        raise ValueError(f"Non-finite {field} for event {event_id}: {value!r}")
    return x


def inside_box(lon: float, lat: float, box: dict[str, float]) -> bool:
    # Input catalogue longitudes are expected in [-180, 180]. All four selected
    # pilot windows have non-wrapping longitude intervals.
    return box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]


def parse_year(value: str, event_id: str) -> int:
    try:
        # Handles ISO 8601 timestamps ending in Z.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).year
    except Exception as exc:
        raise ValueError(f"Invalid origin_time_utc for event {event_id}: {value!r}") from exc


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the offline Stage 1C.2 pilot target-region crosswalk.")
    ap.add_argument("--input", default="metadata/event_catalogue_v002.csv", help="Frozen Stage 1A v002 target catalogue")
    ap.add_argument("--output-dir", default="reports/stage1c2/pilot_v001", help="Output directory")
    ap.add_argument("--allow-hash-mismatch", action="store_true", help="Diagnostic override only; never use for a frozen project run")
    ap.add_argument("--force", action="store_true", help="Overwrite expected output files if they already exist")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input catalogue not found: {input_path}")

    expected_outputs = [
        "stage1c2_pilot_region_spec_v001.csv",
        "stage1c2_target_region_crosswalk_v001.csv",
        "stage1c2_overlap_review_events_v001.csv",
        "stage1c2_pilot_assignment_summary_v001.json",
        "STAGE1C2_PILOT_REGION_ASSIGNMENT_v001.md",
    ]
    existing_outputs = [str(output_dir / name) for name in expected_outputs if (output_dir / name).exists()]
    if existing_outputs and not args.force:
        raise FileExistsError("Refusing to overwrite existing outputs. Choose a new --output-dir or pass --force:\n" + "\n".join(existing_outputs))

    source_hash = sha256_file(input_path)
    if source_hash != EXPECTED_SHA256 and not args.allow_hash_mismatch:
        raise ValueError(
            "Frozen target catalogue SHA-256 mismatch. Refusing to create outputs.\n"
            f"Expected: {EXPECTED_SHA256}\nActual:   {source_hash}"
        )

    with input_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"Required catalogue columns missing: {missing}")
        source_rows = list(reader)

    if len(source_rows) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} catalogue rows; found {len(source_rows)}")

    ids = [r["event_id"].strip() for r in source_rows]
    if any(not x for x in ids):
        raise ValueError("Blank event_id detected")
    duplicate_ids = [k for k, n in Counter(ids).items() if n > 1]
    if duplicate_ids:
        raise ValueError(f"Duplicate event IDs detected: {duplicate_ids[:10]}")

    crosswalk: list[dict[str, Any]] = []
    period_counts: dict[str, Counter[str]] = {p: Counter() for p in PERIODS}
    assignment_counts: Counter[str] = Counter()
    membership_counts: Counter[str] = Counter()
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    depth10_counts: Counter[str] = Counter()
    overlap_ids: list[dict[str, Any]] = []
    outside_ids: list[str] = []

    for raw in source_rows:
        eid = raw["event_id"].strip()
        lon = as_float(raw["longitude_deg"], "longitude_deg", eid)
        lat = as_float(raw["latitude_deg"], "latitude_deg", eid)
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError(f"Coordinates out of range for {eid}: lon={lon}, lat={lat}")
        if raw["event_type"].strip().lower() != "earthquake":
            raise ValueError(f"Non-earthquake event in frozen target catalogue: {eid}")

        hits = [name for name, box in PILOT_BOXES.items() if inside_box(lon, lat, box)]
        h = "HIMALAYA_TIBET" in hits
        s = "SUNDA_INDONESIA" in hits
        if h and s:
            assignment = "OVERLAP_REVIEW_HIMALAYA_SUNDA"
        elif h:
            assignment = "HIMALAYA_TIBET_CORE"
        elif s:
            assignment = "SUNDA_INDONESIA_CORE"
        elif "JAPAN_KURIL" in hits:
            assignment = "JAPAN_KURIL"
        elif "ANDES" in hits:
            assignment = "ANDES"
        else:
            assignment = "OUTSIDE_PILOT"

        year = parse_year(raw["origin_time_utc"], eid)
        period = next((p for p, (a, b) in PERIODS.items() if a <= year <= b), "OUTSIDE_TARGET_PERIOD")
        mtype = (raw.get("magnitude_type") or "").strip().lower()
        assignment_counts[assignment] += 1
        for hit in hits:
            membership_counts[hit] += 1
        if period in period_counts:
            period_counts[period][assignment] += 1
        type_counts[assignment][mtype or "(missing)"] += 1
        if (raw.get("depth_km") or "").strip():
            depth = as_float(raw["depth_km"], "depth_km", eid)
            if abs(depth - 10.0) < 1e-9:
                depth10_counts[assignment] += 1
        if assignment == "OVERLAP_REVIEW_HIMALAYA_SUNDA":
            overlap_ids.append({
                "event_id": eid,
                "origin_time_utc": raw["origin_time_utc"],
                "latitude_deg": lat,
                "longitude_deg": lon,
                "magnitude": raw["magnitude"],
                "magnitude_type": mtype,
                "place": raw["place"],
            })
        if assignment == "OUTSIDE_PILOT":
            outside_ids.append(eid)

        crosswalk.append({
            "event_id": eid,
            "origin_time_utc": raw["origin_time_utc"],
            "year_utc": year,
            "target_period": period,
            "latitude_deg": lat,
            "longitude_deg": lon,
            "depth_km": raw["depth_km"],
            "magnitude": raw["magnitude"],
            "magnitude_type": mtype,
            "event_type": raw["event_type"],
            "place": raw["place"],
            "in_himalaya_tibet_box": h,
            "in_japan_kuril_box": "JAPAN_KURIL" in hits,
            "in_sunda_indonesia_box": s,
            "in_andes_box": "ANDES" in hits,
            "pilot_box_membership_count": len(hits),
            "pilot_box_memberships": ";".join(hits),
            "pilot_assignment_v001": assignment,
            "is_in_four_region_pilot_union": assignment != "OUTSIDE_PILOT",
            "is_overlap_review": assignment == "OVERLAP_REVIEW_HIMALAYA_SUNDA",
        })

    expected_assignment_counts = {
        "HIMALAYA_TIBET_CORE": 35,
        "JAPAN_KURIL": 138,
        "SUNDA_INDONESIA_CORE": 239,
        "ANDES": 127,
        "OVERLAP_REVIEW_HIMALAYA_SUNDA": 7,
        "OUTSIDE_PILOT": 640,
    }
    actual_assignment_counts = {k: int(assignment_counts.get(k, 0)) for k in expected_assignment_counts}
    if actual_assignment_counts != expected_assignment_counts and not args.allow_hash_mismatch:
        raise AssertionError(f"Spatial assignment counts differ from audited expectation: {actual_assignment_counts}")
    if sum(actual_assignment_counts.values()) != EXPECTED_ROWS:
        raise AssertionError("Exclusive assignment counts do not sum to the frozen target row count")

    region_spec_rows = []
    for rid, box in PILOT_BOXES.items():
        region_spec_rows.append({
            "region_id": rid,
            "role": "candidate_operational_pilot_box",
            **box,
            "boundary_semantics": "inclusive rectangle; exploratory Stage 1C.1 box; not a tectonic polygon",
        })
    region_spec_rows.append({
        "region_id": "HIMALAYA_SUNDA_INTERSECTION",
        "role": "overlap_review_intersection",
        **OVERLAP_BOX,
        "boundary_semantics": "exact geometric intersection of Himalaya-Tibet and Sunda-Indonesia candidate boxes",
    })
    write_csv(output_dir / "stage1c2_pilot_region_spec_v001.csv", region_spec_rows,
              ["region_id", "role", "west", "east", "south", "north", "boundary_semantics"])

    crosswalk_fields = list(crosswalk[0].keys()) if crosswalk else []
    write_csv(output_dir / "stage1c2_target_region_crosswalk_v001.csv", crosswalk, crosswalk_fields)
    write_csv(output_dir / "stage1c2_overlap_review_events_v001.csv", overlap_ids,
              ["event_id", "origin_time_utc", "latitude_deg", "longitude_deg", "magnitude", "magnitude_type", "place"])

    summary = {
        "project": "LAIC-GUARD",
        "stage": "1C.2",
        "artifact": "pilot_region_assignment",
        "version": SCRIPT_VERSION,
        "status": "DRAFT_FOR_REVIEW",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input": {
            "path_as_supplied": args.input,
            "resolved_path": str(input_path),
            "rows": len(source_rows),
            "sha256": source_hash,
            "frozen_expected_sha256": EXPECTED_SHA256,
            "hash_match": source_hash == EXPECTED_SHA256,
        },
        "scope": "Frozen Stage 1A target catalogue only; no supporting event data; no network calls; no sequence labels.",
        "region_semantics": "Exploratory rectangular operational pilot windows, not tectonic regions or plate polygons.",
        "assignment_rule": "Mutually exclusive assignment; the exact Himalaya-Tibet/Sunda-Indonesia intersection is retained as OVERLAP_REVIEW_HIMALAYA_SUNDA and excluded from both core strata.",
        "pilot_boxes": PILOT_BOXES,
        "overlap_intersection_box": OVERLAP_BOX,
        "original_box_membership_counts": {k: int(membership_counts[k]) for k in PILOT_BOXES},
        "exclusive_assignment_counts": actual_assignment_counts,
        "period_assignment_counts": {p: {k: int(v.get(k, 0)) for k in expected_assignment_counts} for p, v in period_counts.items()},
        "magnitude_type_counts_by_assignment": {a: dict(c) for a, c in type_counts.items()},
        "depth_exactly_10km_by_assignment": {a: int(depth10_counts.get(a, 0)) for a in expected_assignment_counts},
        "overlap_event_ids": [x["event_id"] for x in overlap_ids],
        "outside_pilot_event_count": len(outside_ids),
        "checks": {
            "row_count_1186": len(source_rows) == EXPECTED_ROWS,
            "unique_event_ids": len(set(ids)) == len(ids),
            "all_event_type_earthquake": all(r["event_type"].strip().lower() == "earthquake" for r in source_rows),
            "all_coordinates_valid": True,
            "exclusive_assignments_sum_to_1186": sum(actual_assignment_counts.values()) == EXPECTED_ROWS,
            "overlap_count_7": len(overlap_ids) == 7,
            "no_event_records_downloaded": True,
            "sequence_ids_assigned": False,
        },
        "outputs": [
            "stage1c2_pilot_region_spec_v001.csv",
            "stage1c2_target_region_crosswalk_v001.csv",
            "stage1c2_overlap_review_events_v001.csv",
            "stage1c2_pilot_assignment_summary_v001.json",
            "STAGE1C2_PILOT_REGION_ASSIGNMENT_v001.md",
        ],
    }
    summary_path = output_dir / "stage1c2_pilot_assignment_summary_v001.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Compact human-readable report.
    lines = [
        "# LAIC-GUARD Stage 1C.2 — Pilot Region Assignment v001",
        "",
        "**Status:** DRAFT FOR REVIEW  ",
        f"**Input rows:** {len(source_rows)}  ",
        f"**Input SHA-256:** `{source_hash}`  ",
        "**Network calls:** none  ",
        "**Supporting event records downloaded:** 0",
        "",
        "## Purpose and scope",
        "",
        "This artifact assigns the frozen Stage 1A v002 target events to mutually exclusive bookkeeping strata for a candidate four-domain pilot. It does not define tectonic regions, estimate magnitude completeness, change the source catalogue, or assign sequence labels.",
        "",
        "The four candidate boxes are retained exactly as used in Stage 1C.1. They are exploratory operational rectangles, not tectonic polygons. The Himalaya-Tibet and Sunda-Indonesia rectangles intersect; the exact intersection is preserved as a separate review stratum.",
        "",
        "## Exclusive target assignment",
        "",
        "| Assignment | Target events |",
        "|---|---:|",
    ]
    for key in ["HIMALAYA_TIBET_CORE", "JAPAN_KURIL", "SUNDA_INDONESIA_CORE", "ANDES", "OVERLAP_REVIEW_HIMALAYA_SUNDA", "OUTSIDE_PILOT"]:
        lines.append(f"| {key} | {actual_assignment_counts[key]} |")
    lines += [
        f"| **Total** | **{sum(actual_assignment_counts.values())}** |",
        "",
        "## Original candidate-box memberships",
        "",
        "| Box | Memberships |",
        "|---|---:|",
    ]
    for key in PILOT_BOXES:
        lines.append(f"| {key} | {int(membership_counts[key])} |")
    lines += [
        "",
        "The four box-membership totals are not additive. The seven events in the Himalaya-Tibet/Sunda-Indonesia intersection are counted in both original boxes but assigned once to the overlap-review stratum.",
        "",
        "## Period distribution",
        "",
        "| Assignment | 2000–2009 | 2010–2019 | 2020–2025 |",
        "|---|---:|---:|---:|",
    ]
    for key in ["HIMALAYA_TIBET_CORE", "JAPAN_KURIL", "SUNDA_INDONESIA_CORE", "ANDES", "OVERLAP_REVIEW_HIMALAYA_SUNDA", "OUTSIDE_PILOT"]:
        vals = [int(period_counts[p].get(key, 0)) for p in PERIODS]
        lines.append(f"| {key} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines += [
        "",
        "The 2020–2025 interval is six calendar years and is not comparable to a complete ten-year period without exposure-time normalization. These are target-event counts, not supporting-catalogue completeness estimates.",
        "",
        "## Assignment rule",
        "",
        "1. Assign an event to `OVERLAP_REVIEW_HIMALAYA_SUNDA` when it falls inside both candidate boxes.",
        "2. Assign Himalaya-only and Sunda-only events to their respective core strata.",
        "3. Assign Japan-Kuril and Andes events to their respective strata.",
        "4. Assign all remaining target events to `OUTSIDE_PILOT`.",
        "",
        "This rule is deterministic and mutually exclusive. It is a geographic bookkeeping rule only; it does not adjudicate tectonic setting or event identity.",
        "",
        "## Next gate",
        "",
        "Review this assignment and approve or amend the pilot-window specification. Only after that should a separate Stage 1C.2 count-only acquisition plan be frozen. Proposed lower preferred-magnitude thresholds are exploratory planning values, not Mw thresholds or chosen analytical cutoffs. No event retrieval is authorized by this artifact.",
        "",
        "## Reproducibility",
        "",
        "Run `13_build_stage1c2_pilot_crosswalk_v001.py` from the repository root with the frozen input path. The script verifies the SHA-256 and expected row count before producing outputs. It performs no network access.",
    ]
    (output_dir / "STAGE1C2_PILOT_REGION_ASSIGNMENT_v001.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("STAGE 1C.2 PILOT TARGET ASSIGNMENT COMPLETE")
    print(f"Input rows / unique IDs       : {len(source_rows)} / {len(set(ids))}")
    print(f"Input SHA-256                 : {source_hash}")
    print("Exclusive assignment counts  :")
    for key, value in actual_assignment_counts.items():
        print(f"  {key:<42}: {value}")
    print("Original box memberships    :")
    for key in PILOT_BOXES:
        print(f"  {key:<42}: {int(membership_counts[key])}")
    print("Network calls                 : 0")
    print("Supporting event records     : 0")
    print("Sequence labels assigned      : NO")
    print(f"Outputs                       : {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
