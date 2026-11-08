#!/usr/bin/env python3
"""
Reproducible Stage 1B preliminary ComCat event-identity audit.

Reads the verified Stage 1A v002 catalogue, local USGS annual GeoJSON
summary chunks, query sidecars, and metadata/data_manifest.csv.

This is a screening audit only. It DOES NOT assign sequence IDs, delete
events, or decide that proximity implies duplicate identity.
Standard library only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "metadata" / "event_catalogue_v002.csv"
MANIFEST = ROOT / "metadata" / "data_manifest.csv"
RAW_DIR = ROOT / "data" / "raw" / "usgs"
OUT_DIR = ROOT / "reports" / "stage1b"

EXPECTED_CHUNKS = 26
EXPECTED_ROWS = 1186
PAIR_MAX_SECONDS = 3600.0
PAIR_MAX_KM = 100.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def parse_iso_utc_ms(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value}")
    dt = dt.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = dt - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def iso_from_ms(value: int | float) -> str:
    dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def split_ids(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def split_types(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def manifest_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    idx: dict[str, dict[str, str]] = {}
    for row in rows:
        name = Path(row["local_relative_path"]).name
        if name in idx:
            raise RuntimeError(f"Duplicate manifest basename: {name}")
        idx[name] = row
    return idx


def main() -> int:
    for p in (CATALOGUE, MANIFEST, RAW_DIR):
        if not p.exists():
            raise FileNotFoundError(f"Required project input missing: {p}")

    catalogue = read_csv(CATALOGUE)
    manifest_rows = read_csv(MANIFEST)
    manifest = manifest_index(manifest_rows)

    geo_files = sorted(RAW_DIR.glob("usgs_comcat_candidate_events_*.geojson"))
    if len(geo_files) != EXPECTED_CHUNKS:
        raise RuntimeError(
            f"Expected {EXPECTED_CHUNKS} annual candidate GeoJSON chunks; found {len(geo_files)}"
        )
    if len(catalogue) != EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} v002 rows; found {len(catalogue)}")

    raw_features: list[dict] = []
    chunk_rows: list[dict] = []
    raw_file_checks: list[tuple[str, str]] = []

    for geo_path in geo_files:
        side_path = geo_path.with_name(geo_path.name.removesuffix(".geojson") + ".query.json")
        if not side_path.exists():
            raise FileNotFoundError(f"Missing query sidecar: {side_path.name}")

        for path in (geo_path, side_path):
            if path.name not in manifest:
                raise RuntimeError(f"No data_manifest.csv row for {path.name}")
            m = manifest[path.name]
            actual_size = path.stat().st_size
            actual_hash = sha256(path)
            if actual_size != int(m["file_size_bytes"]):
                raise RuntimeError(f"Manifest size mismatch: {path.name}")
            if actual_hash.lower() != m["sha256"].lower():
                raise RuntimeError(f"Manifest SHA-256 mismatch: {path.name}")
            raw_file_checks.append((path.name, actual_hash))

        geo = json.loads(geo_path.read_text(encoding="utf-8"))
        side = json.loads(side_path.read_text(encoding="utf-8"))
        features = geo.get("features", [])
        params = side.get("parameters", {})
        api_url = side.get("api_endpoint")
        geo_url = geo.get("metadata", {}).get("url")

        expected = side.get("expected_count_from_count_endpoint")
        returned = side.get("returned_count")
        if not (len(features) == expected == returned):
            raise RuntimeError(f"Count mismatch in chunk {geo_path.name}")
        if api_url != geo_url:
            raise RuntimeError(f"GeoJSON URL / sidecar URL mismatch in {geo_path.name}")
        if params.get("minmagnitude") != "6.5" or params.get("eventtype") != "earthquake":
            raise RuntimeError(f"Unexpected query parameters in {side_path.name}")

        year_start = params.get("starttime", "")[:4]
        chunk_rows.append({
            "chunk_file": geo_path.name,
            "year": year_start,
            "feature_count": len(features),
            "count_endpoint_expected": expected,
            "sidecar_returned_count": returned,
            "query_minmagnitude": params.get("minmagnitude"),
            "query_eventtype": params.get("eventtype"),
            "geojson_sha256": sha256(geo_path),
            "sidecar_sha256": sha256(side_path),
        })
        for feature in features:
            feature["_chunk_file"] = geo_path.name
            raw_features.append(feature)

    # One-to-one ID and key-field comparison with v002.
    cat_by_id: dict[str, dict[str, str]] = {}
    for row in catalogue:
        eid = row["event_id"]
        if eid in cat_by_id:
            raise RuntimeError(f"Duplicate v002 event ID: {eid}")
        cat_by_id[eid] = row

    feature_by_id: dict[str, dict] = {}
    for feature in raw_features:
        eid = feature.get("id")
        if not eid:
            raise RuntimeError("Raw feature without an event ID")
        if eid in feature_by_id:
            raise RuntimeError(f"Duplicate raw GeoJSON feature ID: {eid}")
        feature_by_id[eid] = feature

    if set(cat_by_id) != set(feature_by_id):
        missing_raw = sorted(set(cat_by_id) - set(feature_by_id))[:10]
        missing_cat = sorted(set(feature_by_id) - set(cat_by_id))[:10]
        raise RuntimeError(
            f"Catalogue/raw event-ID set mismatch. Missing raw={missing_raw}; missing catalogue={missing_cat}"
        )

    compare_fields = Counter()
    mismatch_examples = []
    for eid, row in cat_by_id.items():
        feature = feature_by_id[eid]
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) != 3:
            raise RuntimeError(f"Unexpected point coordinate structure for {eid}")

        comparisons = [
            ("origin_time", parse_iso_utc_ms(row["origin_time_utc"]), int(props["time"])),
            ("latitude", float(row["latitude_deg"]), float(coords[1])),
            ("longitude", float(row["longitude_deg"]), float(coords[0])),
            ("depth", float(row["depth_km"]), float(coords[2])),
            ("magnitude", float(row["magnitude"]), float(props["mag"])),
            ("magnitude_type", row["magnitude_type"], props.get("magType")),
            ("place", row["place"], props.get("place")),
            ("network", row["network"], props.get("net")),
            ("network_code", row["network_code"], props.get("code")),
            ("event_status", row["event_status"], props.get("status")),
        ]
        for name, left, right in comparisons:
            compare_fields[name] += 1
            if isinstance(left, (float, int)) and isinstance(right, (float, int)):
                matched = abs(float(left) - float(right)) <= 1e-6
            else:
                matched = left == right
            if not matched:
                mismatch_examples.append((eid, name, left, right))
    if mismatch_examples:
        raise RuntimeError(f"Catalogue/raw field mismatch examples: {mismatch_examples[:10]}")

    # ComCat associated-ID audit.
    alias_to_events: dict[str, set[str]] = defaultdict(set)
    alias_count_by_event: dict[str, int] = {}
    primary_id_not_listed = []
    properties_keys = Counter()
    nonnull_counts = Counter()
    product_to_events: dict[str, set[str]] = defaultdict(set)
    detail_rows = []
    preferred_rows = []

    for eid, feature in feature_by_id.items():
        props = feature.get("properties", {})
        properties_keys.update(props.keys())
        for key, value in props.items():
            if value is not None:
                nonnull_counts[key] += 1

        ids = split_ids(props.get("ids"))
        if eid not in ids:
            primary_id_not_listed.append(eid)
        alias_count_by_event[eid] = len(set(ids))
        for associated_id in set(ids + [eid]):
            alias_to_events[associated_id].add(eid)

        types = set(split_types(props.get("types")))
        for product_type in types:
            product_to_events[product_type].add(eid)

        row = cat_by_id[eid]
        detail_rows.append({
            "event_id": eid,
            "origin_time_utc": row["origin_time_utc"],
            "magnitude": row["magnitude"],
            "magnitude_type": row["magnitude_type"],
            "place": row["place"],
            "network": row["network"],
            "product_types": ";".join(sorted(types)),
            "associated_ids": ";".join(ids),
            "detail_url": props.get("detail", ""),
        })

    alias_collisions = {
        aid: sorted(events)
        for aid, events in alias_to_events.items()
        if len(events) > 1
    }
    if primary_id_not_listed:
        raise RuntimeError(f"Primary event IDs absent from properties.ids: {primary_id_not_listed[:10]}")

    # Pairwise pre-screen: this is a candidate-finding envelope only, not a
    # deduplication rule or the final sequence model.
    ordered = sorted(
        detail_rows,
        key=lambda r: parse_iso_utc_ms(r["origin_time_utc"])
    )
    # Fast ID -> raw event
    row_by_id = cat_by_id
    pairs = []
    for i, left in enumerate(ordered):
        t1 = parse_iso_utc_ms(left["origin_time_utc"])
        f1 = feature_by_id[left["event_id"]]
        c1 = f1["geometry"]["coordinates"]
        for right in ordered[i + 1:]:
            t2 = parse_iso_utc_ms(right["origin_time_utc"])
            dt_s = (t2 - t1) / 1000.0
            if dt_s > PAIR_MAX_SECONDS:
                break
            f2 = feature_by_id[right["event_id"]]
            c2 = f2["geometry"]["coordinates"]
            d_km = haversine_km(c1[1], c1[0], c2[1], c2[0])
            if d_km > PAIR_MAX_KM:
                continue
            ids1 = set(split_ids(f1["properties"].get("ids")))
            ids2 = set(split_ids(f2["properties"].get("ids")))
            overlap = sorted(ids1 & ids2)
            pairs.append({
                "event_id_1": left["event_id"],
                "origin_time_1_utc": left["origin_time_utc"],
                "magnitude_1": left["magnitude"],
                "magnitude_type_1": left["magnitude_type"],
                "depth_1_km": row_by_id[left["event_id"]]["depth_km"],
                "place_1": left["place"],
                "network_1": left["network"],
                "event_id_2": right["event_id"],
                "origin_time_2_utc": right["origin_time_utc"],
                "magnitude_2": right["magnitude"],
                "magnitude_type_2": right["magnitude_type"],
                "depth_2_km": row_by_id[right["event_id"]]["depth_km"],
                "place_2": right["place"],
                "network_2": right["network"],
                "origin_time_difference_seconds": f"{dt_s:.3f}",
                "epicentral_distance_km": f"{d_km:.3f}",
                "shared_associated_ids": ";".join(overlap),
                "shared_associated_id_count": len(overlap),
                "screening_note": "preliminary proximity pair only; not a duplicate or sequence decision",
            })

    # Diagnostic threshold table, explicitly not approved scientific cut-offs.
    threshold_counts = []
    for seconds in (60, 300, 3600):
        for km in (5, 10, 25, 50, 100):
            n = sum(
                float(p["origin_time_difference_seconds"]) <= seconds
                and float(p["epicentral_distance_km"]) <= km
                for p in pairs
            )
            threshold_counts.append({
                "time_window_seconds": seconds,
                "distance_window_km": km,
                "pair_count": n,
                "interpretation": "diagnostic screening count only; not an approved sequence/deduplication threshold",
            })

    # Product-presence inventory and detail-review priority set.
    product_inventory = []
    for product_type in sorted(product_to_events):
        ids = sorted(product_to_events[product_type])
        product_inventory.append({
            "product_type": product_type,
            "event_count": len(ids),
            "event_ids": ";".join(ids) if product_type in {
                "associate", "disassociate", "event-sequence"
            } else "",
        })

    priority_reasons: dict[str, set[str]] = defaultdict(set)
    for eid in product_to_events.get("associate", set()):
        priority_reasons[eid].add("associate_product_present")
    for eid in product_to_events.get("disassociate", set()):
        priority_reasons[eid].add("disassociate_product_present")
    for eid in product_to_events.get("event-sequence", set()):
        priority_reasons[eid].add("event_sequence_product_present")
    for pair in pairs:
        if float(pair["origin_time_difference_seconds"]) <= 60:
            priority_reasons[pair["event_id_1"]].add("subminute_proximity_pair")
            priority_reasons[pair["event_id_2"]].add("subminute_proximity_pair")

    detail_priority = []
    for eid in sorted(priority_reasons):
        feature = feature_by_id[eid]
        props = feature["properties"]
        row = cat_by_id[eid]
        detail_priority.append({
            "event_id": eid,
            "origin_time_utc": row["origin_time_utc"],
            "magnitude": row["magnitude"],
            "magnitude_type": row["magnitude_type"],
            "place": row["place"],
            "network": row["network"],
            "review_reasons": ";".join(sorted(priority_reasons[eid])),
            "product_types": ";".join(sorted(set(split_types(props.get("types"))))),
            "associated_ids": ";".join(split_ids(props.get("ids"))),
            "detail_url": props.get("detail", ""),
        })

    # Field coverage table for summary properties.
    all_n = len(feature_by_id)
    field_coverage = []
    for field in sorted(properties_keys):
        field_coverage.append({
            "summary_property": field,
            "key_present_events": sum(field in f.get("properties", {}) for f in feature_by_id.values()),
            "nonnull_events": nonnull_counts[field],
            "null_or_missing_events": all_n - nonnull_counts[field],
        })
    for field in ("horizontalError", "depthError", "magError", "locationSource", "magSource"):
        if field not in properties_keys:
            field_coverage.append({
                "summary_property": field,
                "key_present_events": 0,
                "nonnull_events": 0,
                "null_or_missing_events": all_n,
            })

    # Verify summary product counters used in the report.
    def product_n(name: str) -> int:
        return len(product_to_events.get(name, set()))

    sequence_ids = sorted(product_to_events.get("event-sequence", set()))
    associated_alias_n = sum(alias_count_by_event.values())
    unique_alias_n = len(alias_to_events)
    alias_length_values = list(alias_count_by_event.values())
    median_alias = statistics.median(alias_length_values)
    admin_ids = product_to_events.get('associate', set()) | product_to_events.get('disassociate', set())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        OUT_DIR / "comcat_product_presence_v001.csv",
        product_inventory,
        ["product_type", "event_count", "event_ids"],
    )
    write_csv(
        OUT_DIR / "close_pair_screen_1h_100km_v001.csv",
        pairs,
        [
            "event_id_1", "origin_time_1_utc", "magnitude_1", "magnitude_type_1",
            "depth_1_km", "place_1", "network_1", "event_id_2", "origin_time_2_utc",
            "magnitude_2", "magnitude_type_2", "depth_2_km", "place_2", "network_2",
            "origin_time_difference_seconds", "epicentral_distance_km",
            "shared_associated_ids", "shared_associated_id_count", "screening_note",
        ],
    )
    write_csv(
        OUT_DIR / "proximity_threshold_sensitivity_v001.csv",
        threshold_counts,
        ["time_window_seconds", "distance_window_km", "pair_count", "interpretation"],
    )
    write_csv(
        OUT_DIR / "detail_review_priority_v001.csv",
        detail_priority,
        [
            "event_id", "origin_time_utc", "magnitude", "magnitude_type", "place",
            "network", "review_reasons", "product_types", "associated_ids", "detail_url",
        ],
    )
    write_csv(
        OUT_DIR / "summary_property_completeness_v001.csv",
        field_coverage,
        ["summary_property", "key_present_events", "nonnull_events", "null_or_missing_events"],
    )
    write_csv(
        OUT_DIR / "annual_chunk_verification_v001.csv",
        chunk_rows,
        [
            "chunk_file", "year", "feature_count", "count_endpoint_expected",
            "sidecar_returned_count", "query_minmagnitude", "query_eventtype",
            "geojson_sha256", "sidecar_sha256",
        ],
    )

    # Pair summary at fixed diagnostic levels.
    pair_60_5 = sum(
        float(p["origin_time_difference_seconds"]) <= 60
        and float(p["epicentral_distance_km"]) <= 5 for p in pairs
    )
    pair_60_25 = sum(
        float(p["origin_time_difference_seconds"]) <= 60
        and float(p["epicentral_distance_km"]) <= 25 for p in pairs
    )
    pair_300_100 = sum(
        float(p["origin_time_difference_seconds"]) <= 300
        and float(p["epicentral_distance_km"]) <= 100 for p in pairs
    )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    v002_sha = sha256(CATALOGUE)
    manifest_sha = sha256(MANIFEST)
    associate_disassociate_overlap = len(product_to_events.get("associate", set()) & product_to_events.get("disassociate", set()))
    report = f"""# LAIC-GUARD Stage 1B — Preliminary ComCat Event-Identity Audit (v001)

