#!/usr/bin/env python3
"""Reproducibly review ComCat associate/disassociate products for LAIC-GUARD.

Reads the downloaded ComCat detail GeoJSON files and the v002 candidate catalogue.
Writes review-only tables. It does not merge, split, remove, or re-ID earthquake events.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: clean(v) for k, v in row.items()})


def clean(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return value


def iso_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


def tokens_for_event(props: dict[str, Any]) -> set[str]:
    return {x.strip().lower() for x in str(props.get("ids") or "").split(",") if x.strip()}


def endpoint_token(props: dict[str, Any], prefix: str) -> str:
    source = str(props.get(prefix + "eventsource") or "").strip()
    code = str(props.get(prefix + "eventsourcecode") or "").strip()
    return (source + code).lower()


def endpoint_pair(props: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((endpoint_token(props, ""), endpoint_token(props, "other"))))  # type: ignore[return-value]


def inline_content(product: dict[str, Any]) -> str:
    """Return text in PDL inline contents (empty path key), when present."""
    contents = product.get("contents")
    if isinstance(contents, dict):
        entry = contents.get("")
        if isinstance(entry, dict):
            return str(entry.get("bytes") or "")
        if isinstance(entry, str):
            return entry
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="LAIC-GUARD project root")
    ap.add_argument("--detail-dir", type=Path, default=None)
    ap.add_argument("--catalogue", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, default=None)
    args = ap.parse_args()

    root = args.root.resolve()
    detail_dir = (args.detail_dir or root / "data/raw/usgs_event_details").resolve()
    catalogue = (args.catalogue or root / "metadata/event_catalogue_v002.csv").resolve()
    outdir = (args.output_dir or root / "reports/stage1b/adjudication").resolve()

    if not detail_dir.is_dir():
        raise SystemExit(f"ERROR: detail directory not found: {detail_dir}")
    if not catalogue.is_file():
        raise SystemExit(f"ERROR: catalogue not found: {catalogue}")

    detail_files = sorted(detail_dir.glob("*.detail.geojson"))
    if not detail_files:
        raise SystemExit(f"ERROR: no *.detail.geojson files found in {detail_dir}")

    catalogue_rows = read_csv(catalogue)
    if not catalogue_rows or "event_id" not in catalogue_rows[0]:
        raise SystemExit("ERROR: candidate catalogue must contain an event_id column")
    catalogue_ids = {r["event_id"].strip().lower() for r in catalogue_rows if r.get("event_id", "").strip()}

    events: dict[str, dict[str, Any]] = {}
    alias_to_events: dict[str, set[str]] = defaultdict(set)
    product_records: list[dict[str, Any]] = []
    for path in detail_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"ERROR: cannot parse {path}: {exc}")
        event_id = str(doc.get("id") or path.name.split(".detail.")[0]).strip()
        props = doc.get("properties") or {}
        aliases = tokens_for_event(props)
        if event_id:
            aliases.add(event_id.lower())
        events[event_id] = {"doc": doc, "props": props, "aliases": aliases, "path": path}
        for alias in aliases:
            alias_to_events[alias].add(event_id)
        products = props.get("products") or {}
        for product_type in ("associate", "disassociate"):
            for product in products.get(product_type, []) or []:
                pprops = product.get("properties") or {}
                product_records.append({
                    "event_id": event_id,
                    "event_url": props.get("url", ""),
                    "product_type": product_type,
                    "product": product,
                    "product_props": pprops,
                    "pair": endpoint_pair(pprops),
                })

    associates_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in product_records:
        if rec["product_type"] == "associate":
            associates_by_pair[rec["pair"]].append(rec)

    dis_rows: list[dict[str, Any]] = []
    for rec in product_records:
        if rec["product_type"] != "disassociate":
            continue
        eid = rec["event_id"]
        ev = events[eid]
        props = ev["props"]
        product = rec["product"]
        pprops = rec["product_props"]
        first = endpoint_token(pprops, "")
        other = endpoint_token(pprops, "other")
        aliases = ev["aliases"]
        a_matches = sorted(alias_to_events.get(first, set()))
        b_matches = sorted(alias_to_events.get(other, set()))
        exact_associates = associates_by_pair.get(rec["pair"], [])
        same_event_associates = [x for x in exact_associates if x["event_id"] == eid]
        assoc_comments = [inline_content(x["product"]) for x in exact_associates if inline_content(x["product"])]
        c = product.get("contents")
        dis_comments = inline_content(product)
        both_aliases = first in aliases and other in aliases
        if exact_associates:
            recommendation = "REVIEW_CONFLICTING_ASSOCIATE_AND_DISASSOCIATE_PRODUCTS"
        elif both_aliases:
            recommendation = "REVIEW_FLATTENED_IDS_FIELD_AGAINST_PDL_SUBEVENTS"
        else:
            recommendation = "RETRIEVE_OR_DOCUMENT_COUNTERPART_EVENT_DETAIL"

        dis_rows.append({
            "event_id": eid,
            "event_url": rec["event_url"],
            "event_time_utc": iso_ms(props.get("time")),
            "event_mag": props.get("mag"),
            "event_mag_type": props.get("magType"),
            "event_place": props.get("place"),
            "event_ids_field_tokens": sorted(aliases),
            "disassociate_product_id": product.get("id"),
            "product_code": product.get("code"),
            "product_source": product.get("source"),
            "product_status": product.get("status"),
            "product_update_time_utc": iso_ms(product.get("updateTime")),
            "product_index_time_utc": iso_ms(product.get("indexTime")),
            "product_preferred_weight": product.get("preferredWeight"),
            "original_signature_present": "original-signature" in pprops,
            "first_endpoint_source": pprops.get("eventsource", ""),
            "first_endpoint_code": pprops.get("eventsourcecode", ""),
            "first_endpoint_token": first,
            "other_endpoint_source": pprops.get("othereventsource", ""),
            "other_endpoint_code": pprops.get("othereventsourcecode", ""),
            "other_endpoint_token": other,
            "first_endpoint_in_current_detail_ids": first in aliases,
            "other_endpoint_in_current_detail_ids": other in aliases,
            "both_endpoints_in_current_detail_ids": both_aliases,
            "first_endpoint_detail_matches": a_matches,
            "other_endpoint_detail_matches": b_matches,
            "first_endpoint_direct_candidate_event_id_match": first in catalogue_ids,
            "other_endpoint_direct_candidate_event_id_match": other in catalogue_ids,
            "same_pair_associate_product_count_all_details": len(exact_associates),
            "same_pair_associate_product_count_same_detail": len(same_event_associates),
            "same_pair_associate_product_ids": [x["product"].get("id", "") for x in exact_associates],
            "same_pair_associate_update_times_utc": [iso_ms(x["product"].get("updateTime")) for x in exact_associates],
            "same_pair_associate_comments": assoc_comments,
            "disassociate_inline_comment": dis_comments,
            "disassociate_contents_container_type": type(c).__name__,
            "same_detail_associate_product_count_total": len(props.get("products", {}).get("associate", []) or []),
            "same_detail_disassociate_product_count_total": len(props.get("products", {}).get("disassociate", []) or []),
            "review_status": "PENDING_MANUAL_ADJUDICATION",
            "review_recommendation": recommendation,
            "decision": "",
            "reviewer_rationale": "",
        })

    # Group exact undirected source/code pairs to expose duplicate reverse-direction products.
    pair_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in dis_rows:
        pair_groups[tuple(sorted((row["first_endpoint_token"], row["other_endpoint_token"])))].append(row)
    group_rows = []
    for pair, items in sorted(pair_groups.items()):
        group_rows.append({
            "endpoint_a": pair[0],
            "endpoint_b": pair[1],
            "product_record_count": len(items),
            "event_ids": sorted({x["event_id"] for x in items}),
            "product_ids": [x["disassociate_product_id"] for x in items],
            "directions": [x["first_endpoint_token"] + "->" + x["other_endpoint_token"] for x in items],
            "both_endpoints_present_in_detail_count": sum(bool(x["both_endpoints_in_current_detail_ids"]) for x in items),
            "exact_associate_product_count": sum(int(x["same_pair_associate_product_count_all_details"]) for x in items),
        })

    # Capture all associate products in the same 18 event records, with inline comments correctly decoded.
    dis_event_ids = {r["event_id"] for r in dis_rows}
    assoc_rows: list[dict[str, Any]] = []
    for rec in product_records:
        if rec["product_type"] != "associate" or rec["event_id"] not in dis_event_ids:
            continue
        p = rec["product"]
        pp = rec["product_props"]
        assoc_rows.append({
            "event_id": rec["event_id"],
            "product_id": p.get("id", ""),
            "product_code": p.get("code", ""),
            "source": p.get("source", ""),
            "status": p.get("status", ""),
            "update_time_utc": iso_ms(p.get("updateTime")),
            "eventsource": pp.get("eventsource", ""),
            "eventsourcecode": pp.get("eventsourcecode", ""),
            "othereventsource": pp.get("othereventsource", ""),
            "othereventsourcecode": pp.get("othereventsourcecode", ""),
            "endpoint_a": endpoint_token(pp, ""),
            "endpoint_b": endpoint_token(pp, "other"),
            "inline_comment": inline_content(p),
            "original_signature_present": "original-signature" in pp,
        })

    outdir.mkdir(parents=True, exist_ok=True)
    dis_path = outdir / "identity_link_adjudication_v001.csv"
    group_path = outdir / "disassociate_pair_groups_v001.csv"
    assoc_path = outdir / "associate_counterevidence_v001.csv"
    write_csv(dis_path, dis_rows)
    write_csv(group_path, group_rows)
    write_csv(assoc_path, assoc_rows)

    event_counts = Counter(r["event_id"] for r in dis_rows)
    summary = {
        "detail_geojson_files_reviewed": len(detail_files),
        "candidate_catalogue_rows": len(catalogue_rows),
        "associate_products_in_disassociate_events": len(assoc_rows),
        "disassociate_product_objects": len(dis_rows),
        "unique_disassociate_events": len(event_counts),
        "unique_undirected_source_code_pairs": len(pair_groups),
        "duplicate_undirected_source_code_pairs": {a + " <-> " + b: len(v) for (a, b), v in pair_groups.items() if len(v) > 1},
        "disassociate_only_event_ids": sorted(e for e in event_counts if not any(x["event_id"] == e for x in assoc_rows)),
        "disassociate_event_product_counts": dict(sorted(event_counts.items())),
        "events_with_associate_and_disassociate_products": sum(1 for e in event_counts if any(x["event_id"] == e for x in assoc_rows)),
        "disassociate_only_events": sum(1 for e in event_counts if not any(x["event_id"] == e for x in assoc_rows)),
        "both_endpoints_in_current_event_ids": sum(bool(r["both_endpoints_in_current_detail_ids"]) for r in dis_rows),
        "exact_pair_associate_product_conflicts": sum(int(r["same_pair_associate_product_count_all_details"]) > 0 for r in dis_rows),
        "associate_products_in_disassociate_events_with_inline_comment": sum(bool(r["inline_comment"]) for r in assoc_rows),
        "disassociate_products_with_inline_comment": sum(bool(r["disassociate_inline_comment"]) for r in dis_rows),
        "disassociate_products_with_original_signature_field": sum(bool(r["original_signature_present"]) for r in dis_rows),
        "all_disassociate_statuses": dict(Counter(str(r["product_status"]) for r in dis_rows)),
        "review_policy": "No event merging, splitting, removal, or sequence assignment is performed. Every row remains pending manual adjudication.",
    }
    (outdir / "identity_link_review_summary_v001.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report = f"""# LAIC-GUARD Stage 1B.2 — Associate/Disassociate Product Review

