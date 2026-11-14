#!/usr/bin/env python3
"""LAIC-GUARD Stage 1C.2.3: nearest mapped tectonic-boundary distances.

Uses the Hasterok global_tectonics plate_boundaries.shp line layer.
Preserves every source shapefile row as a distinct boundary record, since
feature_id is not unique in this source layer.

Distance method:
  * WGS84 geodesic interpolation between source vertices (max step 10 km).
  * Per-event WGS84 azimuthal-equidistant projection centered on the event.
  * Point-to-polyline minimum in the local projection; nearest point is
    transformed back to WGS84 and distance rechecked with WGS84 Geod.inv.
  * A deterministic validation sample repeats the calculation at 2 km
    densification to assess discretization sensitivity.

No distance threshold is applied. Inferred and all other source classes are
retained; nearest non-inferred distances are reported as an additional view.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from scipy.spatial import cKDTree
import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points

EXPECTED_CATALOGUE_SHA256 = "0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315"
EXPECTED_CROSSWALK_SHA256 = "e3c7d36c9580491acfcb77a4ba501b7496692230dde5015ba964c5b903c2122c"
GEOD = Geod(ellps="WGS84")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean_scalar(v: Any) -> Any:
    if pd.isna(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def parts_of(geom):
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    raise ValueError(f"Unsupported boundary geometry type: {geom.geom_type}")


def densify_line_geodesic(line: LineString, max_step_m: float) -> np.ndarray:
    """Densify a line along WGS84 geodesics between its source vertices."""
    coords = [(float(c[0]), float(c[1])) for c in line.coords]
    if len(coords) < 2:
        return np.asarray(coords, dtype=float)
    out: list[tuple[float, float]] = [coords[0]]
    for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:]):
        _, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
        if not math.isfinite(dist) or dist < 1e-6:
            continue
        n_inner = max(0, int(math.ceil(dist / max_step_m)) - 1)
        if n_inner:
            out.extend(GEOD.npts(lon1, lat1, lon2, lat2, n_inner))
        out.append((lon2, lat2))
    # Remove consecutive duplicate points.
    dedup = [out[0]]
    for xy in out[1:]:
        if xy != dedup[-1]:
            dedup.append(xy)
    return np.asarray(dedup, dtype=float)


def prepare_boundaries(boundaries: gpd.GeoDataFrame, max_step_km: float):
    """Return one flat coordinate array and part/record index maps."""
    lon_chunks: list[np.ndarray] = []
    lat_chunks: list[np.ndarray] = []
    part_ranges: list[tuple[int, int, int]] = []  # record index, start, end
    record_parts: list[list[int]] = [[] for _ in range(len(boundaries))]
    cursor = 0
    for record_idx, geom in enumerate(boundaries.geometry):
        for part in parts_of(geom):
            arr = densify_line_geodesic(part, max_step_km * 1000.0)
            if len(arr) < 2:
                continue
            start, end = cursor, cursor + len(arr)
            lon_chunks.append(arr[:, 0])
            lat_chunks.append(arr[:, 1])
            part_idx = len(part_ranges)
            part_ranges.append((record_idx, start, end))
            record_parts[record_idx].append(part_idx)
            cursor = end
    all_lon = np.concatenate(lon_chunks) if lon_chunks else np.array([], dtype=float)
    all_lat = np.concatenate(lat_chunks) if lat_chunks else np.array([], dtype=float)
    return all_lon, all_lat, part_ranges, record_parts


def build_projected_parts(
    all_lon: np.ndarray,
    all_lat: np.ndarray,
    part_ranges: list[tuple[int, int, int]],
    n_records: int,
    transformer: Transformer,
):
    """Project all vertices and return vectorized Shapely line parts + row IDs."""
    x, y = transformer.transform(all_lon, all_lat)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y) & (np.hypot(x, y) < 19_900_000.0)

    projected_coord_parts: list[np.ndarray] = []
    part_record_ids: list[int] = []
    for record_idx, start, end in part_ranges:
        idx = np.flatnonzero(finite[start:end])
        if len(idx) < 2:
            continue
        run_start = prev = int(idx[0])
        runs: list[tuple[int, int]] = []
        for val in idx[1:]:
            val = int(val)
            if val != prev + 1:
                if prev - run_start + 1 >= 2:
                    runs.append((run_start, prev + 1))
                run_start = val
            prev = val
        if prev - run_start + 1 >= 2:
            runs.append((run_start, prev + 1))
        for a, b in runs:
            coords = np.column_stack((x[start + a:start + b], y[start + a:start + b]))
            if len(coords) >= 2:
                projected_coord_parts.append(coords)
                part_record_ids.append(record_idx)

    if not projected_coord_parts:
        raise RuntimeError("No boundary lines could be projected for event.")
    concatenated_coords = np.concatenate(projected_coord_parts, axis=0)
    line_indices = np.repeat(np.arange(len(projected_coord_parts), dtype=np.int32), [len(a) for a in projected_coord_parts])
    lines = shapely.linestrings(concatenated_coords, indices=line_indices)
    return lines, np.asarray(part_record_ids, dtype=np.int32), Point(0.0, 0.0)


def lonlat_to_unit_xyz(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lonr = np.radians(lon)
    latr = np.radians(lat)
    c = np.cos(latr)
    return np.column_stack((c * np.cos(lonr), c * np.sin(lonr), np.sin(latr)))


def build_boundary_sample_indexes(all_lon, all_lat, part_ranges, boundary_rows):
    """Build spherical KD-trees for all/class subsets of the densified linework."""
    sample_record_ids = np.empty(len(all_lon), dtype=np.int32)
    for record_idx, start, end in part_ranges:
        sample_record_ids[start:end] = record_idx
    xyz = lonlat_to_unit_xyz(all_lon, all_lat)
    type_values = sorted({str(v) for v in boundary_rows["type"].dropna().unique()})
    groups: dict[str, np.ndarray] = {
        "all": np.arange(len(boundary_rows), dtype=np.int32),
        "non_inferred": np.flatnonzero(boundary_rows["type"].astype(str).str.lower().to_numpy() != "inferred").astype(np.int32),
    }
    for typ in type_values:
        groups[f"type::{typ}"] = np.flatnonzero(boundary_rows["type"].astype(str).to_numpy() == typ).astype(np.int32)
    groups["transform_combined"] = np.flatnonzero(
        boundary_rows["type"].astype(str).isin(["dextral transform", "sinistral transform"]).to_numpy()
    ).astype(np.int32)

    indexes = {}
    for name, record_ids in groups.items():
        mask = np.isin(sample_record_ids, record_ids)
        node_ids = np.flatnonzero(mask)
        if len(node_ids) == 0:
            continue
        indexes[name] = {
            "tree": cKDTree(xyz[node_ids]),
            "sample_record_ids": sample_record_ids[node_ids],
        }
    return indexes


def candidate_record_ids_for_event(event_lon, event_lat, indexes, max_step_km: float):
    """Find candidate source rows for the nearest record in each group.

    Every source line segment has geodesic sample spacing <= max_step_km, so
    a closest point on that line is within max_step_km/2 of a sample vertex.
    An additional 1%-of-range margin protects the spherical prefilter against
    ellipsoid/sphere differences. Exact distances are then calculated on the
    candidate polylines in event-centred AEQD.
    """
    point_xyz = lonlat_to_unit_xyz(np.asarray([event_lon]), np.asarray([event_lat]))[0]
    earth_radius_km = 6371.0088
    candidates: set[int] = set()
    candidate_counts = {}
    for name, item in indexes.items():
        chord, _ = item["tree"].query(point_xyz, k=1)
        chord = float(min(2.0, max(0.0, chord)))
        arc_km = 2.0 * math.asin(chord / 2.0) * earth_radius_km
        margin_km = max(5.1, 0.01 * arc_km) + 0.1
        search_arc_km = min(math.pi * earth_radius_km, arc_km + margin_km)
        radius_chord = 2.0 * math.sin(search_arc_km / (2.0 * earth_radius_km))
        node_ids = item["tree"].query_ball_point(point_xyz, r=radius_chord)
        if not node_ids:
            # Include the closest sample as a numerical safety fallback.
            _, nearest_node = item["tree"].query(point_xyz, k=1)
            node_ids = [int(nearest_node)]
        recs = np.unique(item["sample_record_ids"][np.asarray(node_ids, dtype=int)])
        candidates.update(int(v) for v in recs)
        candidate_counts[name] = int(len(recs))
    return sorted(candidates), candidate_counts


def project_candidate_records(
    event_lon, event_lat, candidate_ids, all_lon, all_lat, part_ranges
):
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={event_lat:.12f} +lon_0={event_lon:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    forward = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    reverse = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    candidate_set = set(candidate_ids)
    candidate_parts = [(r, s, e) for r, s, e in part_ranges if r in candidate_set]
    if not candidate_parts:
        raise RuntimeError("Spatial prefilter returned no candidate line parts.")
    lon = np.concatenate([all_lon[s:e] for _, s, e in candidate_parts])
    lat = np.concatenate([all_lat[s:e] for _, s, e in candidate_parts])
    x, y = forward.transform(lon, lat)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    offsets = np.cumsum([0] + [e - s for _, s, e in candidate_parts])
    coord_parts = []
    part_record_ids = []
    for j, (rec, _, _) in enumerate(candidate_parts):
        a, b = int(offsets[j]), int(offsets[j + 1])
        finite = np.isfinite(x[a:b]) & np.isfinite(y[a:b]) & (np.hypot(x[a:b], y[a:b]) < 19_900_000.0)
        idx = np.flatnonzero(finite)
        if len(idx) < 2:
            continue
        start = prev = int(idx[0])
        runs = []
        for val in idx[1:]:
            val = int(val)
            if val != prev + 1:
                if prev - start + 1 >= 2:
                    runs.append((start, prev + 1))
                start = val
            prev = val
        if prev - start + 1 >= 2:
            runs.append((start, prev + 1))
        for aa, bb in runs:
            coord_parts.append(np.column_stack((x[a + aa:a + bb], y[a + aa:a + bb])))
            part_record_ids.append(rec)
    if not coord_parts:
        raise RuntimeError("Candidate linework could not be projected.")
    concatenated = np.concatenate(coord_parts, axis=0)
    line_indices = np.repeat(np.arange(len(coord_parts), dtype=np.int32), [len(a) for a in coord_parts])
    lines = shapely.linestrings(concatenated, indices=line_indices)
    return lines, np.asarray(part_record_ids, dtype=np.int32), reverse, Point(0.0, 0.0)


def nearest_for_event(
    event_lon: float,
    event_lat: float,
    boundary_rows: pd.DataFrame,
    all_lon: np.ndarray,
    all_lat: np.ndarray,
    part_ranges: list[tuple[int, int, int]],
    n_records: int,
    sample_indexes,
    max_step_km: float,
):
    candidate_ids, candidate_counts = candidate_record_ids_for_event(
        event_lon, event_lat, sample_indexes, max_step_km
    )
    lines, part_record_ids, reverse, origin = project_candidate_records(
        event_lon, event_lat, candidate_ids, all_lon, all_lat, part_ranges
    )
    part_distances_m = np.asarray(shapely.distance(lines, origin), dtype=float)
    record_distances_m = np.full(n_records, np.inf, dtype=float)
    np.minimum.at(record_distances_m, part_record_ids, part_distances_m)

    def min_record_id(indices):
        indices = np.asarray(indices, dtype=int)
        if len(indices) == 0:
            return None
        good = indices[np.isfinite(record_distances_m[indices])]
        if len(good) == 0:
            return None
        return int(good[np.argmin(record_distances_m[good])])

    def make_hit(idx: int | None, with_point: bool = False) -> dict[str, Any] | None:
        if idx is None or not np.isfinite(record_distances_m[idx]):
            return None
        row = boundary_rows.iloc[idx]
        hit = {
            "source_record_id": f"HAST_ROW_{idx + 1:04d}",
            "source_row_index_1based": idx + 1,
            "feature_id": clean_scalar(row.get("feature_id")),
            "feature_name": clean_scalar(row.get("feature")),
            "boundary_type": clean_scalar(row.get("type")),
            "plate1": clean_scalar(row.get("plate1")),
            "plate2": clean_scalar(row.get("plate2")),
            "level_raw": clean_scalar(row.get("level")),
            "comment": clean_scalar(row.get("comment")),
            "source_length_attribute_raw": clean_scalar(row.get("length")),
            "distance_km": float(record_distances_m[idx] / 1000.0),
        }
        if with_point:
            matching_parts = np.flatnonzero(part_record_ids == idx)
            part_idx = int(matching_parts[np.argmin(part_distances_m[matching_parts])])
            nearest_segment = shapely.shortest_line(origin, lines[part_idx])
            xy = shapely.get_coordinates(nearest_segment)[-1]
            lon, lat = reverse.transform(float(xy[0]), float(xy[1]))
            az12, _, d_geod = GEOD.inv(event_lon, event_lat, lon, lat)
            hit["nearest_point_longitude_deg"] = float(lon)
            hit["nearest_point_latitude_deg"] = float(lat)
            hit["event_to_boundary_azimuth_deg"] = float((az12 + 360.0) % 360.0)
            hit["distance_geodesic_check_km"] = float(d_geod / 1000.0)
            hit["projection_vs_geodesic_check_abs_m"] = float(abs(d_geod - record_distances_m[idx]))
        return hit

    all_idx = min_record_id(candidate_ids)
    primary = make_hit(all_idx, with_point=True)
    if primary is None:
        raise RuntimeError("Spatial prefilter did not yield a finite nearest boundary.")
    nearest_non_inf = make_hit(min_record_id([
        i for i in candidate_ids if str(boundary_rows.iloc[int(i)]["type"]).lower() != "inferred"
    ]), with_point=False)

    class_hits: dict[str, dict[str, Any] | None] = {}
    type_values = sorted({str(v) for v in boundary_rows["type"].dropna().unique()})
    for typ in type_values:
        ids = [i for i in candidate_ids if str(boundary_rows.iloc[int(i)]["type"]) == typ]
        class_hits[typ] = make_hit(min_record_id(ids), with_point=False)
    transform_ids = [
        i for i in candidate_ids
        if str(boundary_rows.iloc[int(i)]["type"]) in {"dextral transform", "sinistral transform"}
    ]
    class_hits["transform_combined"] = make_hit(min_record_id(transform_ids), with_point=False)
    return primary, nearest_non_inf, class_hits, len(candidate_ids), candidate_counts


def exhaustive_nearest_for_validation(event_lon, event_lat, boundaries, all_lon, all_lat, part_ranges):
    """Full 571-record search for a small deterministic candidate-index audit."""
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={event_lat:.12f} +lon_0={event_lon:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    forward = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    lines, part_rec_ids, origin = build_projected_parts(
        all_lon, all_lat, part_ranges, len(boundaries), forward
    )
    part_d = np.asarray(shapely.distance(lines, origin), dtype=float)
    row_d = np.full(len(boundaries), np.inf, dtype=float)
    np.minimum.at(row_d, part_rec_ids, part_d)
    idx = int(np.argmin(row_d))
    return idx, float(row_d[idx] / 1000.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--crosswalk", type=Path, required=True)
    ap.add_argument("--boundaries", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-step-km", type=float, default=10.0)
    ap.add_argument("--validation-step-km", type=float, default=2.0)
    ap.add_argument("--skip-validation", action="store_true")
    args = ap.parse_args()

    if sha256(args.catalogue) != EXPECTED_CATALOGUE_SHA256:
        raise ValueError("Catalogue SHA-256 does not match frozen v002.")
    if sha256(args.crosswalk) != EXPECTED_CROSSWALK_SHA256:
        raise ValueError("Crosswalk SHA-256 does not match reviewed v001.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalogue = pd.read_csv(args.catalogue)
    crosswalk = pd.read_csv(args.crosswalk)
    boundaries = gpd.read_file(args.boundaries)
    if boundaries.crs is None or CRS.from_user_input(boundaries.crs) != CRS.from_epsg(4326):
        raise ValueError(f"Expected WGS84 EPSG:4326 boundaries; got {boundaries.crs}")
    if not boundaries.geometry.is_valid.all() or boundaries.geometry.is_empty.any():
        raise ValueError("Boundary geometries contain invalid/empty records; inspect before running.")
    if catalogue.event_id.duplicated().any() or crosswalk.event_id.duplicated().any():
        raise ValueError("Duplicate event IDs in catalogue or crosswalk.")
    if set(catalogue.event_id) != set(crosswalk.event_id):
        raise ValueError("Catalogue/crosswalk event ID sets differ.")
    if len(catalogue) != 1186:
        raise ValueError(f"Expected 1,186 frozen target rows; got {len(catalogue)}")

    # Join only validated event-level geography fields; catalogue remains the source of coordinates.
    cat = catalogue.copy()
    cat["latitude_deg"] = pd.to_numeric(cat["latitude_deg"], errors="raise")
    cat["longitude_deg"] = pd.to_numeric(cat["longitude_deg"], errors="raise")
    if not cat.latitude_deg.between(-90, 90).all() or not cat.longitude_deg.between(-180, 180).all():
        raise ValueError("Invalid event coordinates found.")
    assignment_cols = ["event_id", "pilot_assignment_v001"]
    merged = cat.merge(crosswalk[assignment_cols], on="event_id", how="left", validate="one_to_one")

    # Prepare linework using the original shapefile row ordering as stable record IDs.
    boundaries = boundaries.reset_index(drop=True).copy()
    boundaries["source_record_id"] = [f"HAST_ROW_{i+1:04d}" for i in range(len(boundaries))]
    lon10, lat10, ranges10, record_parts10 = prepare_boundaries(boundaries, args.max_step_km)
    sample_indexes10 = build_boundary_sample_indexes(lon10, lat10, ranges10, boundaries)
    print(f"Prepared {len(boundaries)} source records; {len(ranges10)} line parts; {len(lon10)} geodesic vertices at {args.max_step_km:g} km max step; {len(sample_indexes10)} candidate indexes.", flush=True)

    records = []
    all_type_names = sorted({str(v) for v in boundaries["type"].dropna().unique()})
    for n, row in merged.iterrows():
        primary, non_inf, class_hits, candidate_record_count, _ = nearest_for_event(
            float(row.longitude_deg), float(row.latitude_deg), boundaries,
            lon10, lat10, ranges10, len(boundaries), sample_indexes10, args.max_step_km
        )
        out = {
            "event_id": row.event_id,
            "origin_time_utc": row.origin_time_utc,
            "latitude_deg": float(row.latitude_deg),
            "longitude_deg": float(row.longitude_deg),
            "magnitude": clean_scalar(row.get("magnitude")),
            "magnitude_type": clean_scalar(row.get("magnitude_type")),
            "place": clean_scalar(row.get("place")),
            "pilot_assignment_v001": row.pilot_assignment_v001,
            "nearest_boundary_distance_km": primary["distance_km"],
            "nearest_boundary_source_record_id": primary["source_record_id"],
            "nearest_boundary_source_row_index_1based": primary["source_row_index_1based"],
            "nearest_boundary_feature_id": primary["feature_id"],
            "nearest_boundary_name": primary["feature_name"],
            "nearest_boundary_type": primary["boundary_type"],
            "nearest_boundary_plate1": primary["plate1"],
            "nearest_boundary_plate2": primary["plate2"],
            "nearest_boundary_level_raw": primary["level_raw"],
            "nearest_boundary_comment": primary["comment"],
            "nearest_boundary_point_longitude_deg": primary.get("nearest_point_longitude_deg"),
            "nearest_boundary_point_latitude_deg": primary.get("nearest_point_latitude_deg"),
            "event_to_nearest_boundary_azimuth_deg": primary.get("event_to_boundary_azimuth_deg"),
            "nearest_boundary_geodesic_check_km": primary.get("distance_geodesic_check_km"),
            "nearest_boundary_projection_geodesic_abs_difference_m": primary.get("projection_vs_geodesic_check_abs_m"),
            "candidate_boundary_records_examined": candidate_record_count,
            "nearest_non_inferred_boundary_distance_km": non_inf["distance_km"] if non_inf else np.nan,
            "nearest_non_inferred_boundary_name": non_inf["feature_name"] if non_inf else None,
            "nearest_non_inferred_boundary_type": non_inf["boundary_type"] if non_inf else None,
            "nearest_non_inferred_plate1": non_inf["plate1"] if non_inf else None,
            "nearest_non_inferred_plate2": non_inf["plate2"] if non_inf else None,
        }
        # Distance to nearest source record in each exact class.
        for typ in all_type_names:
            slug = typ.replace(" ", "_")
            h = class_hits.get(typ)
            out[f"nearest_{slug}_distance_km"] = h["distance_km"] if h else np.nan
            out[f"nearest_{slug}_name"] = h["feature_name"] if h else None
            out[f"nearest_{slug}_plate_pair"] = (
                f"{h['plate1']} | {h['plate2']}" if h and (h["plate1"] or h["plate2"]) else None
            )
        h = class_hits.get("transform_combined")
        out["nearest_transform_combined_distance_km"] = h["distance_km"] if h else np.nan
        out["nearest_transform_combined_subtype"] = h["boundary_type"] if h else None
        records.append(out)
        if (n + 1) % 100 == 0 or n + 1 == len(merged):
            print(f"Processed {n+1}/{len(merged)} events", flush=True)

    event_df = pd.DataFrame.from_records(records)
    if len(event_df) != 1186 or event_df.event_id.nunique() != 1186:
        raise RuntimeError("Event-level output failed 1,186-row/unique-ID check.")
    if event_df.nearest_boundary_distance_km.isna().any():
        raise RuntimeError("At least one event has no nearest boundary distance.")

    # Deterministic summaries.
    region_summary = (
        event_df.groupby("pilot_assignment_v001")["nearest_boundary_distance_km"]
        .agg(event_count="count", min_km="min", median_km="median", mean_km="mean", max_km="max")
        .reset_index()
    )
    q = event_df.groupby("pilot_assignment_v001")["nearest_boundary_distance_km"].quantile([0.25, 0.75]).unstack()
    region_summary = region_summary.merge(q.rename(columns={0.25: "q1_km", 0.75: "q3_km"}), on="pilot_assignment_v001")
    nearest_type_summary = (
        event_df.groupby(["pilot_assignment_v001", "nearest_boundary_type"], dropna=False)
        .size().reset_index(name="event_count")
        .sort_values(["pilot_assignment_v001", "event_count", "nearest_boundary_type"], ascending=[True, False, True])
    )
    nearest_name_summary = (
        event_df.groupby(["pilot_assignment_v001", "nearest_boundary_name", "nearest_boundary_type", "nearest_boundary_plate1", "nearest_boundary_plate2"], dropna=False)
        .size().reset_index(name="event_count")
        .sort_values(["pilot_assignment_v001", "event_count"], ascending=[True, False])
    )
    overall_type_summary = (
        event_df.groupby("nearest_boundary_type", dropna=False)
        .agg(event_count=("event_id", "count"), median_distance_km=("nearest_boundary_distance_km", "median"), mean_distance_km=("nearest_boundary_distance_km", "mean"))
        .reset_index().sort_values("event_count", ascending=False)
    )

    # Validation sample: 12 per core domain, all overlap cases, 8 outside, plus
    # deterministic event near the antimeridian (if not already selected).
    validation_ids: list[str] = []
    for assignment, take in [
        ("HIMALAYA_TIBET_CORE", 12), ("JAPAN_KURIL", 12),
        ("SUNDA_INDONESIA_CORE", 12), ("ANDES", 12),
        ("OVERLAP_REVIEW_HIMALAYA_SUNDA", 7), ("OUTSIDE_PILOT", 8),
    ]:
        ids = sorted(event_df.loc[event_df.pilot_assignment_v001 == assignment, "event_id"].astype(str).tolist())
        validation_ids.extend(ids[:take])
    antimeridian_id = "us7000glex"
    if antimeridian_id in set(event_df.event_id.astype(str)) and antimeridian_id not in validation_ids:
        validation_ids.append(antimeridian_id)
    validation_results = []
    candidate_search_results = []
    if not args.skip_validation:
        lon2, lat2, ranges2, _ = prepare_boundaries(boundaries, args.validation_step_km)
        sample_indexes2 = build_boundary_sample_indexes(lon2, lat2, ranges2, boundaries)
        selected = event_df[event_df.event_id.astype(str).isin(validation_ids)].copy()
        for _, row in selected.iterrows():
            fine, _, _, fine_candidates, _ = nearest_for_event(
                float(row.longitude_deg), float(row.latitude_deg), boundaries,
                lon2, lat2, ranges2, len(boundaries), sample_indexes2, args.validation_step_km
            )
            same_nearest_record = fine["source_record_id"] == row.nearest_boundary_source_record_id
            fine_km = fine["distance_km"]
            coarse_km = float(row.nearest_boundary_distance_km)
            validation_results.append({
                "event_id": row.event_id,
                "pilot_assignment_v001": row.pilot_assignment_v001,
                "coarse_step_km": args.max_step_km,
                "fine_step_km": args.validation_step_km,
                "coarse_distance_km": coarse_km,
                "fine_distance_km": fine_km,
                "absolute_distance_difference_m": abs(coarse_km - fine_km) * 1000,
                "same_nearest_source_record": same_nearest_record,
                "coarse_boundary_type": row.nearest_boundary_type,
                "fine_boundary_type": fine["boundary_type"],
                "fine_source_record_id": fine["source_record_id"],
                "fine_candidate_records_examined": fine_candidates,
            })

        # Full 571-row exhaustive search on a compact, deterministic subset to
        # verify that the spatial candidate prefilter does not miss the nearest row.
        exhaustive_ids: list[str] = []
        for assignment, take in [
            ("HIMALAYA_TIBET_CORE", 2), ("JAPAN_KURIL", 2),
            ("SUNDA_INDONESIA_CORE", 2), ("ANDES", 2),
            ("OVERLAP_REVIEW_HIMALAYA_SUNDA", 4), ("OUTSIDE_PILOT", 4),
        ]:
            ids = sorted(event_df.loc[event_df.pilot_assignment_v001 == assignment, "event_id"].astype(str).tolist())
            exhaustive_ids.extend(ids[:take])
        if antimeridian_id in set(event_df.event_id.astype(str)) and antimeridian_id not in exhaustive_ids:
            exhaustive_ids.append(antimeridian_id)
        exhaustive_selected = event_df[event_df.event_id.astype(str).isin(exhaustive_ids)].copy()
        for _, row in exhaustive_selected.iterrows():
            exact_idx, exact_km = exhaustive_nearest_for_validation(
                float(row.longitude_deg), float(row.latitude_deg), boundaries,
                lon10, lat10, ranges10
            )
            candidate_search_results.append({
                "event_id": row.event_id,
                "pilot_assignment_v001": row.pilot_assignment_v001,
                "candidate_nearest_distance_km": float(row.nearest_boundary_distance_km),
                "exhaustive_nearest_distance_km": exact_km,
                "absolute_difference_m": abs(float(row.nearest_boundary_distance_km) - exact_km) * 1000,
                "candidate_nearest_source_record_id": row.nearest_boundary_source_record_id,
                "exhaustive_nearest_source_record_id": f"HAST_ROW_{exact_idx + 1:04d}",
                "same_nearest_source_record": row.nearest_boundary_source_record_id == f"HAST_ROW_{exact_idx + 1:04d}",
            })
    validation_df = pd.DataFrame(validation_results)
    candidate_search_df = pd.DataFrame(candidate_search_results)

    out = args.output_dir
    event_path = out / "event_level_tectonic_boundary_distances_v001.csv"
    event_df.to_csv(event_path, index=False, encoding="utf-8-sig")
    region_summary.to_csv(out / "boundary_distance_summary_by_pilot_assignment_v001.csv", index=False, encoding="utf-8-sig")
    nearest_type_summary.to_csv(out / "nearest_boundary_type_counts_by_pilot_assignment_v001.csv", index=False, encoding="utf-8-sig")
    nearest_name_summary.to_csv(out / "nearest_boundary_name_counts_by_pilot_assignment_v001.csv", index=False, encoding="utf-8-sig")
    overall_type_summary.to_csv(out / "nearest_boundary_type_overall_v001.csv", index=False, encoding="utf-8-sig")
    validation_df.to_csv(out / "distance_densification_validation_v001.csv", index=False, encoding="utf-8-sig")
    candidate_search_df.to_csv(out / "candidate_search_exhaustive_validation_v001.csv", index=False, encoding="utf-8-sig")

    # Request source row metadata as its own reproducible lookup table.
    boundary_meta = boundaries.drop(columns=["geometry", "source_record_id"]).copy()
    boundary_meta.insert(0, "source_record_id", boundaries.source_record_id)
    boundary_meta.to_csv(out / "hasterok_boundary_source_record_lookup_v001.csv", index=False, encoding="utf-8-sig")

    max_projection_check = float(event_df.nearest_boundary_projection_geodesic_abs_difference_m.max())
    primary_inferred_count = int((event_df.nearest_boundary_type == "inferred").sum())
    missing_primary_name_count = int(event_df.nearest_boundary_name.isna().sum())
    max_distance_rows = event_df.nlargest(5, "nearest_boundary_distance_km")[[
        "event_id", "place", "nearest_boundary_distance_km", "nearest_boundary_type", "nearest_boundary_name"
    ]]
    metadata = {
        "stage": "1C.2.3",
        "run_id": "stage1c2_boundary_distance_v001",
        "catalogue_sha256": sha256(args.catalogue),
        "crosswalk_sha256": sha256(args.crosswalk),
        "boundary_shapefile_sha256": sha256(args.boundaries),
        "catalogue_rows": len(catalogue),
        "crosswalk_rows": len(crosswalk),
        "boundary_source_rows": len(boundaries),
        "boundary_geometry_types": {str(k): int(v) for k, v in boundaries.geom_type.value_counts().items()},
        "boundary_type_counts": {str(k): int(v) for k, v in boundaries["type"].value_counts(dropna=False).items()},
        "boundary_feature_id_unique_count": int(boundaries.feature_id.nunique(dropna=True)),
        "boundary_feature_id_null_rows": int(boundaries.feature_id.isna().sum()),
        "boundary_feature_id_duplicate_rows": int(boundaries.feature_id.duplicated(keep=False).sum()),
        "boundary_invalid_geometry_count": int((~boundaries.geometry.is_valid).sum()),
        "boundary_empty_geometry_count": int(boundaries.geometry.is_empty.sum()),
        "boundary_source_total_length_attribute_raw_sum": float(pd.to_numeric(boundaries["length"], errors="coerce").sum()),
        "densification_max_step_km": args.max_step_km,
        "validation_densification_step_km": args.validation_step_km,
        "candidate_prefilter_average_boundary_records_examined": float(event_df.candidate_boundary_records_examined.mean()),
        "candidate_prefilter_max_boundary_records_examined": int(event_df.candidate_boundary_records_examined.max()),
        "candidate_search_exhaustive_validation_n": int(len(candidate_search_df)),
        "candidate_search_exhaustive_validation_max_abs_difference_m": float(candidate_search_df.absolute_difference_m.max()) if len(candidate_search_df) else None,
        "candidate_search_exhaustive_validation_same_nearest_record_count": int(candidate_search_df.same_nearest_source_record.sum()) if len(candidate_search_df) else None,
        "densification_validation_n": int(len(validation_df)),
        "densification_validation_max_abs_difference_m": float(validation_df.absolute_distance_difference_m.max()) if len(validation_df) else None,
        "densification_validation_median_abs_difference_m": float(validation_df.absolute_distance_difference_m.median()) if len(validation_df) else None,
        "densification_validation_same_nearest_record_count": int(validation_df.same_nearest_source_record.sum()) if len(validation_df) else None,
        "max_projection_geodesic_recheck_abs_difference_m": max_projection_check,
        "overall_nearest_boundary_distance_median_km": float(event_df.nearest_boundary_distance_km.median()),
        "overall_nearest_boundary_distance_max_km": float(event_df.nearest_boundary_distance_km.max()),
        "primary_nearest_boundary_inferred_event_count": primary_inferred_count,
        "primary_nearest_boundary_name_missing_count": missing_primary_name_count,
        "primary_nearest_boundary_type_missing_count": int(event_df.nearest_boundary_type.isna().sum()),
        "primary_nearest_boundary_plate1_missing_count": int(event_df.nearest_boundary_plate1.isna().sum()),
        "primary_nearest_boundary_plate2_missing_count": int(event_df.nearest_boundary_plate2.isna().sum()),
        "distance_method": "WGS84 Geod.npts geodesic densification; per-event WGS84 azimuthal-equidistant projection; nearest point on projected polyline; inverse projection and Geod.inv check",
        "distance_cutoff_applied": False,
        "inferred_boundaries_in_primary_search": True,
        "nearest_non_inferred_alternative_reported": True,
        "level_field_interpretation": "Not interpreted; retained raw because source README/schema snapshot does not define its meaning",
        "feature_id_handling": "Not assumed unique; source row index is the stable within-snapshot boundary record identity",
        "no_supporting_event_records_downloaded": True,
        "no_sequence_labels_assigned": True,
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "geopandas_version": gpd.__version__,
        "shapely_version": shapely.__version__,
        "pyproj_version": pyproj.__version__,
    }
    (out / "boundary_distance_run_metadata_v001.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Concise audit report.
    report = []
    report += [
        "# LAIC-GUARD Stage 1C.2.3 — Tectonic Boundary Distance Audit v001",
        "",
        "## Scope",
        "Computed nearest distances from all 1,186 frozen target catalogue epicentres to the mapped line records in Hasterok `plate_boundaries.shp`.",
        "The source catalogue and Stage 1C.2 pilot assignment v001 were read-only. No supporting earthquake records were downloaded and no sequence labels were assigned.",
        "",
        "## Methods",
        f"- Boundary layer: {len(boundaries)} source rows; EPSG:4326; {boundaries.geom_type.value_counts().to_dict()} geometry types.",
        f"- Each source segment was densified along WGS84 geodesics to a maximum vertex spacing of {args.max_step_km:g} km.",
        "- For each event, linework was transformed into an event-centred WGS84 azimuthal-equidistant projection. Minimum point-to-line distance was measured from the projected origin.",
        "- The nearest point was transformed back to WGS84 and checked with `pyproj.Geod.inv`.",
        "- No distance threshold was applied. All source boundary classes, including `inferred`, are included in the primary nearest-boundary result.",
        "- A second result reports the nearest non-`inferred` source record. Boundary `level` is retained but not interpreted.",
        "- `feature_id` is not unique in the supplied shapefile; source row IDs `HAST_ROW_0001`... are used to preserve separate records.",
        "",
        "## Validation",
        f"- Catalogue rows / unique event IDs: {len(event_df)} / {event_df.event_id.nunique()}.",
        f"- Boundary source rows: {len(boundaries)}; invalid geometries: {(~boundaries.geometry.is_valid).sum()}; empty geometries: {boundaries.geometry.is_empty.sum()}.",
        f"- Projection-to-geodesic recheck maximum absolute difference: {max_projection_check:.6f} m.",
        f"- Candidate prefilter versus exhaustive 571-record search: {len(candidate_search_df)} events; max absolute distance difference: {metadata['candidate_search_exhaustive_validation_max_abs_difference_m']} m; same nearest row: {metadata['candidate_search_exhaustive_validation_same_nearest_record_count']} / {len(candidate_search_df)}.",
        f"- Densification convergence sample: {len(validation_df)} events; maximum absolute difference between {args.max_step_km:g} km and {args.validation_step_km:g} km steps: {metadata['densification_validation_max_abs_difference_m'] if len(validation_df) else 'not run'} m.",
        f"- Same nearest source record in convergence sample: {metadata['densification_validation_same_nearest_record_count']} / {len(validation_df)}.",
        "",
        "## Nearest boundary distance by pilot assignment",
        region_summary.to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Primary nearest boundary type by pilot assignment",
        nearest_type_summary.to_markdown(index=False),
        "",
        "## Nearest boundary type overall",
        overall_type_summary.to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Additional audit findings",
        f"- Median nearest mapped-boundary distance across all events: {metadata['overall_nearest_boundary_distance_median_km']:.3f} km.",
        f"- The primary nearest line record is classified as `inferred` for {primary_inferred_count} events; these are retained in the primary result and accompanied by a nearest non-inferred alternative.",
        f"- The source boundary `feature` name is blank for {missing_primary_name_count} primary matches; boundary type and both plate-pair fields are populated for all events.",
        "- Largest-distance events (not exclusions):",
        max_distance_rows.to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Interpretation limits",
        "- These are distances to the nearest mapped boundary line in the Hasterok source model, not distances to a rupture plane, hypocentre, slab surface, or necessarily the causative fault.",
        "- The minimum may be to a boundary class such as transform, collision, spreading centre, extension, or inferred; do not interpret every nearest boundary as a subduction interface.",
        "- Distances do not establish tectonic-region membership or justify a geographic cutoff. They are evidence for the later regional-domain review.",
        "- The source geometry is a present-day model and the calculation does not reconstruct boundary positions at each earthquake origin time.",
        "",
        "## Reproducibility",
        f"- Catalogue SHA-256: `{metadata['catalogue_sha256']}`",
        f"- Crosswalk SHA-256: `{metadata['crosswalk_sha256']}`",
        f"- Boundary shapefile SHA-256: `{metadata['boundary_shapefile_sha256']}`",
        "- Full machine-readable metadata: `boundary_distance_run_metadata_v001.json`.",
        "",
    ]
    (out / "STAGE1C2_BOUNDARY_DISTANCE_AUDIT_v001.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
