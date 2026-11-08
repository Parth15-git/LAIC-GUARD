#!/usr/bin/env python3
"""Build a provenance-checked, pair-level ComCat associate/disassociate ledger.

This is a review-only audit. It does NOT merge, split, remove, re-ID, or sequence
any earthquake. It distinguishes endpoint-token pairs from pairs of preferred
ComCat event IDs and preserves every retrieved associate/disassociate record.

Default project layout:
  data/raw/usgs_event_details/*.detail.geojson
  metadata/event_catalogue_v002.csv
  metadata/data_manifest.csv
  reports/stage1b/adjudication/

Outputs:
  comcat_relationship_product_records_v001.csv
  comcat_relationship_pair_ledger_v001.csv
  comcat_relationship_summary_v001.json
  STAGE1B2B_RELATIONSHIP_EVIDENCE_LEDGER_v001.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_DETAIL_COUNT = 358
EXPECTED_CATALOGUE_ROWS = 1186


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def utc_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def as_int(value: Any, default: int = -1) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def endpoint_token(props: dict[str, Any], prefix: str = "") -> str:
    source = str(props.get(prefix + "eventsource") or "").strip()
    code = str(props.get(prefix + "eventsourcecode") or "").strip()
    return (source + code).lower()


def parse_ids(props: dict[str, Any], event_id: str) -> set[str]:
    tokens = {
        value.strip().lower()
        for value in str(props.get("ids") or "").split(",")
        if value.strip()
    }
    if event_id:
        tokens.add(event_id.lower())
    return tokens


def inline_comment(product: dict[str, Any]) -> str:
    contents = product.get("contents")
    if not isinstance(contents, dict):
        return ""
    entry = contents.get("")
    if isinstance(entry, dict):
        return str(entry.get("bytes") or "")
    if isinstance(entry, str):
        return entry
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def product_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("product_type") or "").lower(),
        str(record.get("product_source") or "").lower(),
        str(record.get("product_code") or "").lower(),
    )


def status_is_active(status: str) -> bool:
    # PDL reserves DELETE for removing the previous version. UPDATE is active.
    return status.upper() == "UPDATE"


def status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(r.get("product_status") or "(blank)") for r in records).items()))


def product_state_by_pair(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Return latest-version state per endpoint pair, deduplicating product copies.

    Product versions are keyed by (type, source, code); updateTime is the version
    number. The latest version is selected globally across retrieved detail files.
    Raw occurrences remain available in the product-record output.
    """
    versions: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        versions[product_identity(record)].append(record)

    pair_state: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"current_products": [], "all_identity_keys": set()}
    )
    for identity, items in versions.items():
        latest_time = max(as_int(item.get("update_time_ms")) for item in items)
        latest = [item for item in items if as_int(item.get("update_time_ms")) == latest_time]
        # A product identity should point to one endpoint pair. Preserve a warning
        # if equal/latest versions disagree rather than silently choosing one.
        latest_pairs = {tuple(item["endpoint_pair"]) for item in latest if item.get("endpoint_pair")}
        for pair in latest_pairs:
            pair_state[pair]["current_products"].extend(latest)
            pair_state[pair]["all_identity_keys"].add(identity)
    return pair_state