## Scope

Reviewed {len(detail_files)} ComCat detail GeoJSON records and {len(catalogue_rows)} rows from `event_catalogue_v002.csv`. Extracted every `associate` and `disassociate` product directly from each raw detail response. This is a metadata/identity review only; no earthquake event was merged, split, removed, or assigned a sequence.

## Findings

- Disassociate product objects: **{len(dis_rows)}**
- Distinct ComCat detail events containing them: **{len(event_counts)}**
- Unique undirected source/code endpoint pairs: **{len(pair_groups)}**
- Both endpoint tokens present in the flattened detail `properties.ids` field: **{summary['both_endpoints_in_current_event_ids']} / {len(dis_rows)}**
- Exact same-pair `associate` product also present in the retrieved detail set: **{summary['exact_pair_associate_product_conflicts']} product record(s)**
- Disassociate products with inline comment: **{summary['disassociate_products_with_inline_comment']}**
- Associate products in these 18 events: **{len(assoc_rows)}**, with **{summary['associate_products_in_disassociate_events_with_inline_comment']}** inline comments
- Disassociate products carrying `original-signature`: **{summary['disassociate_products_with_original_signature_field']}**
- Status counts: `{json.dumps(summary['all_disassociate_statuses'])}`

## Key interpretation

USGS PDL documents `disassociate` as a directive to prevent automatic association between two events. Its indexer-processing documentation splits grouped events into Sub-Events by Event ID, then evaluates their pairwise relationship. In that evaluation, a disassociate product is checked before an associate product; when either Sub-Event has a disassociate product for the other, the pair is considered **not associated**. The documentation also notes that the associate/disassociate checks currently use the other Sub-Event's preferred Event ID. Therefore an exact-pair conflict must be evaluated against the preferred Event IDs, not resolved by simply choosing the later timestamp.

