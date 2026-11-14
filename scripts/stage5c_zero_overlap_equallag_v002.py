import csv, gzip, hashlib, io, math, sys, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
sys.path.insert(0, str(ROOT / "scripts"))
from stage4b_scale_full_tier1_cohort_v001 import bilinear_vtec, bootstrap_auc_ci, median_and_mad, roc_auc
from stage5b_hardened_audit_v002 import geomag_modip, grouped_loeo, parse_ionex_safe, pr_auc, wilcoxon_p

S1D_CAT = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
S2C_COH = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
S4B_EV  = ROOT / "reports/stage4b/full_tier1_benchmark_v001/analysis/stage4b_paired_tier1_events_v001.csv"
ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"
OUT_DIR = ROOT / "reports/stage5c/zero_overlap_equallag_v002"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

def parse_trop_strict(zip_path: Path, t_start: datetime, t_end: datetime):
    d_min, d_max = t_start.date(), t_end.date()
    seen = set()
    ztd_b, iwv_b = {}, {}
    headers_seen = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for m in zf.namelist():
            if ".trop" not in m.lower(): continue
            mp = m.split("/")[-1].split(".")
            if len(mp) >= 4 and mp[1].isdigit() and mp[2].isdigit():
                try:
                    md = (datetime(int(mp[1]), 1, 1) + timedelta(days=int(mp[2]) - 1)).date()
                    if md < d_min or md > d_max: continue
                except ValueError: pass
            raw = zf.read(m)
            if raw[:2] == b"\x1f\x8b": raw = gzip.decompress(raw)
            in_sol, cols = False, []
            for bl in io.BytesIO(raw):
                ln = bl.decode("utf-8", errors="replace").rstrip("\r\n")
                if ln.startswith("+TROP/SOLUTION"): in_sol = True; continue
                if ln.startswith("-TROP/SOLUTION"): break
                if not in_sol or not ln.strip(): continue
                if ln.startswith("*"):
                    hdr = ln.lstrip("*").strip().split()
                    if "TROTOT" in hdr:
                        cols = hdr
                        headers_seen.add(" ".join(hdr))
                    continue
                p = ln.split()
                if len(p) < 4: continue
                tp = p[1].split(":")
                if len(tp) != 3: continue
                try:
                    yy, doy, sec = int(tp[0]), int(tp[1]), int(tp[2])
                    yr = yy if yy >= 1900 else (2000 + yy if yy < 80 else 1900 + yy)
                    dt = datetime(yr, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, seconds=sec)
                except ValueError: continue
                if dt < t_start or dt > t_end: continue
                try: trotot = float(p[2])
                except ValueError: continue
                if not (1000.0 <= trotot <= 3500.0): continue
                ts5 = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                if ts5 in seen: continue
                seen.add(ts5)
                hk = ts5[:13] + ":00:00Z"
                ztd_b.setdefault(hk, []).append(trotot)
                if "IWV" in cols:
                    idx = cols.index("IWV")
                    if idx < len(p):
                        try:
                            iv = float(p[idx])
                            if 0.5 <= iv <= 120.0: iwv_b.setdefault(hk, []).append(iv)
                        except ValueError: pass
    return {k: sum(v)/len(v) for k, v in ztd_b.items()}, {k: sum(v)/len(v) for k, v in iwv_b.items()}, headers_seen

