import csv, hashlib, json, math, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
sys.path.insert(0, str(ROOT / "scripts"))
from stage4b_scale_full_tier1_cohort_v001 import bilinear_vtec, bootstrap_auc_ci, median_and_mad, roc_auc
from stage5b_hardened_audit_v002 import grouped_loeo, parse_ionex_safe, pr_auc, wilcoxon_p
from stage5c_zero_overlap_equallag_v002 import parse_trop_strict

S1D_CAT = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
S2C_COH = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
S4B_EV  = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
STN_REG = ROOT / "metadata/station_registry.csv"

ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
ERA5_CACHE = ROOT / "data/external/meteorology/era5_openmeteo_v002"
ERA5_CACHE.mkdir(parents=True, exist_ok=True)

OUT_DIR = ROOT / "reports/stage5e/era5_deconfounded_v002_era5"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def load_station_coords() -> dict[str, tuple[float, float, float]]:
    if not STN_REG.exists():
        return {}
    with STN_REG.open(encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        cols = rdr.fieldnames or []
        id_c = next((c for c in cols if "station" in c.lower() and "id" in c.lower()), cols[0])
        lat_c = next((c for c in cols if "lat" in c.lower()), "")
        lon_c = next((c for c in cols if "lon" in c.lower()), "")
        h_c = next((c for c in cols if "height" in c.lower() or "elev" in c.lower()), "")
        out = {}
        for r in rdr:
            sid = r.get(id_c, "").strip().upper()
            if sid and lat_c and lon_c:
                try:
                    lat = float(r[lat_c])
                    lon = float(r[lon_c])
                    h_m = float(r[h_c]) if (h_c and r.get(h_c, "").strip()) else 0.0
                    out[sid] = (lat, lon, h_m)
                except ValueError:
                    pass
        return out


def fetch_era5_hourly(eid: str, sid: str, lat: float, lon: float, h_m: float, t0: datetime, t1: datetime) -> dict[str, float]:
    cache_fp = ERA5_CACHE / f"{eid}_{sid}_era5.json"
    if cache_fp.exists() and cache_fp.stat().st_size > 200:
        payload = json.loads(cache_fp.read_text(encoding="utf-8"))
    else:
        s_str = t0.strftime("%Y-%m-%d")
        e_str = t1.strftime("%Y-%m-%d")
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&start_date={s_str}&end_date={e_str}"
            f"&hourly=surface_pressure,temperature_2m,dew_point_2m,total_column_integrated_water_vapour&timezone=UTC"
        )
        payload = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "LAIC-GUARD-Stage5E-ERA5/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                    payload = json.loads(raw)
                    cache_fp.write_text(raw, encoding="utf-8")
                    time.sleep(0.22)
                    break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if payload is None:
            return {}

    hr = payload.get("hourly", {})
    times = hr.get("time", [])
    ps_arr = hr.get("surface_pressure", [])
    t2_arr = hr.get("temperature_2m", [])
    td_arr = hr.get("dew_point_2m", [])
    tcwv_arr = hr.get("total_column_integrated_water_vapour", [])

    phi = math.radians(lat)
    h_km = h_m / 1000.0
    denom_zhd = 1.0 - 0.00266 * math.cos(2.0 * phi) - 0.00028 * h_km
    ztd_era5 = {}

    for i, t_str in enumerate(times):
        ps = ps_arr[i] if i < len(ps_arr) else None
        t2 = t2_arr[i] if i < len(t2_arr) else None
        tcwv = tcwv_arr[i] if i < len(tcwv_arr) else None
        if tcwv is None and i < len(td_arr) and td_arr[i] is not None:
            # Magnus vapor pressure fallback if TCWV missing
            e_hpa = 6.112 * math.exp((17.67 * td_arr[i]) / (td_arr[i] + 243.5))
            tcwv = 1.75 * e_hpa
        if ps is None or tcwv is None:
            continue
        t_k = (t2 + 273.15) if t2 is not None else 288.15
        tm = 70.2 + 0.72 * t_k
        # Bevis (1992) Pi conversion factor (kg/m^2 PWV -> mm ZWD)
        pi_inv = 1e-6 * 461.5 * (3.739e5 / tm + 22.1)
        zhd_mm = (2.2768 * ps) / denom_zhd
        zwd_mm = tcwv * pi_inv * 1000.0
        ztd_era5[t_str + ":00Z"] = zhd_mm + zwd_mm

    return ztd_era5