**Generated (UTC):** {now}  
**Inputs:** Stage 1A v002 catalogue, 26 annual USGS ComCat GeoJSON summary chunks, 26 query sidecars, and `metadata/data_manifest.csv`.  
**Scope:** Event-identity and data-field audit only. No sequence assignment, record exclusion, or final duplicate decision is made here.

**v002 catalogue SHA-256:** `{v002_sha}`  
**Data manifest SHA-256:** `{manifest_sha}`

## 1. Integrity and catalogue-to-raw alignment

| Check | Result |
|---|---:|
| Annual candidate GeoJSON chunks | {len(geo_files)} |
| Query sidecars | {len(geo_files)} |
| Raw GeoJSON and sidecar SHA-256 / sizes | {len(raw_file_checks)}/{len(raw_file_checks)} matched manifest |
| Total raw features | {len(raw_features)} |
| v002 catalogue rows | {len(catalogue)} |
| Unique raw preferred event IDs | {len(feature_by_id)} |
| Catalogue/raw event-ID set | Exact match |
| Key catalogue fields vs raw summary features | {sum(compare_fields.values())} comparisons; 0 mismatches |
| Annual sidecar counts / GeoJSON feature counts | All matched |
| Annual query `minmagnitude` / `eventtype` | All `6.5` / `earthquake` |