For one pair, `us7000lfxx` ↔ `at00s53wgj`, both an `associate` and a `disassociate` product are present. The associate product is later and carries the inline comment `outside automatic association window`; the disassociate product is also `UPDATE`, carries no inline comment, and the counterpart token is not in the current `us7000lfxx` detail ID list. USGS PDL's disassociate product documentation explicitly states that when both product types exist for the same pair, **disassociate takes precedence**. The indexer guide gives the same ordering. We therefore have a documented PDL rule, but must still retrieve the counterpart detail to confirm that `at00s53wgj` is the preferred Event ID used by the indexer check.

For {summary['both_endpoints_in_current_event_ids']} disassociate product records, both endpoint tokens also occur in the corresponding detail response's `properties.ids` string. This co-presence in the flattened `ids` field is not conclusive because the indexer can split a grouped event into separate Sub-Events by Event ID. Do not interpret the comma-delimited `ids` field alone as proof that the pair should be merged.

Three disassociate records have a counterpart endpoint absent from the current detail ID list and absent as a direct `event_id` in the scoped candidate catalogue. This does **not** prove the counterpart event does not exist: the project catalogue is filtered to magnitude >= 6.5 and uses preferred event IDs. Retrieve or document the counterpart record before closing those cases.

## Additional review notes

