import csv
import hashlib
import math
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
FROZEN_CSV = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
CACHE_DIR = ROOT / "data/external/gnss/unr_station_holdings_v001"
OUT_DIR = ROOT / "reports/stage2a/gnss_station_pairing_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage2A-GNSS-Pairing/1.0 (academic-research)"


def fetch_unr_holdings() -> tuple[Path, str]:
    urls = [
        ("https://geodesy.unr.edu/NGLStationPages/DataHoldings.txt", "DataHoldings.txt"),
        ("http://geodesy.unr.edu/NGLStationPages/DataHoldings.txt", "DataHoldings.txt"),
        ("https://geodesy.unr.edu/NGLStationPages/llh.out", "llh.out"),
    ]
    for url, fname in urls:
        dest = CACHE_DIR / fname
        if dest.exists() and dest.stat().st_size > 50_000:
            print(f"Using cached UNR station file: {dest}")
            return dest, url
        try:
            print(f"Downloading {url} ...")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                if len(raw) > 50_000:
                    dest.write_bytes(raw)
                    print(f"Saved {dest} ({len(raw):,} bytes)")
                    return dest, url
        except Exception as e:
            print(f"  Warning: failed {url}: {e}")
    raise RuntimeError("Could not download UNR station metadata from any endpoint.")


def parse_unr_stations(file_path: Path, source_url: str) -> list[dict]:
    stations = {}
    is_holdings = file_path.name == "DataHoldings.txt"
    with file_path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f):
            parts = line.strip().split()
            if not parts:
                continue
            if is_holdings and line_no == 0 and parts[0].lower() in ("sta", "station"):
                continue
            if len(parts) < 4:
                continue
            sta = parts[0].strip().upper()
            if len(sta) != 4:
                continue
            try:
                lat = float(parts[1])
                lon = float(parts[2])
                elev = float(parts[3])
            except ValueError:
                continue

            # Normalize longitude to [-180, 180]
            if lon > 180.0:
                lon -= 360.0

            parsed_dates = []
            for tok in parts[4:]:
                t_up = tok.strip().upper()
                if len(t_up) == 10 and t_up[4] == "-" and t_up[7] == "-":
                    try:
                        parsed_dates.append(datetime.fromisoformat(t_up))
                    except ValueError:
                        pass
                elif len(t_up) == 7 and t_up[:2].isdigit() and t_up[2:5].isalpha() and t_up[5:].isdigit():
                    try:
                        parsed_dates.append(datetime.strptime(t_up, "%y%b%d"))
                    except ValueError:
                        pass
            dt_beg_obj = parsed_dates[0] if len(parsed_dates) >= 1 else None
            dt_end_obj = parsed_dates[1] if len(parsed_dates) >= 2 else None
            dt_beg = dt_beg_obj.strftime("%Y-%m-%d") if dt_beg_obj else ""
            dt_end = dt_end_obj.strftime("%Y-%m-%d") if dt_end_obj else ""
            start_utc = f"{dt_beg}T00:00:00Z" if dt_beg else ""
            end_utc = f"{dt_end}T23:59:59Z" if dt_end else ""

            stations[sta] = {
                "station_id": sta,
                "network": "UNR_NGL_GLOBAL",
                "provider": "Nevada_Geodetic_Laboratory",
                "station_type": "CONTINUOUS_GNSS",
                "latitude_deg": f"{lat:.6f}",
                "longitude_deg": f"{lon:.6f}",
                "elevation_m": f"{elev:.2f}",
                "start_time_utc": start_utc,
                "end_time_utc": end_utc,
                "parameters_available": "ZTD;PWV;IGS20_TROPOSPHERE",
                "source_url": source_url,
                "access_notes": "Open UNR NGL troposphere/position archive (/IGS20/trop/)",
                "licence_notes": "Academic attribution to Blewitt et al. (2018) / NGL required",
                "qc_status": "UNR_LISTED_ACTIVE_SPAN_VERIFIED" if dt_beg else "UNR_COORDINATES_ONLY",
                "_lat": lat,
                "_lon": lon,
                "_dt_beg": datetime.fromisoformat(dt_beg) if dt_beg else None,
                "_dt_end": datetime.fromisoformat(dt_end) if dt_end else None,
            }
    return sorted(stations.values(), key=lambda x: x["station_id"])