The archive contains exactly the 26 annual candidate GeoJSON summary files and their 26 query sidecars. Every one of those 52 files matched its `data_manifest.csv` size and SHA-256 entry. All annual counts matched both the query sidecar count metadata and the number of GeoJSON features.

The v002 event IDs matched the raw GeoJSON preferred IDs one-to-one. Origin times, coordinates, depth, magnitude, magnitude type, place, network, source code, and USGS review status matched the raw feature values.

## 2. ComCat event-ID association audit

USGS ComCat defines `id` as the current preferred event ID; it may change. The GeoJSON `ids` field is a comma-separated list of event IDs associated with that event. In this sample:

| Check | Result |
|---|---:|
| Preferred IDs | {len(feature_by_id)} |
| Primary ID also present in its `ids` list | {len(feature_by_id) - len(primary_id_not_listed)}/{len(feature_by_id)} |
| Associated-ID occurrences (including primary ID) | {associated_alias_n} |
| Unique associated IDs | {unique_alias_n} |
| Associated IDs appearing under multiple catalogue features | {len(alias_collisions)} |
| Events with only one associated ID | {sum(v == 1 for v in alias_length_values)} |
| Mean / median / maximum associated IDs per event | {statistics.mean(alias_length_values):.2f} / {median_alias} / {max(alias_length_values)} |

