import csv, gzip, hashlib, math, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
sys.path.insert(0, str(ROOT / "scripts"))
from stage4b_scale_full_tier1_cohort_v001 import (
    bilinear_vtec, bootstrap_auc_ci, median_and_mad,
    parse_sinex_trop_hourly, roc_auc,
)

S1D_CAT = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
S2B_ANC = ROOT / "reports/stage2b/coverage_matrix_v001/analysis/event_primary_gnss_anchors_v001.csv"
S2C_COH = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
S4B_EV  = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
IONEX_CACHE = ROOT / "data/external/ionosphere/code_ionex_v001"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
OUT_DIR = ROOT / "reports/stage5b/hardened_audit_v002"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

def unlzw_aligned(data: bytes) -> bytes:
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Invalid .Z header")
    flags = data[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    pos, n_bytes, block_start = 3, len(data), 3
    bit_buf, bits_in_buf, code_size = 0, 0, 9
    clear_code = 256 if block_mode else -1
    next_code = 257 if block_mode else 256
    max_code = 1 << max_bits
    table = {i: bytes([i]) for i in range(256)}
    out = bytearray()
    prev_seq = None

    while True:
        while bits_in_buf < code_size and pos < n_bytes:
            bit_buf |= data[pos] << bits_in_buf
            bits_in_buf += 8
            pos += 1
        if bits_in_buf < code_size:
            break
        code = bit_buf & ((1 << code_size) - 1)
        bit_buf >>= code_size
        bits_in_buf -= code_size

        if block_mode and code == clear_code:
            consumed = (pos - block_start) - (bits_in_buf // 8)
            rem = consumed % code_size
            if rem:
                pos += (code_size - rem)
            block_start = pos
            bit_buf = bits_in_buf = 0
            table = {i: bytes([i]) for i in range(256)}
            code_size = 9
            next_code = 257
            prev_seq = None
            continue
        if prev_seq is None:
            seq = table[code]
            out.extend(seq)
            prev_seq = seq
            continue
        seq = table[code] if code in table else (prev_seq + prev_seq[:1])
        out.extend(seq)
        if next_code < max_code:
            table[next_code] = prev_seq + seq[:1]
            next_code += 1
            if next_code == (1 << code_size) and code_size < max_bits:
                code_size += 1
        prev_seq = seq
    return bytes(out)

def parse_ionex_safe(day_dt: datetime):
    y, doy, yy = day_dt.year, day_dt.timetuple().tm_yday, day_dt.year % 100
    fp = None
    for fn in (f"CODG{doy:03d}0.{yy:02d}I.Z", f"COD0OPSFIN_{y}{doy:03d}0000_01D_01H_GIM.INX.gz"):
        cand = IONEX_CACHE / fn
        if cand.exists() and cand.stat().st_size > 2000:
            fp = cand
            break
    if fp is None:
        return []
    try:
        raw = fp.read_bytes()
        if fp.name.endswith(".gz") or raw[:2] == b"\x1f\x8b":
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
        elif fp.name.endswith(".Z") or raw[:2] == b"\x1f\x9d":
            text = unlzw_aligned(raw).decode("utf-8", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")

        lat1, lat2, dlat = 87.5, -87.5, -2.5
        lon1, lon2, dlon = -180.0, 180.0, 5.0
        exponent = -1
        lines = text.splitlines()
        idx, n_lines = 0, len(lines)
        while idx < n_lines:
            label = lines[idx][60:].strip()
            if label == "END OF HEADER":
                idx += 1; break
            elif label == "LAT1 / LAT2 / DLAT":
                p = lines[idx][:60].split(); lat1, lat2, dlat = float(p[0]), float(p[1]), float(p[2])
            elif label == "LON1 / LON2 / DLON":
                p = lines[idx][:60].split(); lon1, lon2, dlon = float(p[0]), float(p[1]), float(p[2])
            elif label == "EXPONENT":
                exponent = int(lines[idx][:60].strip())
            idx += 1

        scale = 10.0 ** exponent
        n_lats = int(round((lat2 - lat1) / dlat)) + 1
        n_lons = int(round((lon2 - lon1) / dlon)) + 1
        maps = []
        while idx < n_lines:
            if lines[idx][60:].strip() == "START OF TEC MAP":
                idx += 1; epoch_dt = None; grid = []
                while idx < n_lines:
                    mlabel = lines[idx][60:].strip()
                    if mlabel == "END OF TEC MAP":
                        idx += 1; break
                    elif mlabel == "EPOCH OF CURRENT MAP":
                        ep = [int(x) for x in lines[idx][:60].split()]
                        epoch_dt = datetime(ep[0], ep[1], ep[2], 0, ep[4], ep[5], tzinfo=timezone.utc) + timedelta(days=1) if ep[3] == 24 else datetime(ep[0], ep[1], ep[2], ep[3], ep[4], ep[5], tzinfo=timezone.utc)
                        idx += 1
                    elif mlabel == "LAT/LON1/LON2/DLON/H":
                        idx += 1; vals = []
                        while len(vals) < n_lons and idx < n_lines:
                            rs = lines[idx]
                            for k in range(0, min(80, len(rs)), 5):
                                ch = rs[k:k+5].strip()
                                if ch:
                                    v = int(ch)
                                    vals.append(float("nan") if v == 9999 else v * scale)
                            idx += 1
                        grid.append(vals[:n_lons])
                    else:
                        idx += 1
                if epoch_dt is not None and len(grid) == n_lats:
                    maps.append((epoch_dt, lat1, dlat, lon1, dlon, n_lats, n_lons, grid))
            else:
                idx += 1
        return maps
    except Exception:
        return []

def geomag_modip(lat: float, lon: float) -> tuple[float, float]:
    phi, lam = math.radians(lat), math.radians(lon)
    pp, lp = math.radians(80.65), math.radians(-72.68)
    gm = math.asin(max(-1.0, min(1.0, math.sin(phi)*math.sin(pp) + math.cos(phi)*math.cos(pp)*math.cos(lam - lp))))
    modip = math.atan(math.atan(2.0 * math.tan(gm)) / math.sqrt(max(1e-6, math.cos(phi))))
    return math.degrees(gm), math.degrees(modip)

def pr_auc(scores: list[float], labels: list[int]) -> float:
    n_pos = sum(labels)
    if not n_pos: return float("nan")
    tp = fp = 0; prev_r = area = 0.0
    for _, y in sorted(zip(scores, labels), key=lambda x: -x[0]):
        tp += (y == 1); fp += (y == 0)
        r = tp / n_pos
        area += (tp / (tp + fp)) * (r - prev_r)
        prev_r = r
    return area

def wilcoxon_p(diffs: list[float]) -> float:
    nz = sorted([d for d in diffs if abs(d) > 1e-9], key=abs)
    n = len(nz)
    if n < 5: return float("nan")
    w_plus, i = 0.0, 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(nz[j + 1]) - abs(nz[i])) <= 1e-9: j += 1
        rk = 0.5 * (i + j) + 1.0
        w_plus += sum(rk for k in range(i, j + 1) if nz[k] > 0)
        i = j + 1
    z = (w_plus - n*(n + 1)/4.0 - 0.5) / math.sqrt(n*(n + 1)*(2*n + 1)/24.0)
    return 0.5 * math.erfc(z / math.sqrt(2.0))

def grouped_loeo(samples: list[dict], fkeys: list[str], gkey: str = "event_id") -> list[float]:
    preds = [0.5] * len(samples)
    for hg in sorted({s[gkey] for s in samples}):
        tr = [i for i, s in enumerate(samples) if s[gkey] != hg]
        te = [i for i, s in enumerate(samples) if s[gkey] == hg]
        ms, ss = [], []
        for k in fkeys:
            vs = [samples[i][k] for i in tr]
            m = sum(vs) / len(vs)
            ms.append(m)
            ss.append(max(1e-6, math.sqrt(sum((x - m)**2 for x in vs) / max(1, len(vs) - 1))))
        x_tr = [[(samples[i][k] - ms[j]) / ss[j] for j, k in enumerate(fkeys)] for i in tr]
        y_tr = [samples[i]["label"] for i in tr]
        d = len(fkeys); w, b, n_tr = [0.0]*d, 0.0, len(x_tr)
        for _ in range(250):
            gw, gb = [0.0]*d, 0.0
            for xi, yi in zip(x_tr, y_tr):
                z = max(-20.0, min(20.0, b + sum(wj*xij for wj, xij in zip(w, xi))))
                err = (1.0 / (1.0 + math.exp(-z))) - yi
                gb += err
                for j in range(d): gw[j] += err * xi[j]
            b -= 0.08 * (gb / n_tr)
            for j in range(d): w[j] -= 0.08 * ((gw[j] / n_tr) + w[j])
        for i in te:
            xi = [(samples[i][k] - ms[j]) / ss[j] for j, k in enumerate(fkeys)]
            z = max(-20.0, min(20.0, b + sum(wj*xij for wj, xij in zip(w, xi))))
            preds[i] = 1.0 / (1.0 + math.exp(-z))
    return preds

def main() -> None:
    s1d = list(csv.DictReader(S1D_CAT.open(encoding="utf-8-sig")))
    s2b = {r["event_id"]: r for r in csv.DictReader(S2B_ANC.open(encoding="utf-8-sig"))}
    s2c = {r["event_id"]: r for r in csv.DictReader(S2C_COH.open(encoding="utf-8-sig"))}
    s4b = {r["event_id"]: r for r in csv.DictReader(S4B_EV.open(encoding="utf-8-sig"))}

    ledger, counts = [], {}
    for r in s1d:
        eid = r["event_id"]
        r2b, r2c = s2b.get(eid, {}), s2c.get(eid, {})
        if r["stage1d_included_in_pilot_v001"] != "True":
            disp = f"EXCL_STAGE1D_{r['stage1d_analysis_role_v001']}"
        elif r2b.get("stage2b_near_regional_eligible_le_300km") != "True":
            disp = f"EXCL_STAGE2B_{r2b.get('stage2b_coupling_eligibility_tier', 'NO_GNSS')}"
        elif r2c.get("unr_trop_archive_status") == "NO_UNR_TROP_ZIP_IN_TOP2":
            disp = "EXCL_STAGE2C_NO_UNR_TROP_ZIP"
        elif r2c.get("stage2c_benchmark_ready_v001") != "True":
            disp = "EXCL_STAGE2C_QUIET_DAYS_LT_15"
        elif r2b.get("stage2b_coupling_eligibility_tier") != "TIER1_NEAR_FIELD_ELIGIBLE_LE_150KM":
            disp = "DEFERRED_TIER2_150_300KM"
        elif eid not in s4b:
            disp = "EXCL_STAGE4B_QA_OR_UNPAIRED_WINDOW"
        else:
            disp = "INCLUDED_FINAL_111_BENCHMARK"
        counts[disp] = counts.get(disp, 0) + 1
        ledger.append({
            "event_id": eid, "origin_time_utc": r["origin_time_utc"], "magnitude": r["magnitude"],
            "depth_km": r["depth_km"], "latitude_deg": r["latitude_deg"], "longitude_deg": r["longitude_deg"],
            "macro_region": r["frozen_macro_region_v001"], "source_class": r["stage1c4_final_source_class_v001"],
            "analysis_role": r["stage1d_analysis_role_v001"],
            "station_id": r2c.get("verified_gnss_station_id", r2b.get("primary_gnss_station_id", "")),
            "station_km": r2c.get("verified_gnss_distance_km", r2b.get("primary_gnss_distance_km", "")),
            "final_disposition_v002": disp,
        })

    with (ANALYSIS_DIR / "event_attrition_ledger_v002.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ledger[0].keys())); w.writeheader(); w.writerows(ledger)

    omni = {}
    for fp in sorted(OMNI_CACHE.glob("omni2_*.dat")):
        for line in fp.open(encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) < 51: continue
            try:
                y, doy, hr, kp10, dst, f107 = int(p[0]), int(p[1]), int(p[2]), int(p[38]), float(p[40]), float(p[50])
                ts = (datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hr)).strftime("%Y-%m-%dT%H:00:00Z")
                omni[ts] = (kp10/10.0 if 0 <= kp10 <= 90 else None, dst if -1000 <= dst <= 500 else None, f107 if 50 <= f107 <= 400 else None)
            except ValueError: pass

    s1d_map = {r["event_id"]: r for r in s1d}
    paired_evs = sorted(s4b.values(), key=lambda x: x["origin_time_utc"])
    ionex_cache, timelines, clusters = {}, {}, {}
    cid, prev_dt = 0, None

    for ev in paired_evs:
        eid = ev["event_id"]
        m = s1d_map[eid]
        elat, elon = float(m["latitude_deg"]), float(m["longitude_deg"])
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        if prev_dt is None or (ev_dt - prev_dt).days > 15: cid += 1
        clusters[eid], prev_dt = f"C{cid:03d}", ev_dt
        ev_hr = ev_dt.replace(minute=0, second=0, microsecond=0)

        ztd_hr, iwv_hr = {}, {}
        for u in s2c[eid]["unr_trop_urls"].split(";"):
            zp = ZIP_CACHE / u.strip().rstrip("/").split("/")[-1]
            if zp.exists():
                _, zh, ih = parse_sinex_trop_hourly(zp, ev_dt - timedelta(days=45), ev_dt + timedelta(days=5))
                ztd_hr.update(zh); iwv_hr.update(ih)

        vtec_hr = {}
        for off in range(-45, 6):
            d_dt = (ev_dt + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
            dk = d_dt.strftime("%Y-%m-%d")
            if dk not in ionex_cache:
                ionex_cache[dk] = parse_ionex_safe(d_dt)
            for mt in ionex_cache[dk]:
                v = bilinear_vtec(mt, elat, elon)
                if not math.isnan(v): vtec_hr[mt[0].strftime("%Y-%m-%dT%H:00:00Z")] = v

        tl = []
        for h_off in range(-45*24, 5*24 + 1):
            tc = ev_hr + timedelta(hours=h_off)
            ts = tc.strftime("%Y-%m-%dT%H:00:00Z")
            kp, dst, f107 = omni.get(ts, (None, None, None))
            tl.append({"rh": h_off, "h": tc.hour, "q": (kp is not None and dst is not None and kp < 3.0 and dst > -30.0),
                       "f107": f107, "ztd": ztd_hr.get(ts), "iwv": iwv_hr.get(ts), "vtec": vtec_hr.get(ts)})

        pts = [(x["f107"], x["vtec"]) for x in tl if -45*24 <= x["rh"] <= -21*24 - 1 and x["q"] and x["f107"] and x["vtec"]]
        if len(pts) >= 36:
            mx = sum(p[0] for p in pts)/len(pts); my = sum(p[1] for p in pts)/len(pts)
            sxx = sum((p[0] - mx)**2 for p in pts)
            slp = (sum((p[0] - mx)*(p[1] - my) for p in pts) / sxx) if sxx > 1e-6 else 0.0
        else:
            slp, mx = 0.0, 0.0
        for x in tl:
            x["vd"] = (x["vtec"] - slp*(x["f107"] - mx)) if (x["vtec"] is not None and x["f107"] is not None) else x["vtec"]

        gm, modip = geomag_modip(elat, elon)
        timelines[eid] = {"ev": ev, "gm": gm, "modip": modip, "yr": ev_dt.year, "dist": float(ev["verified_gnss_distance_km"]),
                          "role": ev["stage1d_analysis_role_v001"], "src": ev["stage1c4_final_source_class_v001"], "tl": tl}

    def eval_disjoint(lag_d: int, base_d: int):
        b0, b1 = -(2*lag_d + base_d)*24, -(2*lag_d)*24 - 1
        p0, p1 = -(2*lag_d)*24, -lag_d*24 - 1
        t0, t1 = -lag_d*24, -1
        out = []
        for eid, info in timelines.items():
            tl = info["tl"]
            def cal(fld: str, qo: bool):
                pool = [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x[fld] is not None and (not qo or x["q"])]
                if len(pool) < 20: return {}
                gm, gs = median_and_mad(pool)
                return {h: median_and_mad(sub) if len(sub := [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x["h"] == h and x[fld] is not None and (not qo or x["q"])]) >= 2 else (gm, gs) for h in range(24)}
            zc, ic, vc = cal("ztd", False), cal("iwv", False), cal("vd", True)
            def win(e0: int, e1: int):
                zz, iz, vz = [], [], []
                for x in tl:
                    if e0 <= x["rh"] <= e1:
                        if x["ztd"] is not None and x["h"] in zc: zz.append(abs((x["ztd"] - zc[x["h"]][0]) / zc[x["h"]][1]))
                        if x["iwv"] is not None and x["h"] in ic: iz.append(abs((x["iwv"] - ic[x["h"]][0]) / ic[x["h"]][1]))
                        if x["q"] and x["vd"] is not None and x["h"] in vc: vz.append(abs((x["vd"] - vc[x["h"]][0]) / vc[x["h"]][1]))
                return zz, iz, vz
            pz, pi, pv = win(p0, p1); tz, ti, tv = win(t0, t1)
            if min(len(pz), len(tz), len(pv), len(tv)) < 12: continue
            out.append({
                "event_id": eid, "cluster_id": clusters[eid], "role": info["role"], "src": info["src"],
                "gm": info["gm"], "modip": info["modip"], "yr": info["yr"], "dist": info["dist"],
                "p_ztd_max": max(pz), "p_ztd_q95": sorted(pz)[int(0.95*(len(pz)-1))],
                "t_ztd_max": max(tz), "t_ztd_q95": sorted(tz)[int(0.95*(len(tz)-1))],
                "has_iwv": len(pi) >= 12 and len(ti) >= 12,
                "p_iwv_max": max(pi) if pi else 0.0, "p_iwv_q95": sorted(pi)[int(0.95*(len(pi)-1))] if pi else 0.0,
                "t_iwv_max": max(ti) if ti else 0.0, "t_iwv_q95": sorted(ti)[int(0.95*(len(ti)-1))] if ti else 0.0,
                "p_vtec_max": max(pv), "p_vtec_q95": sorted(pv)[int(0.95*(len(pv)-1))],
                "t_vtec_max": max(tv), "t_vtec_q95": sorted(tv)[int(0.95*(len(tv)-1))],
            })
        return out

    summary = []
    def add_row(cat: str, desc: str, sub: list[dict], pref: str, gk: str = "event_id"):
        if len(sub) < 3: return
        samps = []
        for e in sub:
            samps.append({"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 0, "mx": e[f"p_{pref}_max"], "q95": e[f"p_{pref}_q95"]})
            samps.append({"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 1, "mx": e[f"t_{pref}_max"], "q95": e[f"t_{pref}_q95"]})
        preds = grouped_loeo(samps, ["mx", "q95"], gk)
        y = [s["label"] for s in samps]
        auc_v = roc_auc(preds, y); lo, hi = bootstrap_auc_ci(samps, preds)
        summary.append({
            "category": cat, "stratum_or_model": desc, "n_events": len(sub),
            "roc_auc": f"{auc_v:.3f}", "ci95": f"[{lo:.2f}, {hi:.2f}]", "pr_auc": f"{pr_auc(preds, y):.3f}",
            "wilcoxon_p": f"{wilcoxon_p([e[f't_{pref}_q95'] - e[f'p_{pref}_q95'] for e in sub]):.4f}",
            "hit_q95_ge3": f"{sum(1 for e in sub if e[f't_{pref}_q95'] >= 3.0)/len(sub):.1%}",
            "fa_q95_ge3": f"{sum(1 for e in sub if e[f'p_{pref}_q95'] >= 3.0)/len(sub):.1%}",
        })

    for desc, ld, bd in [
        ("Disjoint Fixed Base (L=10d, Base=[-35,-21])", 10, 15),
        ("Disjoint Fixed Base (L=10d, Base=[-45,-21])", 10, 25),
        ("Disjoint Multi-Lag (L=12d, Base=[-39,-25])", 12, 15),
        ("Disjoint Multi-Lag (L=15d, Base=[-45,-31])", 15, 15),
    ]:
        add_row("1_BASELINE_LAG", desc, [e for e in eval_disjoint(ld, bd) if e["role"] == "PRIMARY_SHALLOW_TARGET"], "vtec")

    base = eval_disjoint(10, 15)
    sh = [e for e in base if e["role"] == "PRIMARY_SHALLOW_TARGET"]
    nc = [e for e in base if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    add_row("2_MODELS_CV", "M2a: Troposphere ZTD-Only (Shallow)", sh, "ztd")
    add_row("2_MODELS_CV", "M2b: Troposphere IWV-Only (Shallow)", [e for e in sh if e["has_iwv"]], "iwv")
    add_row("2_MODELS_CV", "M3: Quiet VTEC (Shallow, Event-LOEO)", sh, "vtec", "event_id")
    add_row("2_MODELS_CV", "M3: Quiet VTEC (Shallow, Storm-Cluster CV)", sh, "vtec", "cluster_id")
    add_row("2_MODELS_CV", "M3: Quiet VTEC (Null-Control Slab/Outer)", nc, "vtec", "event_id")

    for desc, sub in [
        ("Shallow: Geomagnetic |gm_lat| <= 25 deg (EIA)", [e for e in sh if abs(e["gm"]) <= 25.0]),
        ("Shallow: Geomagnetic |gm_lat| > 25 deg (Mid-Lat)", [e for e in sh if abs(e["gm"]) > 25.0]),
        ("Shallow: Modified Dip |modip| > 30 deg", [e for e in sh if abs(e["modip"]) > 30.0]),
        ("Shallow: Era 2000-2014 (2-h GIM Cadence)", [e for e in sh if e["yr"] <= 2014]),
        ("Shallow: Era 2015-2025 (1-h GIM Cadence)", [e for e in sh if e["yr"] >= 2015]),
        ("Shallow: Onshore/Near-Coast (<= 50 km)", [e for e in sh if e["dist"] <= 50.0]),
        ("Shallow: Offshore/Regional (50-150 km)", [e for e in sh if e["dist"] > 50.0]),
        ("Shallow: Megathrust Interface (Disjoint)", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"]),
        ("Shallow: Crustal / Splay (Disjoint)", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"]),
    ]:
        add_row("3_GEOMAG_OBSERVABILITY", desc, sub, "vtec")

    with (ANALYSIS_DIR / "stage5b_hardened_audit_summary_v002.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)

    md_lines = ["# Stage 5B Hardened Audit v002\n", "## 1,186-Event Attrition Ledger\n"]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        md_lines.append(f"- `{k}`: **{v}**\n")
    (OUT_DIR / "STAGE5B_HARDENED_AUDIT_v002.md").write_text("".join(md_lines), encoding="utf-8")

    (OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n$ErrorActionPreference = "Stop"\n'
        'foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {\n'
        '  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }\n'
        '  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n}\n'
        'Write-Host "ALL CHECKS PASSED (Stage 5B v002 hardened audit verified)." -ForegroundColor Cyan\n', encoding="utf-8")

    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in ["STAGE5B_HARDENED_AUDIT_v002.md", "VERIFY_PACKAGE.ps1", "analysis/event_attrition_ledger_v002.csv", "analysis/stage5b_hardened_audit_summary_v002.csv"]:
            fp = OUT_DIR / rel; w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

if __name__ == "__main__":
    main()
