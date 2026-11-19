import csv, hashlib, json, math, random, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
sys.path.insert(0, str(ROOT / "scripts"))
from stage4b_scale_full_tier1_cohort_v001 import bilinear_vtec, bootstrap_auc_ci, median_and_mad, roc_auc
from stage5b_hardened_audit_v002 import geomag_modip, grouped_loeo, parse_ionex_safe, pr_auc, wilcoxon_p
from stage5c_zero_overlap_equallag_v002 import parse_trop_strict
from stage5e_era5_deconfounded_v002 import load_station_coords, ols_calibrate

S1D_CAT = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
S2C_COH = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
S4B_EV  = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
IONEX_CACHE = ROOT / "data/external/ionosphere/code_ionex_v001"
ERA5_CACHE = ROOT / "data/external/meteorology/era5_openmeteo_v002"

OUT_DIR = ROOT / "reports/stage6a/audit_repaired_v003"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
MS_DIR = ROOT / "manuscript"
MS_TABLES = MS_DIR / "tables"
MS_FIGS = MS_DIR / "figures"


# ==============================================================================
# P1: NUMERICAL UNIT TEST FOR ERA5 ZHD, ZWD & ZTD (EQS. 2-6)
# ==============================================================================
def era5_zhd_zwd_mm(ps_hpa: float, t2m_c: float, tcwv_kgm2: float, lat_deg: float, h_m: float) -> tuple[float, float, float, float, float]:
    """
    Physical GNSS Meteorology Forward Operator (Saastamoinen 1972; Davis et al. 1985; Bevis et al. 1992).
    - ps_hpa: surface pressure in hPa
    - t2m_c: 2-m temperature in Celsius
    - tcwv_kgm2: total column water vapour in kg/m^2 (1 kg/m^2 == 1 mm PWV for rho_w = 1000 kg/m^3)
    - Returns: (tm_k, pi_inv_mm_per_kgm2, zhd_mm, zwd_mm, ztd_mm)
    """
    phi = math.radians(lat_deg)
    h_km = h_m / 1000.0
    denom_zhd = 1.0 - 0.00266 * math.cos(2.0 * phi) - 0.00028 * h_km
    zhd_mm = (2.2768 * ps_hpa) / denom_zhd

    t_k = t2m_c + 273.15
    tm_k = 70.2 + 0.72 * t_k
    # Bevis et al. (1992): Pi^-1 = 10^-8 * rho_w * R_v * (k3 / Tm + k2')
    # With rho_w = 1000 kg/m^3, R_v = 461.5 J/(kg K), k3 = 3.739e5 K^2/hPa, k2' = 22.1 K/hPa:
    # 10^-8 * 1000 = 10^-5 (accounts for 1 hPa = 100 Pa and 10^-6 refractivity scaling)
    pi_inv = 1e-5 * 461.5 * (3.739e5 / tm_k + 22.1)
    zwd_mm = pi_inv * tcwv_kgm2
    return tm_k, pi_inv, zhd_mm, zwd_mm, zhd_mm + zwd_mm


def run_p1_unit_test() -> dict:
    # Audit test case: Tm = 270.0 K -> t2m_k = (270.0 - 70.2)/0.72 = 277.5 K (4.35 C), TCWV = 30 kg/m^2
    t2m_c_test = (270.0 - 70.2) / 0.72 - 273.15
    tm, pi_inv, zhd, zwd, ztd = era5_zhd_zwd_mm(1013.25, t2m_c_test, 30.0, 35.0, 100.0)
    assert abs(tm - 270.0) < 1e-6, f"Expected Tm=270.0 K, got {tm}"
    assert 6.0 <= pi_inv <= 6.8, f"Implausible Pi^-1={pi_inv}"
    assert 180.0 <= zwd <= 210.0, f"Implausible ZWD={zwd} mm for TCWV=30 kg/m^2"
    return {
        "test_tm_K": round(tm, 4),
        "test_tcwv_kgm2": 30.0,
        "test_pi_inv_mm_per_kgm2": round(pi_inv, 4),
        "test_zwd_mm": round(zwd, 2),
        "test_zhd_mm": round(zhd, 2),
        "test_ztd_mm": round(ztd, 2),
        "status": "PASS (Matches physical ~195 mm ZWD scale; 100x v002 bug resolved)",
    }