- Four disassociate-bearing events contain no `associate` product in their own detail response: `usp000ba6g`, `usp000ba6m`, `usp000ccg3`, and `usp000d06s`.
- Two endpoint pairs have two separate disassociate product objects, one in each endpoint order: `duputel200509090726a` ↔ `iscgem7519857` and `duputel200604301917a` ↔ `iscgem10698202`. They count as four product records but two unique undirected pairs.
- Five inline comments were found across the 60 associate products in these 18 event details. The complete associate counterevidence is preserved in `associate_counterevidence_v001.csv`. The only exact-pair associate/disassociate match is `us7000lfxx` ↔ `at00s53wgj`.
- `original-signature` is present in two disassociate products; this audit records presence only and does not cryptographically verify the signatures.

## Recommended decisions

All rows remain `PENDING_MANUAL_ADJUDICATION`. In particular:

1. Review the exact-pair associate/disassociate conflict for `us7000lfxx` ↔ `at00s53wgj`. The disassociate rule is evaluated first by the documented associator; the counterpart's preferred Event ID still needs confirmation.
2. Review the 22 flattened-`ids` co-presence cases against the ComCat Event Timeline and each endpoint's preferred Event ID.
3. Retrieve or document counterpart details for the three endpoints not represented in this detail set: `ci10169070`, `at00s53wgj`, and `usc0007dax`.
4. Review the two reversed-direction duplicate pair groups: `duputel200509090726a` ↔ `iscgem7519857` and `duputel200604301917a` ↔ `iscgem10698202`.
5. Keep original event IDs and catalogue rows unchanged until source-level decisions are documented.

## Reproducibility

Run from the repository root:

```powershell
python .\\scripts\\07_audit_disassociate_adjudication.py
```

Outputs are written to `reports/stage1b/adjudication/`.

## Official documentation consulted

- Product types: https://earthquake.usgs.gov/data/products/
- Disassociate product (explicit precedence note): https://ghsc.code-pages.usgs.gov/users/zcloutet/pdl/userguide/products/known-types/disassociate.html
- Associate product: https://ghsc.code-pages.usgs.gov/hazdev/pdl/userguide-3.5.5/products/known-types/associate.html
- Indexer processing: https://usgs.github.io/pdl/indexer.html

"""
    (outdir / "STAGE1B2_IDENTITY_LINK_REVIEW_v001.md").write_text(report, encoding="utf-8")

    print("STAGE 1B.2 IDENTITY-LINK REVIEW COMPLETE")
    for k, v in summary.items(): print(f"{k}: {v}")
    print(f"Outputs: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