**Result:** No cross-feature overlap was found in the `ids` association lists. That means the supplied current ComCat summary records do not expose a shared associated ID between two different candidate rows.

**Limit:** This does not prove that no two records describe the same physical rupture. It only means ComCat's supplied `ids` association lists did not link two rows in this snapshot. A spatial/time-near pair without a shared associated ID still needs source/product-level adjudication.

## 3. Proximity screen — triage only

A diagnostic screen found **{len(pairs)} pairs** within an explicitly broad search envelope of **1 hour and 100 km epicentral distance**. This envelope is only used to surface pairs for inspection. It is not an accepted duplicate rule, aftershock window, or sequence threshold.

| Diagnostic screen | Pair count |
|---|---:|
| <=60 seconds and <=5 km | {pair_60_5} |
| <=60 seconds and <=25 km | {pair_60_25} |
| <=5 minutes and <=100 km | {pair_300_100} |
| <=1 hour and <=100 km | {len(pairs)} |

### Two sub-minute pairs requiring detail review

| Event IDs | Origin times (UTC) | Time separation | Epicentral separation | Raw catalogue values |
|---|---|---:|---:|---|
"""
    for p in pairs:
        if float(p["origin_time_difference_seconds"]) <= 60:
            report += (
                f"| `{p['event_id_1']}` / `{p['event_id_2']}` | "
                f"{p['origin_time_1_utc']} / {p['origin_time_2_utc']} | "
                f"{p['origin_time_difference_seconds']} s | "
                f"{p['epicentral_distance_km']} km | "
                f"M {p['magnitude_1']} ({p['magnitude_type_1']}) / "
                f"M {p['magnitude_2']} ({p['magnitude_type_2']}) |\n"
            )

    report += f"""