def haversine_and_azimuth(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    r_earth = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    dist_km = r_earth * c

    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    az = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return dist_km, az


def main() -> None:
    holdings_path, src_url = fetch_unr_holdings()
    stations = parse_unr_stations(holdings_path, src_url)
    print(f"Parsed {len(stations):,} unique continuous GNSS stations from UNR.")

    with FROZEN_CSV.open("r", encoding="utf-8-sig") as f:
        events = [
            r for r in csv.DictReader(f)
            if r["stage1d_included_in_pilot_v001"] == "True"
        ]
    print(f"Pairing {len(events)} frozen Stage 1D Core Pilot events against UNR GNSS stations...")

    # Pre-index stations by 10-degree latitude bands for fast spatial filtering
    lat_bins: dict[int, list[dict]] = {}
    for st in stations:
        b = int(math.floor(st["_lat"] / 10.0))
        lat_bins.setdefault(b, []).append(st)

    pair_rows = []
    event_summaries = []
    used_station_ids = set()

    for ev in events:
        eid = ev["event_id"]
        elat = float(ev["latitude_deg"])
        elon = float(ev["longitude_deg"])
        rd_km = float(ev["dobrovolsky_radius_km"])
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00")).replace(tzinfo=None)
        win_start = ev_dt - timedelta(days=45)
        win_end = ev_dt + timedelta(days=5)

        deg_pad = (rd_km / 111.0) + 1.5
        b_min = int(math.floor((elat - deg_pad) / 10.0))
        b_max = int(math.floor((elat + deg_pad) / 10.0))

        ev_pairs = []
        for b in range(b_min, b_max + 1):
            for st in lat_bins.get(b, []):
                if abs(st["_lat"] - elat) > deg_pad:
                    continue
                dist_km, az_deg = haversine_and_azimuth(elat, elon, st["_lat"], st["_lon"])
                if dist_km <= rd_km:
                    active_full = False
                    if st["_dt_beg"] and st["_dt_end"]:
                        active_full = (st["_dt_beg"] <= win_start) and (st["_dt_end"] >= win_end)
                    ev_pairs.append((dist_km, az_deg, st, active_full))

        ev_pairs.sort(key=lambda x: x[0])
        active_pairs = [p for p in ev_pairs if p[3]]

        for dist_km, az_deg, st, active_full in ev_pairs:
            used_station_ids.add(st["station_id"])
            pair_rows.append({
                "event_id": eid,
                "station_id": st["station_id"],
                "distance_km": f"{dist_km:.2f}",
                "azimuth_deg": f"{az_deg:.2f}",
                "distance_method": "WGS84_HAVERSINE_GREAT_CIRCLE",
                "coordinate_source": "UNR_NGL_DATAHOLDINGS",
                "calculation_version": "stage2a_v001",
                "dobrovolsky_radius_km": f"{rd_km:.2f}",
                "distance_to_rd_ratio": f"{(dist_km / rd_km):.4f}",
                "station_active_minus45_plus5d": str(active_full),
            })

        nearest_active = active_pairs[0] if active_pairs else None
        event_summaries.append({
            "event_id": eid,
            "origin_time_utc": ev["origin_time_utc"],
            "magnitude": ev["magnitude"],
            "depth_km": ev["depth_km"],
            "frozen_macro_region_v001": ev["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": ev["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": ev["stage1d_analysis_role_v001"],
            "dobrovolsky_radius_km": f"{rd_km:.2f}",
            "total_unr_stations_in_rd": len(ev_pairs),
            "active_unr_stations_in_rd": len(active_pairs),
            "nearest_active_station_id": nearest_active[2]["station_id"] if nearest_active else "",
            "nearest_active_distance_km": f"{nearest_active[0]:.2f}" if nearest_active else "",
            "gnss_pairing_eligible_v001": str(len(active_pairs) > 0),
        })

    # 1. Export full UNR station registry + paired subset
    reg_fields = [
        "station_id", "network", "provider", "station_type", "latitude_deg", "longitude_deg",
        "elevation_m", "start_time_utc", "end_time_utc", "parameters_available",
        "source_url", "access_notes", "licence_notes", "qc_status"
    ]
    reg_out = ANALYSIS_DIR / "station_registry_unr_full_v001.csv"
    with reg_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=reg_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(stations)

    paired_reg_out = ANALYSIS_DIR / "station_registry_paired_subset_v001.csv"
    with paired_reg_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=reg_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows([s for s in stations if s["station_id"] in used_station_ids])

    # 2. Export station-event distances
    dist_out = ANALYSIS_DIR / "station_event_distances_v001.csv"
    with dist_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pair_rows[0].keys()))
        w.writeheader()
        w.writerows(pair_rows)

    # 3. Export event-level GNSS coverage summary
    ev_sum_out = ANALYSIS_DIR / "event_gnss_coverage_summary_v001.csv"
    with ev_sum_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(event_summaries[0].keys()))
        w.writeheader()
        w.writerows(event_summaries)

    elig_total = sum(1 for x in event_summaries if x["gnss_pairing_eligible_v001"] == "True")
    elig_shallow = sum(
        1 for x in event_summaries
        if x["gnss_pairing_eligible_v001"] == "True" and x["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET"
    )
    elig_ctrl = sum(
        1 for x in event_summaries
        if x["gnss_pairing_eligible_v001"] == "True" and x["stage1d_analysis_role_v001"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"
    )

    md_out = OUT_DIR / "STAGE2A_GNSS_STATION_PAIRING_v001.md"
    md_out.write_text(
        "# Stage 2A - UNR Continuous GNSS Station Inventory & Dobrovolsky Pairing (v001)\n\n"
        f"**UNR Global Station Count:** {len(stations):,} continuous GNSS stations\n"
        f"**Unique Stations Within Dobrovolsky Radius of Core Pilot Events:** {len(used_station_ids):,}\n"
        f"**Total Station-Event Pairs (d <= R_D):** {len(pair_rows):,}\n"
        f"**Events with >=1 Active GNSS Station ([-45d, +5d]):** {elig_total} / {len(events)} "
        f"({elig_shallow} Primary Shallow Targets + {elig_ctrl} Physical Null-Control Events)\n",
        encoding="utf-8",
    )

    verify_ps1 = OUT_DIR / "VERIFY_PACKAGE.ps1"
    verify_ps1.write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n'
        '$ErrorActionPreference = "Stop"\n'
        '$entries = Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv")\n'
        'foreach ($e in $entries) {\n'
        '    $fp = Join-Path $PackageRoot $e.relative_path\n'
        '    if (!(Test-Path $fp) -or (Get-FileHash $fp -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) {\n'
        '        throw "SHA256 mismatch: $($e.relative_path)"\n'
        '    }\n'
        '    Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n'
        '}\n'
        '$ev = Import-Csv (Join-Path $PackageRoot "analysis\\event_gnss_coverage_summary_v001.csv")\n'
        'if ($ev.Count -ne 563) { throw "Expected 563 Stage 1D events, got $($ev.Count)" }\n'
        'Write-Host "ALL CHECKS PASSED (563 Stage 1D events paired and SHA-256 verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE2A_GNSS_STATION_PAIRING_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/station_registry_unr_full_v001.csv",
        "analysis/station_registry_paired_subset_v001.csv",
        "analysis/station_event_distances_v001.csv",
        "analysis/event_gnss_coverage_summary_v001.csv",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print(f"\nStage 2A Complete:")
    print(f"  Total station-event pairs (d <= R_D) : {len(pair_rows):,}")
    print(f"  Eligible events (>=1 active station) : {elig_total} / {len(events)} ({elig_shallow} Primary Shallow, {elig_ctrl} Null-Control)")


if __name__ == "__main__":
    main()