def ols_calibrate(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    if len(pairs) < 24:
        return 0.0, 1.0
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx < 1e-6:
        return my - mx, 1.0
    beta = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    alpha = my - beta * mx
    return alpha, beta


def main() -> None:
    s1d = {r["event_id"]: r for r in csv.DictReader(S1D_CAT.open(encoding="utf-8-sig"))}
    s2c = {r["event_id"]: r for r in csv.DictReader(S2C_COH.open(encoding="utf-8-sig"))}
    s4b = sorted(csv.DictReader(S4B_EV.open(encoding="utf-8-sig")), key=lambda x: x["origin_time_utc"])
    stn_coords = load_station_coords()

    omni = {}
    for fp in sorted(OMNI_CACHE.glob("omni2_*.dat")):
        for line in fp.open(encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) < 51:
                continue
            try:
                y, doy, hr, kp10, dst, f107 = int(p[0]), int(p[1]), int(p[2]), int(p[38]), float(p[40]), float(p[50])
                ts = (datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hr)).strftime("%Y-%m-%dT%H:00:00Z")
                omni[ts] = (kp10 / 10.0 if 0 <= kp10 <= 90 else None, dst if -1000 <= dst <= 500 else None, f107 if 50 <= f107 <= 400 else None)
            except ValueError:
                pass

    print(f"Fetching/loading ERA5 hourly reanalysis for {len(s4b)} paired Tier-1 events...")
    ionex_cache, ev_rows = {}, []
    cid, prev_dt, era5_ok = 0, None, 0

    for idx, ev in enumerate(s4b, 1):
        eid = ev["event_id"]
        sid = ev["verified_gnss_station_id"].strip().upper()
        m = s1d[eid]
        elat, elon = float(m["latitude_deg"]), float(m["longitude_deg"])
        slat, slon, sh_m = stn_coords.get(sid, (elat, elon, 0.0))

        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        if prev_dt is None or (ev_dt - prev_dt).days > 15:
            cid += 1
        clust, prev_dt = f"C{cid:03d}", ev_dt
        ev_hr = ev_dt.replace(minute=0, second=0, microsecond=0)
        w0, w1 = ev_dt - timedelta(days=45), ev_dt + timedelta(days=5)

        ztd_gnss = {}
        for u in s2c[eid]["unr_trop_urls"].split(";"):
            zp = ZIP_CACHE / u.strip().rstrip("/").split("/")[-1]
            if zp.exists():
                zh, _, _ = parse_trop_strict(zp, w0, w1)
                ztd_gnss.update(zh)

        ztd_era5 = fetch_era5_hourly(eid, sid, slat, slon, sh_m, w0, w1)
        if len(ztd_era5) >= 800:
            era5_ok += 1
        if idx % 30 == 0 or idx == len(s4b):
            print(f"  ERA5 progress: {idx}/{len(s4b)} (valid={era5_ok})")

        vtec_hr = {}
        for off in range(-45, 6):
            d_dt = (ev_dt + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
            dk = d_dt.strftime("%Y-%m-%d")
            if dk not in ionex_cache:
                ionex_cache[dk] = parse_ionex_safe(d_dt)
            for mt in ionex_cache[dk]:
                v = bilinear_vtec(mt, elat, elon)
                if not math.isnan(v):
                    vtec_hr[mt[0].strftime("%Y-%m-%dT%H:00:00Z")] = v

        tl = []
        for h_off in range(-45 * 24, 5 * 24 + 1):
            tc = ev_hr + timedelta(hours=h_off)
            ts = tc.strftime("%Y-%m-%dT%H:00:00Z")
            kp, dst, f107 = omni.get(ts, (None, None, None))
            zg = ztd_gnss.get(ts)
            ze = ztd_era5.get(ts)
            tl.append({
                "rh": h_off,
                "h": tc.hour,
                "q": (kp is not None and dst is not None and kp < 3.0 and dst > -30.0),
                "f107": f107,
                "zg": zg,
                "ze": ze,
                "res_raw": (zg - ze) if (zg is not None and ze is not None) else None,
                "vtec": vtec_hr.get(ts),
            })

        # Out-of-sample OLS calibration of ERA5 ZTD -> GNSS ZTD inside each causal baseline
        a_p, b_p = ols_calibrate([(x["ze"], x["zg"]) for x in tl if -45 * 24 <= x["rh"] <= -31 * 24 - 1 and x["zg"] is not None and x["ze"] is not None])
        a_t, b_t = ols_calibrate([(x["ze"], x["zg"]) for x in tl if -25 * 24 <= x["rh"] <= -11 * 24 - 1 and x["zg"] is not None and x["ze"] is not None])
        for x in tl:
            if x["zg"] is not None and x["ze"] is not None:
                x["res_p"] = x["zg"] - (a_p + b_p * x["ze"])
                x["res_t"] = x["zg"] - (a_t + b_t * x["ze"])
            else:
                x["res_p"] = x["res_t"] = None

        # F10.7 detrending on both causal baselines
        pts = [(x["f107"], x["vtec"]) for x in tl if ((-45 * 24 <= x["rh"] <= -31 * 24 - 1) or (-25 * 24 <= x["rh"] <= -11 * 24 - 1)) and x["q"] and x["f107"] and x["vtec"]]
        if len(pts) >= 48:
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            sxx = sum((p[0] - mx) ** 2 for p in pts)
            slp = (sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx) if sxx > 1e-6 else 0.0
        else:
            slp, mx = 0.0, 0.0
        for x in tl:
            x["vd"] = (x["vtec"] - slp * (x["f107"] - mx)) if (x["vtec"] is not None and x["f107"] is not None) else x["vtec"]

        def win_z(b0, b1, e0, e1, fld, qo=False):
            pool = [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x[fld] is not None and (not qo or x["q"])]
            if len(pool) < 20:
                return []
            gm, gs = median_and_mad(pool)
            cal = {h: median_and_mad(sub) if len(sub := [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x["h"] == h and x[fld] is not None and (not qo or x["q"])]) >= 2 else (gm, gs) for h in range(24)}
            return [abs((x[fld] - cal[x["h"]][0]) / cal[x["h"]][1]) for x in tl if e0 <= x["rh"] <= e1 and x[fld] is not None and (not qo or x["q"])]

        pz = win_z(-45 * 24, -31 * 24 - 1, -30 * 24, -21 * 24 - 1, "zg")
        tz = win_z(-25 * 24, -11 * 24 - 1, -10 * 24, -1, "zg")
        pr_raw = win_z(-45 * 24, -31 * 24 - 1, -30 * 24, -21 * 24 - 1, "res_raw")
        tr_raw = win_z(-25 * 24, -11 * 24 - 1, -10 * 24, -1, "res_raw")
        pr_cal = win_z(-45 * 24, -31 * 24 - 1, -30 * 24, -21 * 24 - 1, "res_p")
        tr_cal = win_z(-25 * 24, -11 * 24 - 1, -10 * 24, -1, "res_t")
        pv = win_z(-45 * 24, -31 * 24 - 1, -30 * 24, -21 * 24 - 1, "vd", True)
        tv = win_z(-25 * 24, -11 * 24 - 1, -10 * 24, -1, "vd", True)

        if min(len(pz), len(tz), len(pr_cal), len(tr_cal), len(pv), len(tv)) < 12:
            continue

        ev_rows.append({
            "event_id": eid,
            "cluster_id": clust,
            "role": ev["stage1d_analysis_role_v001"],
            "src": ev["stage1c4_final_source_class_v001"],
            "p_ztd_max": max(pz), "p_ztd_q95": sorted(pz)[int(0.95 * (len(pz) - 1))],
            "t_ztd_max": max(tz), "t_ztd_q95": sorted(tz)[int(0.95 * (len(tz) - 1))],
            "p_raw_max": max(pr_raw), "p_raw_q95": sorted(pr_raw)[int(0.95 * (len(pr_raw) - 1))],
            "t_raw_max": max(tr_raw), "t_raw_q95": sorted(tr_raw)[int(0.95 * (len(tr_raw) - 1))],
            "p_cal_max": max(pr_cal), "p_cal_q95": sorted(pr_cal)[int(0.95 * (len(pr_cal) - 1))],
            "t_cal_max": max(tr_cal), "t_cal_q95": sorted(tr_cal)[int(0.95 * (len(tr_cal) - 1))],
            "p_vtec_max": max(pv), "p_vtec_q95": sorted(pv)[int(0.95 * (len(pv) - 1))],
            "t_vtec_max": max(tv), "t_vtec_q95": sorted(tv)[int(0.95 * (len(tv) - 1))],
        })

    with (ANALYSIS_DIR / "stage5e_era5_event_features_v002.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ev_rows[0].keys()))
        w.writeheader()
        w.writerows(ev_rows)

    summary = []
    def eval_model(desc: str, sub: list[dict], feats_p: list[str], feats_t: list[str], diff_key: str, gk: str = "event_id"):
        samps = []
        for e in sub:
            d0 = {"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 0}
            d1 = {"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 1}
            for j, (kp, kt) in enumerate(zip(feats_p, feats_t)):
                d0[f"f{j}"] = e[kp]
                d1[f"f{j}"] = e[kt]
            samps.extend([d0, d1])
        fkeys = [f"f{j}" for j in range(len(feats_p))]
        preds = grouped_loeo(samps, fkeys, gk)
        y = [s["label"] for s in samps]
        auc_v = roc_auc(preds, y)
        lo, hi = bootstrap_auc_ci(samps, preds)
        pw = wilcoxon_p([e[f"t_{diff_key}_q95"] - e[f"p_{diff_key}_q95"] for e in sub])
        summary.append({
            "model_or_stratum": desc,
            "n_events": len(sub),
            "roc_auc": f"{auc_v:.3f}",
            "ci95": f"[{lo:.2f}, {hi:.2f}]",
            "pr_auc": f"{pr_auc(preds, y):.3f}",
            "wilcoxon_p": f"{pw:.4f}",
        })

    sh = [e for e in ev_rows if e["role"] == "PRIMARY_SHALLOW_TARGET"]
    nc = [e for e in ev_rows if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    eval_model("M2a: Raw GNSS ZTD-Only (Shallow Baseline)", sh, ["p_ztd_max", "p_ztd_q95"], ["t_ztd_max", "t_ztd_q95"], "ztd")
    eval_model("M2b: Physical GNSS - ERA5 (ZHD+ZWD) Residual (Shallow)", sh, ["p_raw_max", "p_raw_q95"], ["t_raw_max", "t_raw_q95"], "raw")
    eval_model("M2c: Calibrated GNSS - ERA5 Residual (Shallow, Event-LOEO)", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_model("M2c: Calibrated GNSS - ERA5 Residual (Shallow, Cluster-CV)", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "cluster_id")
    eval_model("M2c: Calibrated GNSS - ERA5 Residual (Null-Control Slab)", nc, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_model("M2c: Calibrated GNSS - ERA5 Residual (Megathrust N=62)", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal")
    eval_model("M2c: Calibrated GNSS - ERA5 Residual (Crustal/Splay N=28)", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal")
    eval_model("M4_era5: Joint ERA5-Resid + Quiet VTEC (Shallow)", sh, ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal")

    with (ANALYSIS_DIR / "stage5e_era5_ablation_summary_v002.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    (OUT_DIR / "STAGE5E_ERA5_DECONFOUNDING_v002.md").write_text("# Stage 5E ECMWF ERA5 Meteorological Deconfounding (v002_era5)\n", encoding="utf-8")
    (OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n$ErrorActionPreference = "Stop"\n'
        'foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {\n'
        '  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }\n'
        '  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n}\n'
        'Write-Host "ALL CHECKS PASSED (Stage 5E ERA5 deconfounding audit verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in ["STAGE5E_ERA5_DECONFOUNDING_v002.md", "VERIFY_PACKAGE.ps1", "analysis/stage5e_era5_event_features_v002.csv", "analysis/stage5e_era5_ablation_summary_v002.csv"]:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])


if __name__ == "__main__":
    main()