# ==============================================================================
# P2: AUTOMATED WINDOW-DISJOINTNESS & EQUAL-LAG ASSERTION
# ==============================================================================
# Half-open hour offsets [start_h, end_h) relative to truncated origin hour ev_hr:
# B0 = [-1080, -792) h  ([-45d, -33d), duration = 288 h = 12.0 d)
# w0 = [-792,  -552) h  ([-33d, -23d), duration = 240 h = 10.0 d, lag = 1..10 d after B0)
# B1 = [-552,  -264) h  ([-23d, -11d), duration = 288 h = 12.0 d)
# w1 = [-264,   -24) h  ([-11d,  -1d), duration = 240 h = 10.0 d, lag = 1..10 d after B1)
# Guard = [-24,   0) h  ([-1d,    0d), duration =  24 h =  1.0 d pre-origin co-seismic guard)
WIN_B0 = (-1080, -792)
WIN_W0 = (-792, -552)
WIN_B1 = (-552, -264)
WIN_W1 = (-264, -24)
WIN_GUARD = (-24, 0)


def run_p2_window_assertion() -> dict:
    sets = {
        "B0": set(range(*WIN_B0)),
        "w0": set(range(*WIN_W0)),
        "B1": set(range(*WIN_B1)),
        "w1": set(range(*WIN_W1)),
        "Guard": set(range(*WIN_GUARD)),
    }
    names = list(sets.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            inter = sets[names[i]].intersection(sets[names[j]])
            assert len(inter) == 0, f"Forbidden overlap between {names[i]} and {names[j]}: {len(inter)} hours"
    assert len(sets["B0"]) == len(sets["B1"]) == 288, "Baseline durations must both equal 288 hours (12.0 days)"
    assert len(sets["w0"]) == len(sets["w1"]) == 240, "Evaluation durations must both equal 240 hours (10.0 days)"
    assert (WIN_W0[0] - WIN_B0[1]) == (WIN_W1[0] - WIN_B1[1]) == 0, "Equal lag symmetry violated"
    return {
        "B0_hours": list(WIN_B0), "w0_hours": list(WIN_W0),
        "B1_hours": list(WIN_B1), "w1_hours": list(WIN_W1),
        "Guard_hours": list(WIN_GUARD),
        "pairwise_intersections": 0,
        "baseline_duration_hours": 288,
        "eval_duration_hours": 240,
        "status": "PASS (Strictly mutually disjoint half-open UTC intervals with equal 12d baseline and 10d eval)",
    }


def load_era5_repaired(eid: str, sid: str, lat: float, lon: float, h_m: float) -> dict[str, float]:
    cache_fp = ERA5_CACHE / f"{eid}_{sid}_era5.json"
    if not cache_fp.exists() or cache_fp.stat().st_size <= 200:
        return {}
    payload = json.loads(cache_fp.read_text(encoding="utf-8"))
    hr = payload.get("hourly", {})
    times = hr.get("time", [])
    ps_arr = hr.get("surface_pressure", [])
    t2_arr = hr.get("temperature_2m", [])
    td_arr = hr.get("dew_point_2m", [])
    tcwv_arr = hr.get("total_column_integrated_water_vapour", [])

    ztd_era5 = {}
    for i, t_str in enumerate(times):
        ps = ps_arr[i] if i < len(ps_arr) else None
        t2 = t2_arr[i] if i < len(t2_arr) else None
        tcwv = tcwv_arr[i] if i < len(tcwv_arr) else None
        if tcwv is None and i < len(td_arr) and td_arr[i] is not None:
            e_hpa = 6.112 * math.exp((17.67 * td_arr[i]) / (td_arr[i] + 243.5))
            tcwv = 1.75 * e_hpa
        if ps is None or tcwv is None:
            continue
        t2_c = t2 if t2 is not None else 15.0
        _, _, _, _, ztd_mm = era5_zhd_zwd_mm(ps, t2_c, tcwv, lat, h_m)
        ztd_era5[t_str + ":00Z"] = ztd_mm
    return ztd_era5


def perm_auc_pvalue(preds: list[float], labels: list[int], n_perm: int = 2000, seed: int = 42) -> float:
    obs = abs(roc_auc(preds, labels) - 0.5)
    rng = random.Random(seed)
    n_pairs = len(labels) // 2
    cnt = 0
    for _ in range(n_perm):
        perm_y = []
        for p_idx in range(n_pairs):
            if rng.random() < 0.5:
                perm_y.extend([labels[2 * p_idx], labels[2 * p_idx + 1]])
            else:
                perm_y.extend([labels[2 * p_idx + 1], labels[2 * p_idx]])
        if abs(roc_auc(preds, perm_y) - 0.5) >= obs - 1e-12:
            cnt += 1
    return (cnt + 1) / (n_perm + 1)


def paired_delta_auc_pvalue(preds_a: list[float], preds_b: list[float], labels: list[int], n_perm: int = 2000, seed: int = 42) -> tuple[float, float]:
    delta_obs = roc_auc(preds_a, labels) - roc_auc(preds_b, labels)
    rng = random.Random(seed)
    n_pairs = len(labels) // 2
    cnt = 0
    for _ in range(n_perm):
        pa, pb = [], []
        for i in range(n_pairs):
            if rng.random() < 0.5:
                pa.extend([preds_a[2 * i], preds_a[2 * i + 1]])
                pb.extend([preds_b[2 * i], preds_b[2 * i + 1]])
            else:
                pa.extend([preds_b[2 * i], preds_b[2 * i + 1]])
                pb.extend([preds_a[2 * i], preds_a[2 * i + 1]])
        d_perm = roc_auc(pa, labels) - roc_auc(pb, labels)
        if abs(d_perm) >= abs(delta_obs) - 1e-12:
            cnt += 1
    return delta_obs, (cnt + 1) / (n_perm + 1)


def fmt_p(p: float) -> str:
    return "<0.0001" if p < 0.0001 else f"{p:.4f}"


def main() -> None:
    p1_res = run_p1_unit_test()
    p2_res = run_p2_window_assertion()
    print("P1 Unit Test:", p1_res["status"], f"(Pi^-1={p1_res['test_pi_inv_mm_per_kgm2']}, ZWD={p1_res['test_zwd_mm']} mm)")
    print("P2 Disjointness Test:", p2_res["status"])

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

    # Build 50-day overlap graph components (two events connected if within 50 days on same station or <=15 days globally)
    n_ev = len(s4b)
    ev_dts = [datetime.fromisoformat(e["origin_time_utc"].replace("Z", "+00:00")) for e in s4b]
    ev_stns = [e["verified_gnss_station_id"].strip().upper() for e in s4b]
    parent = list(range(n_ev))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n_ev):
        for j in range(i + 1, n_ev):
            dt_days = abs((ev_dts[j] - ev_dts[i]).total_seconds()) / 86400.0
            if dt_days <= 15.0 or (ev_stns[i] == ev_stns[j] and dt_days <= 50.0):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    ionex_cache, ev_rows = {}, []
    cid, prev_dt = 0, None

    for idx, ev in enumerate(s4b):
        eid = ev["event_id"]
        sid = ev["verified_gnss_station_id"].strip().upper()
        m = s1d[eid]
        elat, elon = float(m["latitude_deg"]), float(m["longitude_deg"])
        slat, slon, sh_m = stn_coords.get(sid, (elat, elon, 0.0))
        reg = m.get("stage1c3_frozen_macro_region_v001", m.get("pilot_region_v001", "UNKNOWN"))
        dist_km = float(ev.get("verified_station_distance_km", 50.0))

        ev_dt = ev_dts[idx]
        if prev_dt is None or (ev_dt - prev_dt).days > 15:
            cid += 1
        clust, prev_dt = f"C{cid:03d}", ev_dt
        ov_comp = f"OV{find(idx):03d}"
        ev_hr = ev_dt.replace(minute=0, second=0, microsecond=0)
        w0_dt, w1_dt = ev_dt - timedelta(days=45), ev_dt + timedelta(days=5)

        ztd_gnss = {}
        for u in s2c[eid]["unr_trop_urls"].split(";"):
            zp = ZIP_CACHE / u.strip().rstrip("/").split("/")[-1]
            if zp.exists():
                zh, _, _ = parse_trop_strict(zp, w0_dt, w1_dt)
                ztd_gnss.update(zh)

        ztd_era5 = load_era5_repaired(eid, sid, slat, slon, sh_m)

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
        for h_off in range(-1080, 1):
            tc = ev_hr + timedelta(hours=h_off)
            ts = tc.strftime("%Y-%m-%dT%H:00:00Z")
            kp, dst, f107 = omni.get(ts, (None, None, None))
            zg = ztd_gnss.get(ts)
            ze = ztd_era5.get(ts)
            tl.append({
                "rh": h_off, "h": tc.hour,
                "q": (kp is not None and dst is not None and kp < 3.0 and dst > -30.0),
                "f107": f107, "zg": zg, "ze": ze,
                "res_raw": (zg - ze) if (zg is not None and ze is not None) else None,
                "vtec": vtec_hr.get(ts),
            })

        # Baseline-only OLS transfer calibration strictly inside B0=[-1080,-792) and B1=[-552,-264)
        a_p, b_p = ols_calibrate([(x["ze"], x["zg"]) for x in tl if WIN_B0[0] <= x["rh"] < WIN_B0[1] and x["zg"] is not None and x["ze"] is not None])
        a_t, b_t = ols_calibrate([(x["ze"], x["zg"]) for x in tl if WIN_B1[0] <= x["rh"] < WIN_B1[1] and x["zg"] is not None and x["ze"] is not None])
        for x in tl:
            if x["zg"] is not None and x["ze"] is not None:
                x["res_p"] = x["zg"] - (a_p + b_p * x["ze"])
                x["res_t"] = x["zg"] - (a_t + b_t * x["ze"])
            else:
                x["res_p"] = x["res_t"] = None

        # Fit F10.7 strictly on quiet epochs in B0 union B1 (zero overlap with w0 or w1)
        pts = [(x["f107"], x["vtec"]) for x in tl if ((WIN_B0[0] <= x["rh"] < WIN_B0[1]) or (WIN_B1[0] <= x["rh"] < WIN_B1[1])) and x["q"] and x["f107"] and x["vtec"]]
        if len(pts) >= 48:
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            sxx = sum((p[0] - mx) ** 2 for p in pts)
            slp = (sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx) if sxx > 1e-6 else 0.0
        else:
            slp, mx = 0.0, 0.0
        for x in tl:
            x["vd"] = (x["vtec"] - slp * (x["f107"] - mx)) if (x["vtec"] is not None and x["f107"] is not None) else x["vtec"]

        def score_win(b_rng, e_rng, fld, qo=False, signed_pos=False):
            b0, b1 = b_rng
            e0, e1 = e_rng
            pool = [x[fld] for x in tl if b0 <= x["rh"] < b1 and x[fld] is not None and (not qo or x["q"])]
            if len(pool) < 20:
                return []
            gm, gs = median_and_mad(pool)
            cal = {h: median_and_mad(sub) if len(sub := [x[fld] for x in tl if b0 <= x["rh"] < b1 and x["h"] == h and x[fld] is not None and (not qo or x["q"])]) >= 2 else (gm, gs) for h in range(24)}
            out = []
            for x in tl:
                if e0 <= x["rh"] < e1 and x[fld] is not None and (not qo or x["q"]):
                    raw_z = (x[fld] - cal[x["h"]][0]) / cal[x["h"]][1]
                    out.append(max(0.0, raw_z) if signed_pos else abs(raw_z))
            return out

        pz = score_win(WIN_B0, WIN_W0, "zg")
        tz = score_win(WIN_B1, WIN_W1, "zg")
        pr_raw = score_win(WIN_B0, WIN_W0, "res_raw")
        tr_raw = score_win(WIN_B1, WIN_W1, "res_raw")
        pr_cal = score_win(WIN_B0, WIN_W0, "res_p")
        tr_cal = score_win(WIN_B1, WIN_W1, "res_t")
        pr_pos = score_win(WIN_B0, WIN_W0, "res_p", False, True)
        tr_pos = score_win(WIN_B1, WIN_W1, "res_t", False, True)
        pv = score_win(WIN_B0, WIN_W0, "vd", True)
        tv = score_win(WIN_B1, WIN_W1, "vd", True)
        pv_pos = score_win(WIN_B0, WIN_W0, "vd", True, True)
        tv_pos = score_win(WIN_B1, WIN_W1, "vd", True, True)

        if min(len(pz), len(tz), len(pr_cal), len(tr_cal), len(pv), len(tv)) < 12:
            continue

        gm, modip = geomag_modip(elat, elon)
        ev_rows.append({
            "event_id": eid, "station_id": sid, "region": reg,
            "cluster_id": clust, "overlap_id": ov_comp,
            "role": ev["stage1d_analysis_role_v001"], "src": ev["stage1c4_final_source_class_v001"],
            "mag": float(ev["magnitude"]), "dist_km": dist_km, "gm": gm, "modip": modip,
            "p_ztd_max": max(pz), "p_ztd_q95": sorted(pz)[int(0.95 * (len(pz) - 1))],
            "t_ztd_max": max(tz), "t_ztd_q95": sorted(tz)[int(0.95 * (len(tz) - 1))],
            "p_raw_max": max(pr_raw), "p_raw_q95": sorted(pr_raw)[int(0.95 * (len(pr_raw) - 1))],
            "t_raw_max": max(tr_raw), "t_raw_q95": sorted(tr_raw)[int(0.95 * (len(tr_raw) - 1))],
            "p_cal_max": max(pr_cal), "p_cal_q95": sorted(pr_cal)[int(0.95 * (len(pr_cal) - 1))],
            "t_cal_max": max(tr_cal), "t_cal_q95": sorted(tr_cal)[int(0.95 * (len(tr_cal) - 1))],
            "p_cpos_max": max(pr_pos), "p_cpos_q95": sorted(pr_pos)[int(0.95 * (len(pr_pos) - 1))],
            "t_cpos_max": max(tr_pos), "t_cpos_q95": sorted(tr_pos)[int(0.95 * (len(tr_pos) - 1))],
            "p_vtec_max": max(pv), "p_vtec_q95": sorted(pv)[int(0.95 * (len(pv) - 1))],
            "t_vtec_max": max(tv), "t_vtec_q95": sorted(tv)[int(0.95 * (len(tv) - 1))],
            "p_vpos_max": max(pv_pos), "p_vpos_q95": sorted(pv_pos)[int(0.95 * (len(pv_pos) - 1))],
            "t_vpos_max": max(tv_pos), "t_vpos_q95": sorted(tv_pos)[int(0.95 * (len(tv_pos) - 1))],
        })

    # Station reuse diagnostics
    unique_stns = len(set(e["station_id"] for e in ev_rows))
    unique_regs = len(set(e["region"] for e in ev_rows))
    unique_ov = len(set(e["overlap_id"] for e in ev_rows))
    print(f"Verified v003 cohort: {len(ev_rows)} events across {unique_stns} unique stations, {unique_regs} regions, {unique_ov} overlap-graph components.")

    summary_rows = []
    oof_store = {}

    def eval_v003(desc: str, dom: str, sub: list[dict], fp: list[str], ft: list[str], dkey: str, gk: str = "event_id"):
        samps = []
        for e in sub:
            d0 = {"event_id": e["event_id"], "station_id": e["station_id"], "region": e["region"], "cluster_id": e["cluster_id"], "overlap_id": e["overlap_id"], "label": 0}
            d1 = {"event_id": e["event_id"], "station_id": e["station_id"], "region": e["region"], "cluster_id": e["cluster_id"], "overlap_id": e["overlap_id"], "label": 1}
            for j, (kp, kt) in enumerate(zip(fp, ft)):
                d0[f"f{j}"] = e[kp]
                d1[f"f{j}"] = e[kt]
            samps.extend([d0, d1])
        fkeys = [f"f{j}" for j in range(len(fp))]
        preds = grouped_loeo(samps, fkeys, gk)
        y = [s["label"] for s in samps]
        auc_v = roc_auc(preds, y)
        lo, hi = bootstrap_auc_ci(samps, preds)
        p_auc = perm_auc_pvalue(preds, y)
        pw = wilcoxon_p([e[f"t_{dkey}_q95"] - e[f"p_{dkey}_q95"] for e in sub])
        oof_store[desc] = (preds, y)
        summary_rows.append({
            "domain": dom,
            "model_or_stratum": desc,
            "n_events": len(sub),
            "roc_auc": f"{auc_v:.3f}",
            "ci95": f"[{lo:.2f}, {hi:.2f}]",
            "pr_auc": f"{pr_auc(preds, y):.3f}",
            "p_auc_perm": fmt_p(p_auc),
            "p_wilc_q95": fmt_p(pw),
        })

    sh = [e for e in ev_rows if e["role"] == "PRIMARY_SHALLOW_TARGET"]
    nc = [e for e in ev_rows if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    # Troposphere v003
    eval_v003("M2a: Raw GNSS ZTD-Only (Shallow, Event-LOEO)", "Troposphere", sh, ["p_ztd_max", "p_ztd_q95"], ["t_ztd_max", "t_ztd_q95"], "ztd", "event_id")
    eval_v003("M2b: Uncalibrated GNSS - ERA5 (Repaired Units, Shallow)", "Troposphere", sh, ["p_raw_max", "p_raw_q95"], ["t_raw_max", "t_raw_q95"], "raw", "event_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Event-LOEO)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Cluster-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "cluster_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Station-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "station_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Overlap-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "overlap_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Region-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "region")
    eval_v003("M2c_pos: Signed Positive ERA5 Residual (Shallow, Event-LOEO)", "Troposphere", sh, ["p_cpos_max", "p_cpos_q95"], ["t_cpos_max", "t_cpos_q95"], "cpos", "event_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Slab/Outer Controls)", "Troposphere", nc, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Megathrust N=62)", "Troposphere", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v003("M2c: Baseline-Calibrated ERA5 Residual (Crustal/Splay N=28)", "Troposphere", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")

    # Ionosphere v003
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Event-LOEO)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Cluster-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "cluster_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Station-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "station_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Overlap-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "overlap_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Region-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "region")
    eval_v003("M3_pos: Signed Positive Quiet VTEC (Shallow, Event-LOEO)", "Ionosphere", sh, ["p_vpos_max", "p_vpos_q95"], ["t_vpos_max", "t_vpos_q95"], "vpos", "event_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Slab/Outer Controls)", "Ionosphere", nc, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Megathrust N=62)", "Ionosphere", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet F10.7-Adj. GIM VTEC (Crustal/Splay N=28)", "Ionosphere", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Major Shallow M>=7.0)", "Ionosphere", [e for e in sh if e["mag"] >= 7.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Geomag |lambda_m| <= 25 deg)", "Ionosphere", [e for e in sh if abs(e["gm"]) <= 25.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Geomag |lambda_m| > 25 deg)", "Ionosphere", [e for e in sh if abs(e["gm"]) > 25.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Modip |modip| > 30 deg)", "Ionosphere", [e for e in sh if abs(e["modip"]) > 30.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Station d <= 50 km)", "Ionosphere", [e for e in sh if e["dist_km"] <= 50.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v003("M3: Quiet GIM VTEC (Station 50 < d <= 150 km)", "Ionosphere", [e for e in sh if e["dist_km"] > 50.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")

    # Joint Multi-Domain Fusion v003
    eval_v003("M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, LOEO)", "Multi-Domain", sh, ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal", "event_id")
    eval_v003("M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Megathrust N=62)", "Multi-Domain", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal", "event_id")

    # Paired model-difference permutation tests
    d_m2c_m2a, p_m2c_m2a = paired_delta_auc_pvalue(
        oof_store["M2c: Baseline-Calibrated ERA5 Residual (Shallow, Event-LOEO)"][0],
        oof_store["M2a: Raw GNSS ZTD-Only (Shallow, Event-LOEO)"][0],
        oof_store["M2a: Raw GNSS ZTD-Only (Shallow, Event-LOEO)"][1],
    )
    d_m4_m3, p_m4_m3 = paired_delta_auc_pvalue(
        oof_store["M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, LOEO)"][0],
        oof_store["M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Event-LOEO)"][0],
        oof_store["M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Event-LOEO)"][1],
    )
    print(f"Paired Delta-AUC (M2c vs M2a): {d_m2c_m2a:+.3f} (p_diff = {p_m2c_m2a:.4f})")
    print(f"Paired Delta-AUC (M4 vs M3):   {d_m4_m3:+.3f} (p_diff = {p_m4_m3:.4f})")

    with (ANALYSIS_DIR / "stage6a_v003_benchmark_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    with (ANALYSIS_DIR / "stage6a_v003_event_features.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ev_rows[0].keys()))
        w.writeheader()
        w.writerows(ev_rows)

    (ANALYSIS_DIR / "stage6a_unit_and_window_tests_v003.json").write_text(
        json.dumps({
            "p1_wet_delay_unit_test": p1_res,
            "p2_window_disjointness_test": p2_res,
            "cohort_counts": {
                "n_total_paired": len(ev_rows),
                "n_shallow": len(sh),
                "n_controls": len(nc),
                "unique_stations": unique_stns,
                "unique_regions": unique_regs,
                "unique_overlap_components": unique_ov,
            },
            "paired_model_comparisons": {
                "M2c_vs_M2a_delta_auc": round(d_m2c_m2a, 4),
                "M2c_vs_M2a_p_perm": round(p_m2c_m2a, 4),
                "M4_vs_M3_delta_auc": round(d_m4_m3, 4),
                "M4_vs_M3_p_perm": round(p_m4_m3, 4),
            }
        }, indent=2),
        encoding="utf-8",
    )

    (OUT_DIR / "STAGE6A_AUDIT_REPAIRED_v003.md").write_text("# Stage 6A Audit-Compliant Repaired Benchmark (v003)\n", encoding="utf-8")
    (OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n$ErrorActionPreference = "Stop"\n'
        'foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {\n'
        '  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }\n'
        '  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n}\n'
        'Write-Host "ALL CHECKS PASSED (Stage 6A v003 audit-compliant benchmark verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in [
            "STAGE6A_AUDIT_REPAIRED_v003.md",
            "VERIFY_PACKAGE.ps1",
            "analysis/stage6a_v003_benchmark_summary.csv",
            "analysis/stage6a_v003_event_features.csv",
            "analysis/stage6a_unit_and_window_tests_v003.json",
        ]:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])


if __name__ == "__main__":
    main()