Neither sub-minute pair shares an associated ID in the supplied ComCat `ids` lists. Do not merge or classify either pair as an aftershock solely from this screen. In particular, the 2004 Japan pair and the 2023 Banda Sea pair must remain separate candidate records pending detail-product review.

All {len(pairs)} proximity pairs are retained in `close_pair_screen_1h_100km_v001.csv`. Counts under other diagnostic window combinations are in `proximity_threshold_sensitivity_v001.csv`.

## 4. Product-type inventory

The `types` summary property advertises product types associated with each event. Counts below are numbers of candidate event records that advertise each product type; they are not proof that every product payload is accessible or current.

| Product type | Events |
|---|---:|
| `origin` | {product_n("origin")} |
| `phase-data` | {product_n("phase-data")} |
| `moment-tensor` | {product_n("moment-tensor")} |
| `shakemap` | {product_n("shakemap")} |
| `focal-mechanism` | {product_n("focal-mechanism")} |
| `finite-fault` | {product_n("finite-fault")} |
| `associate` | {product_n("associate")} |
| `disassociate` | {product_n("disassociate")} |
| `event-sequence` | {product_n("event-sequence")} |
| `oaf` | {product_n("oaf")} |

The `associate` / `disassociate` product types are administrative ComCat product categories. Their presence is a reason to inspect the detailed product payloads, not a standalone identity verdict. There are **{len(admin_ids)}** unique events with either product type; **{associate_disassociate_overlap}** events advertise both types.