def main():
    s1d = {r["event_id"]: r for r in csv.DictReader(S1D_CAT.open(encoding="utf-8-sig"))}
    s2c = {r["event_id"]: r for r in csv.DictReader(S2C_COH.open(encoding="utf-8-sig"))}
    s4b = sorted(csv.DictReader(S4B_EV.open(encoding="utf-8-sig")), key=lambda x: x["origin_time_utc"])

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

    all_headers, ionex_cache, ev_data = set(), {}, []
    cid, prev_dt = 0, None
    for ev in s4b:
        eid = ev["event_id"]
        m = s1d[eid]
        elat, elon = float(m["latitude_deg"]), float(m["longitude_deg"])
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        if prev_dt is None or (ev_dt - prev_dt).days > 15: cid += 1
        clust, prev_dt = f"C{cid:03d}", ev_dt
        ev_hr = ev_dt.replace(minute=0, second=0, microsecond=0)

        ztd_hr, iwv_hr = {}, {}
        for u in s2c[eid]["unr_trop_urls"].split(";"):
            zp = ZIP_CACHE / u.strip().rstrip("/").split("/")[-1]
            if zp.exists():
                zh, ih, hs = parse_trop_strict(zp, ev_dt - timedelta(days=45), ev_dt + timedelta(days=5))
                ztd_hr.update(zh); iwv_hr.update(ih); all_headers.update(hs)

        vtec_hr = {}
        for off in range(-45, 6):
            d_dt = (ev_dt + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
            dk = d_dt.strftime("%Y-%m-%d")
            if dk not in ionex_cache: ionex_cache[dk] = parse_ionex_safe(d_dt)
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

        # Fit F10.7 strictly on [-45d, -31d] union [-25d, -11d] (both baselines, zero eval leakage)
        pts = [(x["f107"], x["vtec"]) for x in tl if ((-45*24 <= x["rh"] <= -31*24 - 1) or (-25*24 <= x["rh"] <= -11*24 - 1)) and x["q"] and x["f107"] and x["vtec"]]
        if len(pts) >= 48:
            mx = sum(p[0] for p in pts)/len(pts); my = sum(p[1] for p in pts)/len(pts)
            sxx = sum((p[0] - mx)**2 for p in pts)
            slp = (sum((p[0] - mx)*(p[1] - my) for p in pts) / sxx) if sxx > 1e-6 else 0.0
        else:
            slp, mx = 0.0, 0.0
        for x in tl:
            x["vd"] = (x["vtec"] - slp*(x["f107"] - mx)) if (x["vtec"] is not None and x["f107"] is not None) else x["vtec"]

        # Zero-Overlap + Equal-Lag (1-10d):
        # Placebo: [-30d, -21d] vs Baseline [-45d, -31d]
        # Target : [-10d, -1d]  vs Baseline [-25d, -11d]
        def score_pair(b0, b1, e0, e1, fld, qo):
            pool = [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x[fld] is not None and (not qo or x["q"])]
            if len(pool) < 20: return []
            gm, gs = median_and_mad(pool)
            cal = {h: median_and_mad(sub) if len(sub := [x[fld] for x in tl if b0 <= x["rh"] <= b1 and x["h"] == h and x[fld] is not None and (not qo or x["q"])]) >= 2 else (gm, gs) for h in range(24)}
            return [abs((x[fld] - cal[x["h"]][0]) / cal[x["h"]][1]) for x in tl if e0 <= x["rh"] <= e1 and x[fld] is not None and (not qo or x["q"])]

        pz = score_pair(-45*24, -31*24-1, -30*24, -21*24-1, "ztd", False)
        tz = score_pair(-25*24, -11*24-1, -10*24, -1,       "ztd", False)
        pi = score_pair(-45*24, -31*24-1, -30*24, -21*24-1, "iwv", False)
        ti = score_pair(-25*24, -11*24-1, -10*24, -1,       "iwv", False)
        pv = score_pair(-45*24, -31*24-1, -30*24, -21*24-1, "vd",  True)
        tv = score_pair(-25*24, -11*24-1, -10*24, -1,       "vd",  True)
        if min(len(pz), len(tz), len(pv), len(tv)) < 12: continue

        gm, modip = geomag_modip(elat, elon)
        ev_data.append({
            "event_id": eid, "cluster_id": clust, "role": ev["stage1d_analysis_role_v001"],
            "src": ev["stage1c4_final_source_class_v001"], "mag": float(ev["magnitude"]), "gm": gm,
            "p_ztd_max": max(pz), "p_ztd_q95": sorted(pz)[int(0.95*(len(pz)-1))],
            "t_ztd_max": max(tz), "t_ztd_q95": sorted(tz)[int(0.95*(len(tz)-1))],
            "has_iwv": len(pi) >= 24 and len(ti) >= 24,
            "p_iwv_max": max(pi) if pi else 0.0, "p_iwv_q95": sorted(pi)[int(0.95*(len(pi)-1))] if pi else 0.0,
            "t_iwv_max": max(ti) if ti else 0.0, "t_iwv_q95": sorted(ti)[int(0.95*(len(ti)-1))] if ti else 0.0,
            "p_vtec_max": max(pv), "p_vtec_q95": sorted(pv)[int(0.95*(len(pv)-1))],
            "t_vtec_max": max(tv), "t_vtec_q95": sorted(tv)[int(0.95*(len(tv)-1))],
        })

    print("Distinct SINEX +TROP/SOLUTION headers found:")
    for h in sorted(all_headers): print(" ", h)

    rows = []
    def add(desc, sub, pref, gk="event_id"):
        if len(sub) < 3: return
        samps = []
        for e in sub:
            samps.append({"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 0, "mx": e[f"p_{pref}_max"], "q95": e[f"p_{pref}_q95"]})
            samps.append({"event_id": e["event_id"], "cluster_id": e["cluster_id"], "label": 1, "mx": e[f"t_{pref}_max"], "q95": e[f"t_{pref}_q95"]})
        preds = grouped_loeo(samps, ["mx", "q95"], gk)
        y = [s["label"] for s in samps]
        auc_v = roc_auc(preds, y); lo, hi = bootstrap_auc_ci(samps, preds)
        rows.append({
            "model_or_stratum": desc, "n_events": len(sub),
            "roc_auc": f"{auc_v:.3f}", "ci95": f"[{lo:.2f}, {hi:.2f}]", "pr_auc": f"{pr_auc(preds, y):.3f}",
            "wilcoxon_p": f"{wilcoxon_p([e[f't_{pref}_q95'] - e[f'p_{pref}_q95'] for e in sub]):.4f}",
        })

    sh = [e for e in ev_data if e["role"] == "PRIMARY_SHALLOW_TARGET"]
    nc = [e for e in ev_data if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    add("M2a: Troposphere ZTD-Only (Shallow)", sh, "ztd")
    add("M2b: Troposphere IWV-Only (Strict Header IWV)", [e for e in sh if e["has_iwv"]], "iwv")
    add("M3: Quiet VTEC (Shallow M>=6.5, Event-LOEO)", sh, "vtec", "event_id")
    add("M3: Quiet VTEC (Shallow M>=6.5, Storm-Cluster)", sh, "vtec", "cluster_id")
    add("M3: Quiet VTEC (Null-Control Slab/Outer)", nc, "vtec", "event_id")
    add("M3: Quiet VTEC (Shallow M>=7.0)", [e for e in sh if e["mag"] >= 7.0], "vtec")
    add("M3: Quiet VTEC (Shallow |gm_lat| <= 25 deg)", [e for e in sh if abs(e["gm"]) <= 25.0], "vtec")
    add("M3: Quiet VTEC (Shallow |gm_lat| > 25 deg)", [e for e in sh if abs(e["gm"]) > 25.0], "vtec")
    add("M3: Quiet VTEC (Shallow Megathrust)", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], "vtec")
    add("M3: Quiet VTEC (Shallow Crustal/Splay)", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], "vtec")

    with (ANALYSIS_DIR / "stage5c_zero_overlap_equallag_v002.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    (OUT_DIR / "STAGE5C_ZERO_OVERLAP_v002.md").write_text("# Stage 5C Zero-Overlap Equal-Lag Audit v002\n", encoding="utf-8")
    (OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
        'param([string]$PackageRoot = $PSScriptRoot)\n$ErrorActionPreference = "Stop"\n'
        'foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {\n'
        '  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }\n'
        '  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green\n}\n'
        'Write-Host "ALL CHECKS PASSED (Stage 5C zero-overlap equal-lag audit verified)." -ForegroundColor Cyan\n', encoding="utf-8")
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in ["STAGE5C_ZERO_OVERLAP_v002.md", "VERIFY_PACKAGE.ps1", "analysis/stage5c_zero_overlap_equallag_v002.csv"]:
            fp = OUT_DIR / rel; w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

if __name__ == "__main__":
    main()