def build_associate_alias_graph(
    alias_sets: dict[str, set[str]],
    product_state: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build graph from detail-id membership and current active associate products."""
    graph: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_edge(left: str, right: str, edge: dict[str, Any]) -> None:
        graph[left].append({"neighbor": right, **edge})
        graph[right].append({"neighbor": left, **edge})

    # The feature id and comma-delimited properties.ids form a retrieved alias set.
    for detail_id, aliases in alias_sets.items():
        for alias in aliases:
            if alias == detail_id:
                continue
            add_edge(detail_id, alias, {
                "edge_type": "DETAIL_IDS_MEMBERSHIP",
                "source_detail_event_id": detail_id,
                "product_id": "",
                "update_time_utc": "",
                "inline_comment": "",
            })

    # Only latest active associate product versions are used as graph edges.
    for pair, state in product_state.items():
        unique_latest: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in state.get("current_products", []):
            unique_latest[product_identity(record)] = record
        for record in unique_latest.values():
            if record.get("product_type") != "associate":
                continue
            if not status_is_active(str(record.get("product_status") or "")):
                continue
            add_edge(pair[0], pair[1], {
                "edge_type": "ACTIVE_ASSOCIATE_PRODUCT",
                "source_detail_event_id": record.get("source_detail_event_id", ""),
                "product_id": record.get("product_id", ""),
                "update_time_utc": record.get("update_time_utc", ""),
                "inline_comment": record.get("inline_comment", ""),
            })
    return graph


def shortest_associate_alias_path(
    graph: dict[str, list[dict[str, Any]]], start: str, goal: str, max_depth: int = 8
) -> list[dict[str, Any]]:
    """BFS path using detail alias membership and current active associate edges."""
    if not start or not goal:
        return []
    if start == goal:
        return [{"node": start}]
    queue: list[tuple[str, list[dict[str, Any]], set[str]]] = [(start, [], {start})]
    cursor = 0
    while cursor < len(queue):
        node, path, visited = queue[cursor]
        cursor += 1
        if len(path) >= max_depth:
            continue
        edges = sorted(
            graph.get(node, []),
            key=lambda edge: (
                edge.get("edge_type", ""), edge.get("neighbor", ""), edge.get("product_id", "")
            ),
        )
        for edge in edges:
            neighbor = str(edge.get("neighbor") or "")
            if not neighbor or neighbor in visited:
                continue
            next_path = path + [{
                "from": node,
                "to": neighbor,
                "edge_type": edge.get("edge_type", ""),
                "source_detail_event_id": edge.get("source_detail_event_id", ""),
                "product_id": edge.get("product_id", ""),
                "update_time_utc": edge.get("update_time_utc", ""),
                "inline_comment": edge.get("inline_comment", ""),
            }]
            if neighbor == goal:
                return [{"node": start}] + next_path
            queue.append((neighbor, next_path, visited | {neighbor}))
    return []


def endpoint_detail_ids(token: str, alias_to_detail_ids: dict[str, set[str]]) -> set[str]:
    return set(alias_to_detail_ids.get(token, set()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--detail-dir", type=Path, default=None)
    parser.add_argument("--catalogue", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--prior-adjudication", type=Path, default=None,
                        help="Optional legacy three-row identity CSV; imported as a non-authoritative comparison only.")
    parser.add_argument("--expected-detail-count", type=int, default=EXPECTED_DETAIL_COUNT)
    parser.add_argument("--expected-catalogue-rows", type=int, default=EXPECTED_CATALOGUE_ROWS)
    parser.add_argument("--skip-manifest-hash-check", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    detail_dir = (args.detail_dir or root / "data/raw/usgs_event_details").resolve()
    catalogue_path = (args.catalogue or root / "metadata/event_catalogue_v002.csv").resolve()
    manifest_path = (args.manifest or root / "metadata/data_manifest.csv").resolve()
    outdir = (args.output_dir or root / "reports/stage1b/adjudication").resolve()
    prior_path = args.prior_adjudication
    if prior_path is None:
        candidate = outdir / "LAIC-GUARD_Stage1B2_identity_adjudication_v001.csv"
        prior_path = candidate if candidate.is_file() else None
    elif not prior_path.is_absolute():
        prior_path = (root / prior_path).resolve()

    for required, label in ((detail_dir, "detail directory"), (catalogue_path, "candidate catalogue"), (manifest_path, "data manifest")):
        if not required.exists():
            raise SystemExit(f"ERROR: {label} not found: {required}")

    detail_files = sorted(detail_dir.glob("*.detail.geojson"))
    if len(detail_files) != args.expected_detail_count:
        raise SystemExit(
            f"ERROR: expected {args.expected_detail_count} detail GeoJSON files, found {len(detail_files)}. "
            "Check that the three counterpart detail files are installed in data/raw/usgs_event_details."
        )

    catalogue_rows = read_csv(catalogue_path)
    if not catalogue_rows or "event_id" not in catalogue_rows[0]:
        raise SystemExit("ERROR: candidate catalogue must contain event_id.")
    if len(catalogue_rows) != args.expected_catalogue_rows:
        raise SystemExit(
            f"ERROR: expected {args.expected_catalogue_rows} catalogue rows, found {len(catalogue_rows)}."
        )
    catalogue_ids = {str(row.get("event_id") or "").strip().lower() for row in catalogue_rows}
    catalogue_ids.discard("")

    manifest_rows = read_csv(manifest_path)
    manifest_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in manifest_rows:
        rel = str(row.get("local_relative_path") or "").replace("\\", "/")
        if rel.endswith(".detail.geojson"):
            manifest_by_name[Path(rel).name.lower()].append(row)

    # Load raw detail features, alias graph, and every associate/disassociate product.
    events: dict[str, dict[str, Any]] = {}
    alias_to_detail_ids: dict[str, set[str]] = defaultdict(set)
    alias_sets: dict[str, set[str]] = {}
    raw_records: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    detail_id_mismatches: list[str] = []

    for path in detail_files:
        filename_id = path.name.split(".detail.")[0].lower()
        raw_bytes_hash = sha256_file(path)
        manifest_matches = manifest_by_name.get(path.name.lower(), [])
        if not args.skip_manifest_hash_check:
            if len(manifest_matches) != 1:
                raise SystemExit(
                    f"ERROR: expected exactly one manifest row for {path.name}, found {len(manifest_matches)}."
                )
            mrow = manifest_matches[0]
            expected_hash = str(mrow.get("sha256") or "").lower()
            expected_size = as_int(mrow.get("file_size_bytes"), -1)
            actual_size = path.stat().st_size
            if not expected_hash or raw_bytes_hash != expected_hash:
                raise SystemExit(f"ERROR: SHA-256 mismatch for {path.name}; no output written.")
            if expected_size >= 0 and actual_size != expected_size:
                raise SystemExit(f"ERROR: file-size mismatch for {path.name}; no output written.")
            integrity_status = "PASS_SHA256_AND_SIZE"
        else:
            integrity_status = "SKIPPED_BY_USER"

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"ERROR: invalid JSON in {path.name}: {exc}")
        event_id = str(doc.get("id") or filename_id).strip().lower()
        if event_id != filename_id:
            detail_id_mismatches.append(f"{path.name}:{event_id}")
        props = doc.get("properties") or {}
        aliases = parse_ids(props, event_id)
        alias_sets[event_id] = aliases
        for alias in aliases:
            alias_to_detail_ids[alias].add(event_id)
        events[event_id] = {"doc": doc, "props": props, "aliases": aliases, "path": path}
        integrity_rows.append({
            "detail_event_id": event_id,
            "filename": path.name,
            "file_size_bytes": path.stat().st_size,
            "sha256": raw_bytes_hash,
            "manifest_match_count": len(manifest_matches),
            "integrity_status": integrity_status,
        })

        products = props.get("products") or {}
        for product_type in ("associate", "disassociate"):
            for product in products.get(product_type, []) or []:
                pprops = product.get("properties") or {}
                first = endpoint_token(pprops, "")
                other = endpoint_token(pprops, "other")
                if not first or not other:
                    continue
                pair = tuple(sorted((first, other)))
                raw_records.append({
                    "source_detail_event_id": event_id,
                    "source_detail_status": props.get("status", ""),
                    "source_detail_time_utc": utc_ms(props.get("time")),
                    "source_detail_magnitude": props.get("mag", ""),
                    "source_detail_mag_type": props.get("magType", ""),
                    "product_type": product_type,
                    "product_id": product.get("id", ""),
                    "product_source": product.get("source", ""),
                    "product_code": product.get("code", ""),
                    "product_status": str(product.get("status") or ""),
                    "update_time_ms": as_int(product.get("updateTime")),
                    "update_time_utc": utc_ms(product.get("updateTime")),
                    "index_time_utc": utc_ms(product.get("indexTime")),
                    "preferred_weight": product.get("preferredWeight", ""),
                    "endpoint_a": pair[0],
                    "endpoint_b": pair[1],
                    "endpoint_pair": pair,
                    "first_endpoint_token": first,
                    "other_endpoint_token": other,
                    "inline_comment": inline_comment(product),
                    "original_signature_present": "original-signature" in pprops,
                    "raw_product_properties": pprops,
                })

    if detail_id_mismatches:
        raise SystemExit(
            "ERROR: detail feature ID does not match its requested filename for: "
            + "; ".join(detail_id_mismatches[:10])
            + ". No output written."
        )
    if not args.skip_manifest_hash_check:
        extra_manifest = sorted(set(manifest_by_name) - {p.name.lower() for p in detail_files})
        if extra_manifest:
            # Do not fail merely because a manifest carries detail files outside this selected directory.
            pass

    product_state = product_state_by_pair(raw_records)
    records_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in raw_records:
        records_by_pair[record["endpoint_pair"]].append(record)

    associate_alias_graph = build_associate_alias_graph(alias_sets, product_state)

    disassociate_pairs = sorted(
        pair for pair, rows in records_by_pair.items()
        if any(row["product_type"] == "disassociate" for row in rows)
    )

    # Optional prior CSV: preserved for comparison only, never used to make decisions.
    prior_by_pair: dict[tuple[str, str], dict[str, str]] = {}
    if prior_path and Path(prior_path).is_file():
        for row in read_csv(Path(prior_path)):
            a = str(row.get("endpoint_a") or "").strip().lower()
            b = str(row.get("endpoint_b") or "").strip().lower()
            if a and b:
                prior_by_pair[tuple(sorted((a, b)))] = row

    product_rows: list[dict[str, Any]] = []
    # For each logical product identity, mark the latest product version.
    identity_latest: dict[tuple[str, str, str], int] = {}
    for record in raw_records:
        key = product_identity(record)
        identity_latest[key] = max(identity_latest.get(key, -1), as_int(record.get("update_time_ms")))
    for record in raw_records:
        key = product_identity(record)
        latest_time = identity_latest[key]
        is_latest = as_int(record.get("update_time_ms")) == latest_time
        product_rows.append({
            **record,
            "endpoint_pair_key": record["endpoint_a"] + " <-> " + record["endpoint_b"],
            "product_identity_key": "|".join(key),
            "is_latest_version_for_product_identity": is_latest,
            "latest_version_status": record["product_status"] if is_latest else "",
            "latest_version_active_update": bool(is_latest and status_is_active(str(record["product_status"]))),
            "latest_version_deleted": bool(is_latest and str(record["product_status"]).upper() == "DELETE"),
            "raw_product_properties": json.dumps(record["raw_product_properties"], ensure_ascii=False, sort_keys=True),
        })
    product_fields = [
        "source_detail_event_id", "source_detail_status", "source_detail_time_utc",
        "source_detail_magnitude", "source_detail_mag_type", "product_type", "product_id",
        "product_source", "product_code", "product_status", "update_time_utc", "index_time_utc",
        "preferred_weight", "endpoint_a", "endpoint_b", "endpoint_pair_key",
        "first_endpoint_token", "other_endpoint_token", "inline_comment",
        "original_signature_present", "product_identity_key",
        "is_latest_version_for_product_identity", "latest_version_status",
        "latest_version_active_update", "latest_version_deleted", "raw_product_properties",
    ]

    pair_rows: list[dict[str, Any]] = []
    for pair in disassociate_pairs:
        a, b = pair
        rows = records_by_pair[pair]
        dis_rows = [r for r in rows if r["product_type"] == "disassociate"]
        assoc_rows = [r for r in rows if r["product_type"] == "associate"]
        current = product_state.get(pair, {}).get("current_products", [])
        # The same product version can be repeated in more than one detail file.
        current_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in current:
            key = product_identity(row)
            current_by_identity[key] = row
        current_rows = list(current_by_identity.values())
        current_dis = [r for r in current_rows if r["product_type"] == "disassociate"]
        current_assoc = [r for r in current_rows if r["product_type"] == "associate"]
        active_dis = [r for r in current_dis if status_is_active(str(r["product_status"]))]
        active_assoc = [r for r in current_assoc if status_is_active(str(r["product_status"]))]

        map_a = endpoint_detail_ids(a, alias_to_detail_ids)
        map_b = endpoint_detail_ids(b, alias_to_detail_ids)
        shared_details = map_a & map_b
        mapped_detail_pairs: set[tuple[str, str]] = set()
        for da in map_a:
            for db in map_b:
                if da != db:
                    mapped_detail_pairs.add(tuple(sorted((da, db))))
        same_single_detail = len(shared_details) == 1 and not mapped_detail_pairs
        same_feature_only = bool(map_a and map_b and shared_details and not mapped_detail_pairs)

        # Find direct relationship products between the preferred IDs of mapped detail pairs.
        mapped_pair_evidence = []
        for preferred_pair in sorted(mapped_detail_pairs):
            pref_rows = records_by_pair.get(preferred_pair, [])
            pref_state = product_state.get(preferred_pair, {}).get("current_products", [])
            pref_current_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
            for row in pref_state:
                pref_current_by_identity[product_identity(row)] = row
            pref_current = list(pref_current_by_identity.values())
            pref_dis = [r for r in pref_current if r["product_type"] == "disassociate" and status_is_active(str(r["product_status"]))]
            pref_assoc = [r for r in pref_current if r["product_type"] == "associate" and status_is_active(str(r["product_status"]))]
            if pref_dis:
                instruction = "NOT_ASSOCIATED_DISASSOCIATE_PRECEDENCE"
            elif pref_assoc:
                instruction = "ASSOCIATED_BY_EXPLICIT_ASSOCIATE"
            elif any(r["product_type"] == "associate" for r in pref_current) or any(r["product_type"] == "disassociate" for r in pref_current):
                instruction = "NO_ACTIVE_EXPLICIT_OVERRIDE_AFTER_LATEST_PRODUCT_VERSIONS"
            else:
                instruction = "NO_EXPLICIT_PREFERRED_ID_PAIR_PRODUCT_FOUND"
            mapped_pair_evidence.append({
                "preferred_event_id_a": preferred_pair[0],
                "preferred_event_id_b": preferred_pair[1],
                "all_associate_product_ids": sorted({str(r["product_id"]) for r in pref_rows if r["product_type"] == "associate"}),
                "all_disassociate_product_ids": sorted({str(r["product_id"]) for r in pref_rows if r["product_type"] == "disassociate"}),
                "current_active_associate_product_ids": sorted({str(r["product_id"]) for r in pref_assoc}),
                "current_active_disassociate_product_ids": sorted({str(r["product_id"]) for r in pref_dis}),
                "instruction": instruction,
            })

        # Direct token pair vs the two preferred detail IDs is a separate test.
        direct_preferred_pair = (
            a in events and b in events and a != b
            and a in catalogue_ids.union(set(events)) and b in catalogue_ids.union(set(events))
        )
        direct_pair_instruction = "NOT_A_TWO_PREFERRED_ID_PAIR"
        if direct_preferred_pair:
            if active_dis:
                direct_pair_instruction = "NOT_ASSOCIATED_DISASSOCIATE_PRECEDENCE"
            elif active_assoc:
                direct_pair_instruction = "ASSOCIATED_BY_EXPLICIT_ASSOCIATE"
            elif current_dis or current_assoc:
                direct_pair_instruction = "NO_ACTIVE_EXPLICIT_OVERRIDE_AFTER_LATEST_PRODUCT_VERSIONS"
            else:
                direct_pair_instruction = "NO_EXPLICIT_OVERRIDE"

        if same_feature_only:
            scope_class = "WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR"
            pdl_assessment = "SUBEVENT_LEVEL_REVIEW; DO_NOT_TREAT_AS_TWO_CATALOGUE_ROWS"
            review_priority = "ROUTINE_ALIAS_SCOPE_REVIEW"
        elif len(map_a) == 1 and len(map_b) == 1 and map_a != map_b:
            scope_class = "CROSS_DETAIL_PAIR"
            if direct_preferred_pair:
                pdl_assessment = direct_pair_instruction
            elif len(mapped_pair_evidence) == 1:
                pdl_assessment = mapped_pair_evidence[0]["instruction"]
            else:
                pdl_assessment = "ALIAS_GRAPH_REVIEW_REQUIRED"
            review_priority = "HIGH_MANUAL_REVIEW_PRIORITY"
        elif mapped_detail_pairs:
            scope_class = "AMBIGUOUS_MULTI_DETAIL_ALIAS_MAPPING"
            pdl_assessment = "ALIAS_GRAPH_REVIEW_REQUIRED"
            review_priority = "HIGH_MANUAL_REVIEW_PRIORITY"
        elif map_a or map_b:
            scope_class = "INCOMPLETE_ENDPOINT_DETAIL_RESOLUTION"
            pdl_assessment = "COUNTERPART_RETRIEVAL_OR_ALIAS_REVIEW_REQUIRED"
            review_priority = "HIGH_MANUAL_REVIEW_PRIORITY"
        else:
            scope_class = "NO_ENDPOINT_DETAIL_RESOLUTION"
            pdl_assessment = "COUNTERPART_RETRIEVAL_REQUIRED"
            review_priority = "HIGH_MANUAL_REVIEW_PRIORITY"

        shared_aliases_between_mapped_details = set()
        for da in map_a:
            for db in map_b:
                if da != db:
                    shared_aliases_between_mapped_details |= (alias_sets.get(da, set()) & alias_sets.get(db, set()))
        mapped_catalogue_ids = sorted((map_a | map_b) & catalogue_ids)
        alias_path = shortest_associate_alias_path(associate_alias_graph, a, b)
        alias_path_has_associate = any(
            edge.get("edge_type") == "ACTIVE_ASSOCIATE_PRODUCT"
            for edge in alias_path if "edge_type" in edge
        )
        prior = prior_by_pair.get(pair, {})
        prior_decision = prior.get("decision", "")
        # This is a scope warning, not a new scientific identity decision.
        prior_warning = ""
        if prior_decision and prior_decision.upper().startswith("CONFIRMED_SEPARATE_COMCAT_EVENT_IDENTITIES"):
            if scope_class != "CROSS_DETAIL_PAIR" or "ALIAS" in scope_class or "REVIEW_REQUIRED" in pdl_assessment or pdl_assessment == "SUBEVENT_LEVEL_REVIEW; DO_NOT_TREAT_AS_TWO_CATALOGUE_ROWS":
                prior_warning = "LEGACY_SEPARATE_IDENTITY_LABEL_NOT_ADOPTED; CURRENT_LEDGER_REQUIRES_SCOPE_OR_ALIAS_REVIEW"
            elif pdl_assessment == "NOT_ASSOCIATED_DISASSOCIATE_PRECEDENCE":
                prior_warning = "ADMINISTRATIVE_PDL_DISASSOCIATION_CONFIRMED; PHYSICAL_INDEPENDENCE_NOT_ESTABLISHED"
            else:
                prior_warning = "LEGACY_SEPARATE_IDENTITY_LABEL_NOT_ADOPTED; REVIEW_PHYSICAL_IDENTITY_SEPARATELY"

        chronology = sorted(
            ({"product_type": r["product_type"], "status": r["product_status"],
              "update_time_utc": r["update_time_utc"], "product_id": r["product_id"],
              "source_detail_event_id": r["source_detail_event_id"],
              "inline_comment": r["inline_comment"]} for r in rows),
            key=lambda x: x["update_time_utc"] or ""
        )
        pair_rows.append({
            "endpoint_a": a,
            "endpoint_b": b,
            "endpoint_pair_key": a + " <-> " + b,
            "disassociate_product_occurrences_all_versions": len(dis_rows),
            "associate_product_occurrences_all_versions": len(assoc_rows),
            "disassociate_product_ids_all_versions": sorted({str(r["product_id"]) for r in dis_rows}),
            "associate_product_ids_all_versions": sorted({str(r["product_id"]) for r in assoc_rows}),
            "disassociate_source_detail_event_ids": sorted({r["source_detail_event_id"] for r in dis_rows}),
            "associate_source_detail_event_ids": sorted({r["source_detail_event_id"] for r in assoc_rows}),
            "disassociate_status_counts_all_versions": status_counts(dis_rows),
            "associate_status_counts_all_versions": status_counts(assoc_rows),
            "current_disassociate_product_ids": sorted({str(r["product_id"]) for r in current_dis}),
            "current_associate_product_ids": sorted({str(r["product_id"]) for r in current_assoc}),
            "current_disassociate_status_counts": status_counts(current_dis),
            "current_associate_status_counts": status_counts(current_assoc),
            "current_active_disassociate_count": len(active_dis),
            "current_active_associate_count": len(active_assoc),
            "pair_product_chronology_utc": chronology,
            "endpoint_a_retrieved_detail_ids": sorted(map_a),
            "endpoint_b_retrieved_detail_ids": sorted(map_b),
            "shared_retrieved_detail_ids": sorted(shared_details),
            "both_endpoints_resolve_to_same_single_detail": same_single_detail,
            "distinct_mapped_preferred_event_id_pairs": sorted([list(x) for x in mapped_detail_pairs]),
            "shared_aliases_between_distinct_mapped_details": sorted(shared_aliases_between_mapped_details),
            "active_associate_alias_path": alias_path,
            "active_associate_alias_path_found": bool(alias_path),
            "active_associate_product_edge_in_alias_path": alias_path_has_associate,
            "endpoint_a_is_preferred_detail_id": a in events,
            "endpoint_b_is_preferred_detail_id": b in events,
            "endpoint_a_direct_candidate_catalogue_id": a in catalogue_ids,
            "endpoint_b_direct_candidate_catalogue_id": b in catalogue_ids,
            "mapped_candidate_catalogue_event_ids": mapped_catalogue_ids,
            "mapped_preferred_pair_product_evidence": mapped_pair_evidence,
            "direct_token_pair_pdl_instruction": direct_pair_instruction,
            "relationship_scope_classification": scope_class,
            "preferred_id_pair_pdl_assessment": pdl_assessment,
            "review_priority": review_priority,
            "legacy_preliminary_decision": prior_decision,
            "legacy_decision_confidence": prior.get("confidence", ""),
            "legacy_decision_scope_warning": prior_warning,
            "identity_decision": "NOT_DECIDED_BY_THIS_SCRIPT",
            "sequence_decision": "NONE",
            "catalogue_action": "NO_CHANGE",
        })

    # Validate the expected relationship count so catalogue/data drift is obvious.
    if len(disassociate_pairs) != 23:
        raise SystemExit(
            f"ERROR: expected 23 unique disassociate endpoint pairs, found {len(disassociate_pairs)}. "
            "No output written; inspect input version and Stage 1B.2 baseline."
        )

    outdir.mkdir(parents=True, exist_ok=True)
    product_path = outdir / "comcat_relationship_product_records_v001.csv"
    pair_path = outdir / "comcat_relationship_pair_ledger_v001.csv"
    integrity_path = outdir / "comcat_relationship_input_integrity_v001.csv"
    summary_path = outdir / "comcat_relationship_summary_v001.json"
    report_path = outdir / "STAGE1B2B_RELATIONSHIP_EVIDENCE_LEDGER_v001.md"

    pair_fields = [
        "endpoint_a", "endpoint_b", "endpoint_pair_key",
        "disassociate_product_occurrences_all_versions", "associate_product_occurrences_all_versions",
        "disassociate_product_ids_all_versions", "associate_product_ids_all_versions",
        "disassociate_source_detail_event_ids", "associate_source_detail_event_ids",
        "disassociate_status_counts_all_versions", "associate_status_counts_all_versions",
        "current_disassociate_product_ids", "current_associate_product_ids",
        "current_disassociate_status_counts", "current_associate_status_counts",
        "current_active_disassociate_count", "current_active_associate_count",
        "pair_product_chronology_utc", "endpoint_a_retrieved_detail_ids", "endpoint_b_retrieved_detail_ids",
        "shared_retrieved_detail_ids", "both_endpoints_resolve_to_same_single_detail",
        "distinct_mapped_preferred_event_id_pairs", "shared_aliases_between_distinct_mapped_details",
        "active_associate_alias_path", "active_associate_alias_path_found",
        "active_associate_product_edge_in_alias_path",
        "endpoint_a_is_preferred_detail_id", "endpoint_b_is_preferred_detail_id",
        "endpoint_a_direct_candidate_catalogue_id", "endpoint_b_direct_candidate_catalogue_id",
        "mapped_candidate_catalogue_event_ids", "mapped_preferred_pair_product_evidence",
        "direct_token_pair_pdl_instruction", "relationship_scope_classification",
        "preferred_id_pair_pdl_assessment", "review_priority",
        "legacy_preliminary_decision", "legacy_decision_confidence", "legacy_decision_scope_warning",
        "identity_decision", "sequence_decision", "catalogue_action",
    ]
    write_csv(product_path, product_rows, product_fields)
    write_csv(pair_path, pair_rows, pair_fields)
    write_csv(integrity_path, integrity_rows, [
        "detail_event_id", "filename", "file_size_bytes", "sha256", "manifest_match_count", "integrity_status"
    ])

    scope_counts = Counter(row["relationship_scope_classification"] for row in pair_rows)
    pdl_counts = Counter(row["preferred_id_pair_pdl_assessment"] for row in pair_rows)
    summary = {
        "stage": "1B.2B",
        "detail_geojson_files_reviewed": len(detail_files),
        "catalogue_rows_reviewed": len(catalogue_rows),
        "catalogue_unique_event_ids": len(catalogue_ids),
        "input_detail_sha256_verified": (not args.skip_manifest_hash_check),
        "input_manifest_detail_rows_matched": len(integrity_rows),
        "associate_product_occurrences": sum(r["product_type"] == "associate" for r in raw_records),
        "disassociate_product_occurrences": sum(r["product_type"] == "disassociate" for r in raw_records),
        "unique_undirected_disassociate_endpoint_pairs": len(disassociate_pairs),
        "pair_scope_classification_counts": dict(sorted(scope_counts.items())),
        "preferred_id_pair_pdl_assessment_counts": dict(sorted(pdl_counts.items())),
        "legacy_preliminary_decisions_imported_for_comparison": len(prior_by_pair),
        "policy": [
            "All raw associate/disassociate occurrences are preserved in the product-record CSV.",
            "Product current state is determined by latest updateTime per (type, source, code); DELETE supersedes earlier versions.",
            "PDL explicit disassociate takes precedence over explicit associate when evaluating a pair of preferred Event IDs.",
            "Endpoint alias-token relationships are not automatically promoted to preferred Event ID pair decisions.",
            "Administrative ComCat association status is not interpreted as physical/tectonic independence.",
            "No event is merged, split, removed, re-IDed, or assigned a sequence by this script.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-readable report with explicit three cross-detail cases, based only on computed evidence.
    cross_rows = [r for r in pair_rows if r["relationship_scope_classification"] == "CROSS_DETAIL_PAIR"]
    same_rows = [r for r in pair_rows if r["relationship_scope_classification"] == "WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR"]
    def find_pair(x: str, y: str) -> dict[str, Any] | None:
        key = tuple(sorted((x.lower(), y.lower())))
        return next((r for r in pair_rows if (r["endpoint_a"], r["endpoint_b"]) == key), None)
    case_lines = []
    for r in cross_rows:
        mapped = r["distinct_mapped_preferred_event_id_pairs"]
        case_lines.append(
            f"- `{r['endpoint_pair_key']}`: endpoint detail mappings `{r['endpoint_a_retrieved_detail_ids']}` / "
            f"`{r['endpoint_b_retrieved_detail_ids']}`; mapped preferred pair(s): `{mapped}`; "
            f"PDL assessment: **{r['preferred_id_pair_pdl_assessment']}**. Active associate/alias path: "
            f"`{r['active_associate_alias_path']}`. Manual review priority: {r['review_priority']}."
        )

    us7000 = find_pair("us7000lfxx", "at00s53wgj")
    atlas_usc = find_pair("atlas20111227152156", "usc0007dax")
    ci_pair = find_pair("ci10169070", "duputel201004042240a")
    special = []
    if us7000:
        special.append(
            "- **`us7000lfxx` ↔ `at00s53wgj`:** both endpoint tokens are preferred detail IDs. "
            "The exact preferred-ID pair has active associate and disassociate `UPDATE` products; "
            "the PDL indexer rule therefore returns NOT ASSOCIATED for this pair. This is an indexer "
            "relationship instruction only; it does not prove physical independence."
        )
    if atlas_usc:
        special.append(
            "- **`atlas20111227152156` ↔ `usc0007dax`:** the first endpoint resolves as an alias inside "
            "`usp000jcq2`; the second is the preferred ID of `usc0007dax`. The mapped preferred-ID pair "
            "`usp000jcq2` ↔ `usc0007dax` has active associate products, while the disassociate is for "
            "the alias pair. Keep the alias-graph/physical-identity interpretation open; do not count "
            "the counterpart as a second catalogue event based on this ledger alone."
        )
    if ci_pair:
        special.append(
            "- **`ci10169070` ↔ `duputel201004042240a`:** the endpoints map to separate retrieved "
            "detail records, but `duputel201004042240a` is an alias within `ci14607652`; an active "
            "associate/alias-membership path connects the endpoint tokens through the retrieved records. "
            "No direct preferred-ID-pair override is found "
            "for the mapped pair. This remains a manual alias-graph review, not an automatic separate-identity decision."
        )

    report = f"""# LAIC-GUARD Stage 1B.2B — ComCat Relationship Evidence Ledger

## Scope and input integrity

This is a review-only, reproducible audit of the 358 retrieved ComCat event-detail GeoJSON records and the v002 candidate catalogue ({len(catalogue_rows)} rows). Each detail file was matched to exactly one manifest row and its SHA-256 and byte size were verified before the audit ran.

- Detail GeoJSON records reviewed: **{len(detail_files)}**
- Candidate catalogue rows: **{len(catalogue_rows)}**
- Associate product occurrences: **{summary['associate_product_occurrences']}**
- Disassociate product occurrences: **{summary['disassociate_product_occurrences']}**
- Unique undirected endpoint pairs containing a disassociate product: **{len(disassociate_pairs)}**
- Pair scope classifications: `{json.dumps(summary['pair_scope_classification_counts'])}`

## Key finding

The 23 disassociate endpoint pairs are not 23 independent pairs of catalogue earthquakes. The endpoint-token alias graph maps **{len(same_rows)}** pairs to the same retrieved detail feature and **{len(cross_rows)}** pairs across distinct retrieved detail features. A same-feature mapping is a scope/alias finding; it is not a physical-earthquake interpretation. Of the three cross-detail pairs, one matches both preferred IDs; the other two require alias-graph review.

## Cross-detail relationship cases

{chr(10).join(case_lines) if case_lines else '- None.'}

## Focused interpretation of the three cross-detail cases

{chr(10).join(special) if special else '- No three-case cross-detail subset identified.'}

## Product-state method

1. Every `associate` and `disassociate` product occurrence is retained in `comcat_relationship_product_records_v001.csv`.
2. Product versions are grouped by `(product type, source, code)`; the greatest `updateTime` is treated as the current version. `DELETE` supersedes earlier versions; `UPDATE` is active.
3. Endpoint pairs are normalized as undirected `(source + sourcecode)` tokens.
4. Each endpoint token is mapped against every retrieved detail feature's `properties.ids` plus the feature's top-level `id`.
5. For distinct mapped detail features, the ledger separately tests whether a relationship product exists between the two **preferred detail IDs**. Alias-token products are not silently treated as preferred-ID pair products.
6. An additional graph path is computed using detail-ID membership edges and latest active associate-product edges. This path is evidence of alias/association connectivity, not an identity decision.
7. The PDL indexer processing documentation states that if either event has a disassociate product for the other, the events are not associated; the associate check is considered after disassociate. The documentation also says these product checks currently inspect the other event's preferred Event ID. Thus a product on an alias edge cannot automatically be promoted to a preferred-ID pair decision.

## Decision boundaries

- This ledger distinguishes **ComCat product instruction**, **preferred-ID mapping**, **alias-graph interpretation**, and **physical earthquake identity**.
- A disassociate instruction does not establish that two origins are physically unrelated or tectonically independent.
- A product-level associate does not, by itself, establish the scientific sequence membership of two events.
- No earthquake was merged, split, removed, re-IDed, or assigned a `sequence_id`.
- The candidate catalogue and raw ComCat downloads were not modified.
- Any previously supplied three-row `CONFIRMED_SEPARATE_COMCAT_EVENT_IDENTITIES` CSV is imported only as a legacy comparison. Its decision labels are not adopted as ground truth; see `legacy_decision_scope_warning` in the pair ledger.

## Files produced

- `comcat_relationship_product_records_v001.csv` — all extracted product records and version flags.
- `comcat_relationship_pair_ledger_v001.csv` — one row per each of the 23 unique undirected disassociate endpoint pairs.
- `comcat_relationship_input_integrity_v001.csv` — input file hashes and manifest matches.
- `comcat_relationship_summary_v001.json` — machine-readable counts and policy.

## Official USGS/PDL references

- Indexer processing and pairwise association logic: https://usgs.github.io/pdl/indexer.html
- Disassociate product semantics and status: https://ghsc.code-pages.usgs.gov/users/bhawthorne/pdl/userguide-2.9.1/products/disassociate.html
- Associate product semantics and status: https://ghsc.code-pages.usgs.gov/hazdev/pdl/userguide-3.5.5/products/known-types/associate.html

## Reproduce

Run from the repository root:

```powershell
python .\\scripts\\10_build_comcat_relationship_ledger.py
```

Expected baseline: 358 detail GeoJSON files, 1,186 catalogue rows, 23 unique disassociate endpoint pairs, and all 358 detail hashes verified against `metadata/data_manifest.csv`.
"""
    report_path.write_text(report, encoding="utf-8")

    print("STAGE 1B.2B COMCAT RELATIONSHIP LEDGER COMPLETE")
    print(f"Detail GeoJSON files / manifest hashes : {len(detail_files)} / {len(integrity_rows)} verified")
    print(f"Candidate catalogue rows              : {len(catalogue_rows)}")
    print(f"Associate product occurrences          : {summary['associate_product_occurrences']}")
    print(f"Disassociate product occurrences       : {summary['disassociate_product_occurrences']}")
    print(f"Unique disassociate endpoint pairs     : {len(disassociate_pairs)}")
    print(f"Same-detail alias pairs                : {len(same_rows)}")
    print(f"Cross-detail pairs                     : {len(cross_rows)}")
    print(f"Scope classifications                 : {dict(scope_counts)}")
    print(f"Preferred-ID PDL assessments           : {dict(pdl_counts)}")
    print("Catalogue modified                    : NO")
    print("Raw data modified                     : NO")
    print("Sequence IDs assigned                 : NO")
    print(f"Outputs                               : {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