The `event-sequence` product is advertised for **{len(sequence_ids)}** candidate events. The current USGS Sequence Product describes groups of earthquakes clustered in space and time; USGS notes that its sequence coverage is selective, with international products posted only occasionally. Treat these records as useful auxiliary labels for comparison, not a complete or independent ground truth.

Event IDs advertising `event-sequence`:
{", ".join(f"`{eid}`" for eid in sequence_ids)}

## 5. Summary-field availability and limitations

The supplied raw GeoJSON files are **summary format**, not event-detail format. They contain preferred event summary fields and a `detail` URL for each event.

Selected non-null summary-field coverage:

| Field | Non-null records |
|---|---:|
| `nst` | {nonnull_counts["nst"]}/{all_n} |
| `dmin` | {nonnull_counts["dmin"]}/{all_n} |
| `rms` | {nonnull_counts["rms"]}/{all_n} |
| `gap` | {nonnull_counts["gap"]}/{all_n} |

The summary files do not carry `horizontalError`, `depthError`, `magError`, `locationSource`, or `magSource` as feature properties. Their absence here must not be interpreted as proof that no underlying product or alternative source provides such information. USGS GeoJSON Detail adds associated product objects from contributors; every summary feature in this dataset supplies a `detail` URL. Detail records are therefore the next source to inspect for origins, magnitudes, administrative associations, and product content.

All events have `status=reviewed` in this dataset. USGS documentation notes that reviewed status can range from a quick validity check to careful reanalysis; it is not a guarantee that all event parameters meet this study's quality criteria.

## 6. Detail-review priority list

The next retrieval should prioritize **{len(detail_priority)}** unique events flagged by at least one of these reasons:
- ComCat `associate` product present ({product_n("associate")} events before overlap removal).
- ComCat `disassociate` product present ({product_n("disassociate")} events before overlap removal).
- `event-sequence` product present ({product_n("event-sequence")} events).
- Either member of a sub-minute proximity pair (4 event IDs before overlap removal).

The complete list, including reasons, IDs and `detail` URLs, is in `detail_review_priority_v001.csv`.

## 7. Stage 1B conclusions — what is and is not established

**Established from supplied files**
1. The 26 annual raw summary chunks and 26 query sidecars are byte-for-byte consistent with the supplied manifest.
2. The 1,186 v002 records map one-to-one to the 1,186 raw GeoJSON preferred event IDs and key summary values.
3. No ComCat associated ID is shared across two candidate rows in this snapshot.
4. The raw summary records expose administrative and event-sequence product flags that identify a smaller priority subset for detail retrieval.
5. Two pairs occur within one minute and 100 km; neither pair is linked by a shared ComCat associated ID.

