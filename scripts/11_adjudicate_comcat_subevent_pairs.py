#!/usr/bin/env python3
"""Reproduce LAIC-GUARD Stage 1B.2C from Stage 1B.2B CSV ledgers."""
import csv, hashlib, json
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()
D = ROOT / "reports" / "stage1b" / "adjudication"
PAIR = D / "comcat_relationship_pair_ledger_v001.csv"
PROD = D / "comcat_relationship_product_records_v001.csv"
OUT = D / "comcat_subevent_pair_adjudication_v001.csv"
REPORT = D / "STAGE1B2C_COMCAT_SUBEVENT_PAIR_ADJUDICATION_v001.md"

def read(path):
    if not path.is_file():
        raise FileNotFoundError(f"Missing input: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def truth(v):
    return str(v or "").strip().lower() in ("true", "1", "yes")

def js(v, default):
    try:
        return json.loads(v) if v else default
    except (TypeError, json.JSONDecodeError):
        return default

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def pairkey(a, b):
    return " <-> ".join(sorted((a, b)))

def main():
    pairs, products = read(PAIR), read(PROD)

    if len(pairs) != 23 or len({r["endpoint_pair_key"] for r in pairs}) != 23:
        raise ValueError("Expected 23 unique pair-ledger rows")
    if len(products) != 608 or len({r["product_id"] for r in products}) != 608:
        raise ValueError("Expected 608 unique product records")

    by = defaultdict(list)

    for r in products:
        p = js(r.get("raw_product_properties"), {})
        a = str(p.get("eventsource", "")) + str(p.get("eventsourcecode", ""))
        b = str(p.get("othereventsource", "")) + str(p.get("othereventsourcecode", ""))

        if not a or not b or pairkey(a, b) != r["endpoint_pair_key"]:
            raise ValueError("Raw product endpoint mismatch: " + r["product_id"])

        by[(r["endpoint_pair_key"], r["product_type"])].append(r)

    assoc = [r for r in products if r["product_type"] == "associate"]
    dis = [r for r in products if r["product_type"] == "disassociate"]

    if (len(assoc), len(dis)) != (583, 25):
        raise ValueError("Unexpected associate/disassociate counts")

    if not all(
        truth(r.get("is_latest_version_for_product_identity"))
        and truth(r.get("latest_version_active_update"))
        for r in dis
    ):
        raise ValueError("Disassociate product not latest active UPDATE")

    latest = [r for r in assoc if truth(r.get("is_latest_version_for_product_identity"))]
    old = [r for r in assoc if not truth(r.get("is_latest_version_for_product_identity"))]

    if (len(latest), len(old)) != (573, 10):
        raise ValueError("Unexpected associate version counts")

    out = []

    for p in pairs:
        k = p["endpoint_pair_key"]
        d = by[(k, "disassociate")]
        a = by[(k, "associate")]

        ad = [
            r for r in d
            if truth(r.get("is_latest_version_for_product_identity"))
            and truth(r.get("latest_version_active_update"))
        ]
        aa = [
            r for r in a
            if truth(r.get("is_latest_version_for_product_identity"))
            and truth(r.get("latest_version_active_update"))
        ]

        checks = (
            (len(d), int(p["disassociate_product_occurrences_all_versions"])),
            (len(a), int(p["associate_product_occurrences_all_versions"])),
            (len(ad), int(p["current_active_disassociate_count"])),
            (len(aa), int(p["current_active_associate_count"])),
        )

        if any(x != y for x, y in checks) or not ad:
            raise ValueError("Pair/product count mismatch: " + k)

        scope = p["relationship_scope_classification"]
        shared = js(p.get("shared_retrieved_detail_ids"), [])
        fa = js(p.get("endpoint_a_retrieved_detail_ids"), [])
        fb = js(p.get("endpoint_b_retrieved_detail_ids"), [])
        mapped = js(p.get("distinct_mapped_preferred_event_id_pairs"), [])
        evidence = js(p.get("mapped_preferred_pair_product_evidence"), [])
        path = js(p.get("active_associate_alias_path"), [])
        edges = [x for x in path if x.get("edge_type") == "ACTIVE_ASSOCIATE_PRODUCT"]

        if scope == "WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR":
            cls = "SAME_DETAIL_FEATURE__DIRECT_SUBEVENT_PAIR_DISASSOCIATED"
            interpretation = (
                f"Both endpoint IDs occur in retrieved detail feature {shared}. "
                "The exact sub-event pair has active disassociate; feature co-membership "
                "does not establish physical identity."
            )
            action = "NO CHANGE to v002; do not create a second candidate row from the alias token."
            identity = "SAME DETAIL-FEATURE CO-MEMBERSHIP WITH SUB-EVENT DISASSOCIATION; PHYSICAL IDENTITY NOT ADJUDICATED"
            manual = "CLOSE PAIR INSTRUCTION; KEEP PHYSICAL/SEQUENCE QUESTION OPEN"

        elif k == "at00s53wgj <-> us7000lfxx":
            cls = "CROSS_DETAIL__DIRECT_PREFERRED_PAIR_DISASSOCIATED"
            interpretation = (
                "Both endpoints are preferred IDs. Exact pair has active associate "
                "and disassociate UPDATE products; disassociate takes precedence."
            )
            action = "NO CHANGE to v002; retain us7000lfxx; do not add at00s53wgj as a second catalogue row."
            identity = "PDL PREFERRED-ID PAIR RULE: NOT ASSOCIATED; PHYSICAL IDENTITY NOT ADJUDICATED"
            manual = "CLOSE PDL PAIR RULE; KEEP PHYSICAL/SEQUENCE QUESTION OPEN"

        elif k == "atlas20111227152156 <-> usc0007dax":
            cls = "CROSS_DETAIL__ALIAS_DISASSOCIATE_AND_PREFERRED_PAIR_ASSOCIATE"
            interpretation = (
                "Alias endpoint pair has active disassociate; mapped preferred pair "
                "usp000jcq2 <-> usc0007dax has active associate. Preserve as separate "
                "sub-event relationships."
            )
            action = "NO CHANGE to v002; keep usp000jcq2; do not add usc0007dax as an independent row on this evidence alone."
            identity = "MIXED SUB-EVENT RELATIONSHIPS; AGGREGATE/PHYSICAL IDENTITY NOT ADJUDICATED"
            manual = "CLOSE DIRECT PAIR INSTRUCTION; KEEP AGGREGATE IDENTITY OPEN"

        elif k == "ci10169070 <-> duputel201004042240a":
            cls = "CROSS_DETAIL__DIRECT_ALIAS_DISASSOCIATE_WITH_INDIRECT_ASSOCIATE_PATH"
            interpretation = (
                "Exact alias pair has active disassociate; an indirect associate path "
                "exists through atlas20100404224000; no direct product for preferred "
                "pair ci10169070 <-> ci14607652."
            )
            action = "NO CHANGE to v002; retain ci14607652; do not add ci10169070 as a candidate row."
            identity = "DIRECT SUB-EVENT PAIR HAS DISASSOCIATE INSTRUCTION; AGGREGATE/PHYSICAL IDENTITY NOT ADJUDICATED"
            manual = "CLOSE DIRECT PAIR INSTRUCTION; KEEP AGGREGATE IDENTITY OPEN"

        else:
            raise ValueError("Unrecognized pair: " + k)

        chronology = [
            {
                "type": r["product_type"],
                "product_id": r["product_id"],
                "status": r["product_status"],
                "update_time_utc": r["update_time_utc"],
                "source_detail_event_id": r["source_detail_event_id"],
                "inline_comment": r.get("inline_comment", ""),
            }
            for r in sorted(d + a, key=lambda x: x.get("update_time_utc", ""))
        ]

        out.append({
            "endpoint_pair_key": k,
            "endpoint_a": p["endpoint_a"],
            "endpoint_b": p["endpoint_b"],
            "review_classification": cls,
            "relationship_scope_classification": scope,
            "endpoint_a_retrieved_detail_ids": p["endpoint_a_retrieved_detail_ids"],
            "endpoint_b_retrieved_detail_ids": p["endpoint_b_retrieved_detail_ids"],
            "shared_retrieved_detail_ids": p["shared_retrieved_detail_ids"],
            "mapped_preferred_event_id_pairs": json.dumps(mapped),
            "all_disassociate_product_occurrences": len(d),
            "current_active_disassociate_product_occurrences": len(ad),
            "all_exact_pair_associate_product_occurrences": len(a),
            "current_active_exact_pair_associate_product_occurrences": len(aa),
            "active_disassociate_product_ids": json.dumps([r["product_id"] for r in ad]),
            "active_exact_pair_associate_product_ids": json.dumps([r["product_id"] for r in aa]),
            "pair_product_chronology_utc": json.dumps(chronology),
            "active_associate_edge_count_in_alias_path": len(edges),
            "mapped_preferred_pair_product_evidence": json.dumps(evidence),
            "subevent_pair_pdl_assessment":
                "DO NOT ASSOCIATE this exact endpoint/sub-event pair; active disassociate UPDATE exists"
                + (" and takes precedence over exact-pair associate" if aa else ""),
            "aggregate_feature_interpretation": interpretation,
            "identity_decision_boundary": identity,
            "catalogue_action": action,
            "physical_event_identity": "NOT_ADJUDICATED_FROM_COMCAT_RELATIONSHIP_PRODUCTS",
            "sequence_decision": "NOT_ASSESSED; NO sequence_id assigned",
            "manual_review_status": manual,
            "review_confidence": "HIGH for current direct product instruction; NOT a physical-identity confidence",
        })

    same = sum(r["relationship_scope_classification"] == "WITHIN_ONE_RETRIEVED_DETAIL_FEATURE_ALIAS_PAIR" for r in out)
    cross = sum(r["relationship_scope_classification"] == "CROSS_DETAIL_PAIR" for r in out)
    pathn = sum(int(r["active_associate_edge_count_in_alias_path"]) > 0 for r in out)
    exactn = sum(int(r["current_active_exact_pair_associate_product_occurrences"]) > 0 for r in out)
    dups = sum(int(r["all_disassociate_product_occurrences"]) > 1 for r in out)

    if (same, cross, pathn, exactn, dups) != (20, 3, 17, 1, 2):
        raise ValueError(f"Unexpected classification totals: {same}/{cross}, paths={pathn}, exact={exactn}, repeated={dups}")

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    table = [
        "| Endpoint pair | Scope | Active disassociate | Exact-pair active associate | Alias-path associate edges |",
        "|---|---|---:|---:|---:|",
    ]
    table += [
        f"| `{r['endpoint_pair_key']}` | `{r['relationship_scope_classification']}` | "
        f"{r['current_active_disassociate_product_occurrences']} | "
        f"{r['current_active_exact_pair_associate_product_occurrences']} | "
        f"{r['active_associate_edge_count_in_alias_path']} |"
        for r in out
    ]

    REPORT.write_text(f"""# LAIC-GUARD Stage 1B.2C — ComCat sub-event-pair adjudication

## Scope and integrity

Review-only interpretation of Stage 1B.2B product ledgers; not physical-earthquake identity, sequence assignment, or a catalogue edit.

- Pair rows / unique keys: {len(pairs)} / {len(set(r['endpoint_pair_key'] for r in pairs))}
- Product rows / unique product IDs: {len(products)} / {len(set(r['product_id'] for r in products))}
- Raw product-property endpoint checks: {len(products)}/{len(products)} matched
- Associate occurrences: 583 (573 latest; 10 superseded)
- Disassociate occurrences: 25; all latest active UPDATE versions
- Same-detail / cross-detail pairs: {same} / {cross}
- Exact endpoint pairs with active associate: {exactn}
- Pairs with active associate edges in alias paths: {pathn}
- Pairs with multiple disassociate product occurrences: {dups}

## Pair-level summary

{chr(10).join(table)}

## Interpretation and boundaries

Each of the 23 exact endpoint/sub-event pairs has a current active disassociate UPDATE. The direct instruction is not to associate that exact pair. Where an exact pair also has an active associate UPDATE, disassociate takes precedence. An associate edge elsewhere in an alias path does not cancel a direct disassociate for a different pair.

The 20 same-detail pairs are alias/sub-event pairs within one retrieved detail feature. This does not determine physical earthquake identity. The three cross-detail relationships are documented separately in the adjudication CSV. Aggregate preferred-event identity is not uniformly determined by these pairwise products. Physical identity and tectonic relationship are NOT ADJUDICATED. Sequence assignment is NOT PERFORMED. Catalogue v002 and raw data are NOT MODIFIED; no merge, split, removal, re-ID, or event addition is authorized.

## Cross-detail cases

- `at00s53wgj <-> us7000lfxx`: both endpoints are preferred IDs; exact pair has active associate and disassociate; disassociate takes precedence.
- `atlas20111227152156 <-> usc0007dax`: alias endpoint pair has active disassociate, while mapped preferred pair `usp000jcq2 <-> usc0007dax` has active associate. Retain both sub-event relationships.
- `ci10169070 <-> duputel201004042240a`: exact alias pair has active disassociate; indirect associate path through `atlas20100404224000`; no direct product found for preferred pair `ci10169070 <-> ci14607652`.

## Input SHA-256

- Pair ledger: `{digest(PAIR)}`
- Product ledger: `{digest(PROD)}`

Reproduce from repository root with `python .\\scripts\\11_adjudicate_comcat_subevent_pairs.py`.
""", encoding="utf-8")

    print("STAGE 1B.2C COMCAT SUB-EVENT-PAIR ADJUDICATION COMPLETE")
    print(f"Pair rows / unique keys                     : {len(pairs)} / {len(pairs)}")
    print(f"Product rows / unique product IDs            : {len(products)} / {len(products)}")
    print(f"Raw product-properties endpoint matches      : {len(products)}/{len(products)}")
    print(f"Disassociate occurrences / unique pairs      : {len(dis)} / {len(pairs)}")
    print(f"Current active disassociate endpoint pairs   : {sum(bool(r['current_active_disassociate_product_occurrences']) for r in out)}")
    print(f"Same-detail / cross-detail pairs              : {same} / {cross}")
    print(f"Associate occurrences: latest / superseded    : {len(latest)} / {len(old)}")
    print(f"Exact endpoint pairs with active associate   : {exactn}")
    print(f"Pairs with active associate path edge(s)     : {pathn}")
    print(f"Pairs with >1 disassociate occurrence        : {dups}")
    print("Catalogue modified                           : NO")
    print("Raw data modified                            : NO")
    print("Sequence IDs assigned                        : NO")
    print(f"CSV output                                   : {OUT}")
    print(f"Markdown report                              : {REPORT}")

if __name__ == "__main__":
    main()