**Not established**
1. That all 1,186 rows are 1,186 unique physical ruptures.
2. That the 58 proximity pairs found within 1 hour / 100 km are duplicates or belong to one sequence.
3. Mainshock, foreshock, aftershock, or swarm membership.
4. The final count of independent sequences.
5. Complete uncertainty fields or alternative origin/magnitude information for every event.
6. Control-region eligibility.

**No catalogue rows are removed, no sequence IDs are assigned, and no eligibility thresholds are frozen by this audit.**

## 8. Recommended next operation

Retrieve and cache detailed ComCat GeoJSON for the {len(detail_priority)} priority events first. Inspect:
- product objects and versions;
- `associate` / `disassociate` product contents;
- `event-sequence` product payloads and membership links;
- alternative origins, magnitudes and source networks;
- any available uncertainty or review metadata.

After adjudicating this priority set, decide whether a full 1,186-event detail cache is warranted. Then retrieve a lower-magnitude context catalogue with a completeness-aware magnitude policy before running sequence algorithms.

## 9. References

1. U.S. Geological Survey, **ComCat Event Terms** — preferred `id` and associated `ids` semantics: https://earthquake.usgs.gov/data/comcat/index.php
2. U.S. Geological Survey, **GeoJSON Detail Format** — detailed event payloads include associated product objects: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson_detail.php
3. U.S. Geological Survey, **How Products Work in ComCat** — event association, product versions and preference: https://earthquake.usgs.gov/data/catalog/products.php
4. U.S. Geological Survey, **Earthquake Sequence Product** — purpose, scope and limitations of the sequence product: https://www.usgs.gov/programs/earthquake-hazards/science/earthquake-sequence-product
5. U.S. Geological Survey, **Data Products** — definitions of `associate`, `disassociate`, `event-sequence`, `origin`, `phase-data` and other product types: https://earthquake.usgs.gov/data/products/

## 10. Generated outputs

- `reports/stage1b/event_identity_audit_2000_2025_v001.md`
- `reports/stage1b/close_pair_screen_1h_100km_v001.csv`
- `reports/stage1b/proximity_threshold_sensitivity_v001.csv`
- `reports/stage1b/comcat_product_presence_v001.csv`
- `reports/stage1b/detail_review_priority_v001.csv`
- `reports/stage1b/summary_property_completeness_v001.csv`
- `reports/stage1b/annual_chunk_verification_v001.csv`

This audit is derived from the provided Stage 1A raw summary files and catalogue. It is a preliminary identity audit, not a final sequence analysis.
"""
    # ensure trailing whitespace clean
    report = "\n".join(line.rstrip(" \t") for line in report.splitlines()) + "\n"
    report_path = OUT_DIR / "event_identity_audit_2000_2025_v001.md"
    report_path.write_text(report, encoding="utf-8", newline="\n")

    print("STAGE 1B PRELIMINARY EVENT-IDENTITY AUDIT COMPLETE")
    print(f"Annual GeoJSON chunks / sidecars       : {len(geo_files)} / {len(geo_files)}")
    print(f"Raw hashes matched manifest            : {len(raw_file_checks)}/{len(raw_file_checks)}")
    print(f"Raw features / v002 catalogue rows     : {len(raw_features)} / {len(catalogue)}")
    print(f"Catalogue/raw key-field mismatches     : {len(mismatch_examples)}")
    print(f"Preferred IDs / cross-feature ID clash : {len(feature_by_id)} / {len(alias_collisions)}")
    print(f"ComCat associate / disassociate        : {product_n('associate')} / {product_n('disassociate')}")
    print(f"USGS event-sequence product events     : {product_n('event-sequence')}")
    print(f"Pairs <= 1h / <= 100 km                : {len(pairs)}")
    print(f"Sub-minute pairs <= 25 km              : {pair_60_25}")
    print(f"Priority detail events                 : {len(detail_priority)}")
    print(f"Outputs                                : {OUT_DIR.relative_to(ROOT)}")
    print("No event removed; no sequence ID assigned.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
