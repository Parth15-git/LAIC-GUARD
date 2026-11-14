import csv
import gzip
import hashlib
import io
import math
import random
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\parth\OneDrive\Desktop\Research\LAIC-GUARD")
S2C_CSV = ROOT / "reports/stage2c/archive_readiness_v001/analysis/stage2c_verified_benchmark_cohort_v001.csv"
S1D_CSV = ROOT / "reports/stage1d/catalogue_freeze_v001/analysis/event_catalogue_frozen_v001.csv"
ZIP_CACHE = ROOT / "data/external/gnss/unr_trop_zips_v001"
IONEX_CACHE = ROOT / "data/external/ionosphere/code_ionex_v001"
OMNI_CACHE = ROOT / "data/external/space_weather/omniweb_lowres_v001"

OUT_DIR = ROOT / "reports/stage4b/full_tier1_benchmark_v001"
ANALYSIS_DIR = OUT_DIR / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LAIC-GUARD-Stage4B-FullTier1/1.0 (academic-research)"


def download_zip(url: str) -> tuple[str, Path | None]:
    fname = url.rstrip("/").split("/")[-1]
    dest = ZIP_CACHE / fname
    if dest.exists() and dest.stat().st_size > 500:
        return url, dest
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if len(raw) > 500:
                    dest.write_bytes(raw)
                    return url, dest
        except Exception:
            pass
    return url, None


def unlzw(data: bytes) -> bytes:
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Invalid .Z header")
    flags = data[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    pos, n_bytes = 3, len(data)
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


def fetch_code_ionex_day(day_dt: datetime) -> tuple[str, Path | None]:
    yr = day_dt.year
    doy = day_dt.timetuple().tm_yday
    yy = yr % 100
    d_key = day_dt.strftime("%Y-%m-%d")
    candidates = [
        (f"CODG{doy:03d}0.{yy:02d}I.Z", f"http://www.aiub.unibe.ch/download/CODE/{yr}/CODG{doy:03d}0.{yy:02d}I.Z"),
        (f"COD0OPSFIN_{yr}{doy:03d}0000_01D_01H_GIM.INX.gz", f"http://www.aiub.unibe.ch/download/CODE/{yr}/COD0OPSFIN_{yr}{doy:03d}0000_01D_01H_GIM.INX.gz"),
    ]
    for fname, _ in candidates:
        fp = IONEX_CACHE / fname
        if fp.exists() and fp.stat().st_size > 2000:
            return d_key, fp
    for fname, url in candidates:
        fp = IONEX_CACHE / fname
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                if len(raw) > 2000:
                    fp.write_bytes(raw)
                    return d_key, fp
        except Exception:
            continue
    return d_key, None


def parse_ionex_maps(ionex_path: Path):
    raw = ionex_path.read_bytes()
    if ionex_path.name.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    elif ionex_path.name.endswith(".Z") or raw[:2] == b"\x1f\x9d":
        text = unlzw(raw).decode("utf-8", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")

    lat1, lat2, dlat = 87.5, -87.5, -2.5
    lon1, lon2, dlon = -180.0, 180.0, 5.0
    exponent = -1
    lines = text.splitlines()
    idx, n_lines = 0, len(lines)
    while idx < n_lines:
        line = lines[idx]
        label = line[60:].strip()
        if label == "END OF HEADER":
            idx += 1
            break
        elif label == "LAT1 / LAT2 / DLAT":
            p = line[:60].split()
            lat1, lat2, dlat = float(p[0]), float(p[1]), float(p[2])
        elif label == "LON1 / LON2 / DLON":
            p = line[:60].split()
            lon1, lon2, dlon = float(p[0]), float(p[1]), float(p[2])
        elif label == "EXPONENT":
            exponent = int(line[:60].strip())
        idx += 1

    scale = 10.0 ** exponent
    n_lats = int(round((lat2 - lat1) / dlat)) + 1
    n_lons = int(round((lon2 - lon1) / dlon)) + 1
    maps = []
    while idx < n_lines:
        line = lines[idx]
        if line[60:].strip() == "START OF TEC MAP":
            idx += 1
            epoch_dt = None
            grid = []
            while idx < n_lines:
                mline = lines[idx]
                mlabel = mline[60:].strip()
                if mlabel == "END OF TEC MAP":
                    idx += 1
                    break
                elif mlabel == "EPOCH OF CURRENT MAP":
                    ep = [int(x) for x in mline[:60].split()]
                    if ep[3] == 24:
                        epoch_dt = datetime(ep[0], ep[1], ep[2], 0, ep[4], ep[5], tzinfo=timezone.utc) + timedelta(days=1)
                    else:
                        epoch_dt = datetime(ep[0], ep[1], ep[2], ep[3], ep[4], ep[5], tzinfo=timezone.utc)
                    idx += 1
                elif mlabel == "LAT/LON1/LON2/DLON/H":
                    idx += 1
                    vals = []
                    while len(vals) < n_lons and idx < n_lines:
                        row_str = lines[idx]
                        for k in range(0, min(80, len(row_str)), 5):
                            chunk = row_str[k:k+5].strip()
                            if chunk:
                                v = int(chunk)
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


def bilinear_vtec(m_tuple, lat: float, lon: float) -> float:
    _, lat1, dlat, lon1, dlon, n_lats, n_lons, grid = m_tuple
    fi = (lat - lat1) / dlat
    fj = (lon - lon1) / dlon
    i0 = max(0, min(n_lats - 2, int(math.floor(fi))))
    j0 = max(0, min(n_lons - 2, int(math.floor(fj))))
    wy = max(0.0, min(1.0, fi - i0))
    wx = max(0.0, min(1.0, fj - j0))
    g = grid
    return (1 - wy) * ((1 - wx) * g[i0][j0] + wx * g[i0][j0 + 1]) + wy * ((1 - wx) * g[i0 + 1][j0] + wx * g[i0 + 1][j0 + 1])


def parse_sinex_trop_hourly(zip_path: Path, t_start: datetime, t_end: datetime) -> tuple[int, dict[str, float], dict[str, float]]:
    d_min = t_start.date()
    d_max = t_end.date()
    seen_5min = set()
    ztd_bins: dict[str, list[float]] = {}
    iwv_bins: dict[str, list[float]] = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if ".trop" not in member.lower():
                continue
            base_name = member.split("/")[-1]
            m_parts = base_name.split(".")
            if len(m_parts) >= 4 and m_parts[1].isdigit() and m_parts[2].isdigit():
                try:
                    m_date = (datetime(int(m_parts[1]), 1, 1) + timedelta(days=int(m_parts[2]) - 1)).date()
                    if m_date < d_min or m_date > d_max:
                        continue
                except ValueError:
                    pass

            raw_bytes = zf.read(member)
            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)

            in_sol = False
            col_names = []
            for raw_line in io.BytesIO(raw_bytes):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("+TROP/SOLUTION"):
                    in_sol = True
                    continue
                if line.startswith("-TROP/SOLUTION"):
                    break
                if not in_sol or not line.strip():
                    continue
                if line.startswith("*"):
                    hdr = line.lstrip("*").strip().split()
                    if "TROTOT" in hdr:
                        col_names = hdr
                    continue

                parts = line.split()
                if len(parts) < 4:
                    continue
                ts_parts = parts[1].split(":")
                if len(ts_parts) != 3:
                    continue
                try:
                    yy, doy, sec = int(ts_parts[0]), int(ts_parts[1]), int(ts_parts[2])
                    yr = yy if yy >= 1900 else (2000 + yy if yy < 80 else 1900 + yy)
                    dt = datetime(yr, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, seconds=sec)
                except ValueError:
                    continue
                if dt < t_start or dt > t_end:
                    continue
                try:
                    trotot = float(parts[2])
                except ValueError:
                    continue
                if not (1000.0 <= trotot <= 3500.0):
                    continue

                ts_5m = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                if ts_5m in seen_5min:
                    continue
                seen_5min.add(ts_5m)
                hr_key = ts_5m[:13] + ":00:00Z"
                ztd_bins.setdefault(hr_key, []).append(trotot)

                iwv_idx = col_names.index("IWV") if (col_names and "IWV" in col_names) else (8 if len(parts) >= 10 else -1)
                if 0 <= iwv_idx < len(parts):
                    try:
                        v = float(parts[iwv_idx])
                        if 0.0 <= v <= 120.0:
                            iwv_bins.setdefault(hr_key, []).append(v)
                    except ValueError:
                        pass

    ztd_hr = {k: sum(v) / len(v) for k, v in ztd_bins.items()}
    iwv_hr = {k: sum(v) / len(v) for k, v in iwv_bins.items()}
    return len(seen_5min), ztd_hr, iwv_hr


def load_omni_all() -> dict[str, tuple[float | None, float | None, float | None]]:
    omni = {}
    for fp in sorted(OMNI_CACHE.glob("omni2_*.dat")):
        with fp.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 51:
                    continue
                try:
                    y, doy, hr = int(parts[0]), int(parts[1]), int(parts[2])
                    kp10 = int(parts[38])
                    dst = float(parts[40])
                    f107 = float(parts[50])
                except ValueError:
                    continue
                dt = datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hr)
                ts = dt.strftime("%Y-%m-%dT%H:00:00Z")
                kp_v = (kp10 / 10.0) if (0 <= kp10 <= 90) else None
                dst_v = dst if (-1000.0 <= dst <= 500.0) else None
                f107_v = f107 if (50.0 <= f107 <= 400.0) else None
                omni[ts] = (kp_v, dst_v, f107_v)
    return omni


def median_and_mad(vals: list[float]) -> tuple[float, float]:
    s = sorted(vals)
    n = len(s)
    med = s[n // 2] if n % 2 == 1 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    devs = sorted(abs(v - med) for v in s)
    mad = devs[n // 2] if n % 2 == 1 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
    return med, max(1e-6, 1.4826 * mad)


def roc_auc(scores: list[float], labels: list[int]) -> float:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def fit_and_predict_loeo(samples: list[dict], feat_keys: list[str]) -> list[float]:
    event_ids = sorted({s["event_id"] for s in samples})
    preds = [0.5] * len(samples)
    for hold_eid in event_ids:
        train_idx = [i for i, s in enumerate(samples) if s["event_id"] != hold_eid]
        test_idx = [i for i, s in enumerate(samples) if s["event_id"] == hold_eid]
        means, stds = [], []
        for k in feat_keys:
            vals = [samples[i][k] for i in train_idx]
            m = sum(vals) / len(vals)
            v = sum((x - m) ** 2 for x in vals) / max(1, len(vals) - 1)
            means.append(m)
            stds.append(max(1e-6, math.sqrt(v)))

        x_tr = [[(samples[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)] for i in train_idx]
        y_tr = [samples[i]["label"] for i in train_idx]
        d = len(feat_keys)
        w = [0.0] * d
        b = 0.0
        n_tr = len(x_tr)
        for _ in range(250):
            gw = [0.0] * d
            gb = 0.0
            for xi, yi in zip(x_tr, y_tr):
                z = max(-20.0, min(20.0, b + sum(wj * xij for wj, xij in zip(w, xi))))
                p = 1.0 / (1.0 + math.exp(-z))
                err = p - yi
                gb += err
                for j in range(d):
                    gw[j] += err * xi[j]
            b -= 0.08 * (gb / n_tr)
            for j in range(d):
                w[j] -= 0.08 * ((gw[j] / n_tr) + 1.0 * w[j])

        for i in test_idx:
            xi = [(samples[i][k] - means[j]) / stds[j] for j, k in enumerate(feat_keys)]
            z = max(-20.0, min(20.0, b + sum(wj * xij for wj, xij in zip(w, xi))))
            preds[i] = 1.0 / (1.0 + math.exp(-z))
    return preds


def bootstrap_auc_ci(samples: list[dict], preds: list[float], n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    rng = random.Random(seed)
    by_ev: dict[str, list[tuple[float, int]]] = {}
    for s, p in zip(samples, preds):
        by_ev.setdefault(s["event_id"], []).append((p, s["label"]))
    ev_keys = sorted(by_ev.keys())
    n_ev = len(ev_keys)
    aucs = []
    for _ in range(n_boot):
        sampled = [ev_keys[rng.randrange(n_ev)] for _ in range(n_ev)]
        b_scores, b_labels = [], []
        for ek in sampled:
            for p, y in by_ev[ek]:
                b_scores.append(p)
                b_labels.append(y)
        aucs.append(roc_auc(b_scores, b_labels))
    aucs.sort()
    return aucs[int(0.025 * n_boot)], aucs[int(0.975 * n_boot)]


def main() -> None:
    with S1D_CSV.open("r", encoding="utf-8-sig") as f:
        ev_meta = {r["event_id"]: r for r in csv.DictReader(f)}
    with S2C_CSV.open("r", encoding="utf-8-sig") as f:
        tier1_ready = [
            r for r in csv.DictReader(f)
            if r["stage2c_benchmark_ready_v001"] == "True"
            and r["stage2b_coupling_eligibility_tier"] == "TIER1_NEAR_FIELD_ELIGIBLE_LE_150KM"
        ]
    tier1_ready.sort(key=lambda x: x["origin_time_utc"])
    print(f"Stage 4B Scaling to Full Tier-1 (<=150 km) M>=6.5 Ready Cohort: {len(tier1_ready)} events")

    # 1. Fetch/verify all required UNR .trop.zip files
    unique_zips = sorted({u.strip() for r in tier1_ready for u in r["unr_trop_urls"].split(";") if u.strip()})
    print(f"Fetching/verifying {len(unique_zips)} unique UNR .trop.zip archives...")
    zip_map = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(download_zip, u) for u in unique_zips]
        for i, fut in enumerate(as_completed(futures), 1):
            u, p = fut.result()
            if p:
                zip_map[u] = p
            if i % 60 == 0 or i == len(futures):
                print(f"  UNR ZIP progress: {i}/{len(futures)}")

    # 2. Parse GNSS 5-min windows and select >=80% QA-passing events
    omni_all = load_omni_all()
    qa_pass_events = []
    gnss_hourly_cache = {}
    needed_days = {}

    for ev in tier1_ready:
        eid = ev["event_id"]
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        w_start = ev_dt - timedelta(days=45)
        w_end = ev_dt + timedelta(days=5)
        urls = [u.strip() for u in ev["unr_trop_urls"].split(";") if u.strip()]

        tot_5m = 0
        ztd_hr_all = {}
        iwv_hr_all = {}
        for u in urls:
            zp = zip_map.get(u)
            if zp:
                c5, zh, ih = parse_sinex_trop_hourly(zp, w_start, w_end)
                tot_5m += c5
                ztd_hr_all.update(zh)
                iwv_hr_all.update(ih)

        cov_frac = min(1.0, tot_5m / 14400.0)
        if cov_frac >= 0.80:
            qa_pass_events.append((ev, cov_frac))
            gnss_hourly_cache[eid] = (ztd_hr_all, iwv_hr_all)
            for off in range(-45, 6):
                d = (ev_dt + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
                needed_days[d.strftime("%Y-%m-%d")] = d

    print(f"GNSS >=80% QA-Pass Events across Full Tier-1 Cohort: {len(qa_pass_events)} / {len(tier1_ready)}")

    # 3. Fetch/verify CODE AIUB IONEX GIM maps for all QA-pass events
    print(f"Fetching/verifying {len(needed_days)} unique daily CODE AIUB IONEX GIM files...")
    ionex_files = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_code_ionex_day, d) for d in needed_days.values()]
        for i, fut in enumerate(as_completed(futures), 1):
            d_key, fp = fut.result()
            if fp:
                ionex_files[d_key] = fp
            if i % 1000 == 0 or i == len(futures):
                print(f"  IONEX progress: {i}/{len(futures)}")

    print("Parsing IONEX global TEC maps...")
    parsed_maps = {}
    for d_key, fp in ionex_files.items():
        try:
            parsed_maps[d_key] = parse_ionex_maps(fp)
        except Exception:
            parsed_maps[d_key] = []

    # 4. Build strict 1:1 paired-event deconfounded metrics
    paired_events = []
    for ev, cov_frac in qa_pass_events:
        eid = ev["event_id"]
        meta = ev_meta[eid]
        elat, elon = float(meta["latitude_deg"]), float(meta["longitude_deg"])
        ev_dt = datetime.fromisoformat(ev["origin_time_utc"].replace("Z", "+00:00"))
        ev_hour = ev_dt.replace(minute=0, second=0, microsecond=0)
        ztd_hr, iwv_hr = gnss_hourly_cache[eid]

        vtec_hr = {}
        for off in range(-45, 6):
            d_key = (ev_dt + timedelta(days=off)).strftime("%Y-%m-%d")
            for m_tup in parsed_maps.get(d_key, []):
                val = bilinear_vtec(m_tup, elat, elon)
                if not math.isnan(val):
                    vtec_hr[m_tup[0].strftime("%Y-%m-%dT%H:00:00Z")] = val

        timeline = []
        for h_off in range(-45 * 24, 5 * 24 + 1):
            t_cur = ev_hour + timedelta(hours=h_off)
            ts = t_cur.strftime("%Y-%m-%dT%H:00:00Z")
            kp_v, dst_v, f107_v = omni_all.get(ts, (None, None, None))
            is_q = (kp_v is not None and dst_v is not None and kp_v < 3.0 and dst_v > -30.0)
            timeline.append({
                "rel_hours": h_off,
                "hour": t_cur.hour,
                "is_quiet": is_q,
                "f107": f107_v,
                "ztd": ztd_hr.get(ts),
                "iwv": iwv_hr.get(ts),
                "vtec": vtec_hr.get(ts),
            })

        # Linear F10.7 detrending on [-45d, -11d] quiet baseline
        pts = [(x["f107"], x["vtec"]) for x in timeline if -45 * 24 <= x["rel_hours"] <= -11 * 24 - 1 and x["is_quiet"] and x["f107"] is not None and x["vtec"] is not None]
        if len(pts) >= 48:
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            sxx = sum((p[0] - mx) ** 2 for p in pts)
            slope = (sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx) if sxx > 1e-6 else 0.0
        else:
            slope, mx = 0.0, 0.0

        for x in timeline:
            x["vtec_detr"] = (x["vtec"] - slope * (x["f107"] - mx)) if (x["vtec"] is not None and x["f107"] is not None) else x["vtec"]

        trop_key = "iwv" if sum(1 for x in timeline if x["iwv"] is not None) >= 800 else "ztd"

        def eval_win(c0, c1, e0, e1):
            def cal(field, q_only):
                pool = [x[field] for x in timeline if c0 <= x["rel_hours"] <= c1 and x[field] is not None and (not q_only or x["is_quiet"])]
                if len(pool) < 24:
                    return {}
                gm, gs = median_and_mad(pool)
                out = {}
                for h in range(24):
                    sub = [x[field] for x in timeline if c0 <= x["rel_hours"] <= c1 and x["hour"] == h and x[field] is not None and (not q_only or x["is_quiet"])]
                    out[h] = median_and_mad(sub) if len(sub) >= 3 else (gm, gs)
                return out

            tc = cal(trop_key, False)
            vc = cal("vtec_detr", True)
            tz, vz, jh = [], [], 0
            for x in timeline:
                if not (e0 <= x["rel_hours"] <= e1):
                    continue
                zt = abs((x[trop_key] - tc[x["hour"]][0]) / tc[x["hour"]][1]) if (x[trop_key] is not None and x["hour"] in tc) else None
                zv = abs((x["vtec_detr"] - vc[x["hour"]][0]) / vc[x["hour"]][1]) if (x["is_quiet"] and x["vtec_detr"] is not None and x["hour"] in vc) else None
                if zt is not None:
                    tz.append(zt)
                if zv is not None:
                    vz.append(zv)
                if zt is not None and zv is not None and zt >= 2.5 and zv >= 2.5:
                    jh += 1
            return tz, vz, jh

        ptz, pvz, pjh = eval_win(-35 * 24, -21 * 24 - 1, -20 * 24, -11 * 24 - 1)
        ttz, tvz, tjh = eval_win(-25 * 24, -11 * 24 - 1, -10 * 24, -1)

        # Strict 1:1 paired completeness: >=24 valid trop hours AND >=24 quiet VTEC hours in BOTH windows
        if min(len(ptz), len(ttz), len(pvz), len(tvz)) < 24:
            continue

        paired_events.append({
            "event_id": eid,
            "origin_time_utc": ev["origin_time_utc"],
            "magnitude": float(ev["magnitude"]),
            "depth_km": float(ev["depth_km"]),
            "frozen_macro_region_v001": ev["frozen_macro_region_v001"],
            "stage1c4_final_source_class_v001": ev["stage1c4_final_source_class_v001"],
            "stage1d_analysis_role_v001": ev["stage1d_analysis_role_v001"],
            "verified_gnss_station_id": ev["verified_gnss_station_id"],
            "verified_gnss_distance_km": float(ev["verified_gnss_distance_km"]),
            "gnss_cov_frac": round(cov_frac, 4),
            "p_trop_max": max(ptz),
            "p_trop_q95": sorted(ptz)[int(0.95 * (len(ptz) - 1))],
            "p_vtec_max": max(pvz),
            "p_vtec_q95": sorted(pvz)[int(0.95 * (len(pvz) - 1))],
            "p_joint": float(pjh),
            "t_trop_max": max(ttz),
            "t_trop_q95": sorted(ttz)[int(0.95 * (len(ttz) - 1))],
            "t_vtec_max": max(tvz),
            "t_vtec_q95": sorted(tvz)[int(0.95 * (len(tvz) - 1))],
            "t_joint": float(tjh),
        })

    ev_csv = ANALYSIS_DIR / "stage4b_paired_tier1_events_v001.csv"
    with ev_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(paired_events[0].keys()))
        w.writeheader()
        w.writerows(paired_events)

    def build_samples(sub_events):
        out = []
        for e in sub_events:
            out.append({
                "event_id": e["event_id"], "label": 0,
                "mag": e["magnitude"], "dist": e["verified_gnss_distance_km"],
                "trop_max": e["p_trop_max"], "trop_q95": e["p_trop_q95"],
                "vtec_max": e["p_vtec_max"], "vtec_q95": e["p_vtec_q95"],
                "joint": e["p_joint"], "prod": e["p_trop_max"] * e["p_vtec_max"],
            })
            out.append({
                "event_id": e["event_id"], "label": 1,
                "mag": e["magnitude"], "dist": e["verified_gnss_distance_km"],
                "trop_max": e["t_trop_max"], "trop_q95": e["t_trop_q95"],
                "vtec_max": e["t_vtec_max"], "vtec_q95": e["t_vtec_q95"],
                "joint": e["t_joint"], "prod": e["t_trop_max"] * e["t_vtec_max"],
            })
        return out

    models = [
        ("M1_Seismicity_Distance", r"M1: Seismicity \& Distance Only", ["mag", "dist"]),
        ("M2_Troposphere_15d_Lag", r"M2: Troposphere (ZTD/IWV, 15d-lag)", ["trop_max", "trop_q95"]),
        ("M3_Quiet_VTEC_F107", r"M3: Quiet GIM VTEC ($F_{10.7}$-adj.)", ["vtec_max", "vtec_q95"]),
        ("M4_Joint_Concordance", r"M4: Joint Trop $\times$ VTEC Concordance", ["joint", "prod"]),
        ("M5_Full_MultiDomain", r"M5: Full Multi-Domain Feature Set", ["mag", "dist", "trop_max", "trop_q95", "vtec_max", "vtec_q95", "joint"]),
    ]

    summary_rows = []
    for cohort_name, min_mag in [("ALL_TIER1_M65", 6.5), ("MAJOR_TIER1_M70", 7.0)]:
        sub = [e for e in paired_events if e["magnitude"] >= min_mag]
        sh_ev = [e for e in sub if e["stage1d_analysis_role_v001"] == "PRIMARY_SHALLOW_TARGET"]
        nc_ev = [e for e in sub if e["stage1d_analysis_role_v001"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]
        sh_samp = build_samples(sh_ev)
        nc_samp = build_samples(nc_ev)

        for mid, mtex, fkeys in models:
            sh_p = fit_and_predict_loeo(sh_samp, fkeys)
            nc_p = fit_and_predict_loeo(nc_samp, fkeys)
            sh_auc = roc_auc(sh_p, [s["label"] for s in sh_samp])
            nc_auc = roc_auc(nc_p, [s["label"] for s in nc_samp])
            sh_lo, sh_hi = bootstrap_auc_ci(sh_samp, sh_p)
            nc_lo, nc_hi = bootstrap_auc_ci(nc_samp, nc_p)
            summary_rows.append({
                "cohort": cohort_name,
                "shallow_events": len(sh_ev),
                "null_ctrl_events": len(nc_ev),
                "model_id": mid,
                "latex_label": mtex,
                "shallow_auc": f"{sh_auc:.3f}",
                "shallow_ci95": f"[{sh_lo:.2f}, {sh_hi:.2f}]",
                "null_auc": f"{nc_auc:.3f}",
                "null_ci95": f"[{nc_lo:.2f}, {nc_hi:.2f}]",
                "delta_auc": f"{(sh_auc - nc_auc):+.3f}",
            })

    sum_csv = ANALYSIS_DIR / "stage4b_full_tier1_ablation_v001.csv"
    with sum_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    all_m65 = [r for r in summary_rows if r["cohort"] == "ALL_TIER1_M65"]
    maj_m70 = [r for r in summary_rows if r["cohort"] == "MAJOR_TIER1_M70"]

    tex_path = ANALYSIS_DIR / "stage4b_full_tier1_ablation_table.tex"
    tex_lines = [
        r"% Auto-generated Stage 4B Full Tier-1 (M >= 6.5 & M >= 7.0) 1:1 Paired LOEO Ablation Table",
        r"\begin{table*}[t]",
        r"\centering",
        f"\\caption{{Stage 4B Leave-One-Event-Out (LOEO) $\\text{{ROC-AUC}}$ with Cluster-Bootstrap 95\\% Confidence Intervals Across 1:1 Storm-Paired Tier-1 ($d \\le 150\\,\\text{{km}}$) Earthquakes: Full $M \\ge 6.5$ Cohort ($N_S = {all_m65[0]['shallow_events']}$, $N_{{NC}} = {all_m65[0]['null_ctrl_events']}$) vs.\\ Major $M \\ge 7.0$ Sub-Cohort ($N_S = {maj_m70[0]['shallow_events']}$, $N_{{NC}} = {maj_m70[0]['null_ctrl_events']}$).}}",
        r"\label{tab:stage4b_full_tier1_ablation}",
        r"\begin{tabular}{lcccccc}",
        r"\hline",
        r"\textbf{Ablation Model} & \textbf{Shallow ($M\!\ge\!6.5$)} & \textbf{Null-Ctrl ($M\!\ge\!6.5$)} & \textbf{$\Delta\text{AUC}_{6.5}$} & \textbf{Shallow ($M\!\ge\!7.0$)} & \textbf{Null-Ctrl ($M\!\ge\!7.0$)} & \textbf{$\Delta\text{AUC}_{7.0}$} \\",
        r"\hline",
    ]
    for r65, r70 in zip(all_m65, maj_m70):
        tex_lines.append(
            f"{r65['latex_label']} & {r65['shallow_auc']} {r65['shallow_ci95']} & {r65['null_auc']} {r65['null_ci95']} & {r65['delta_auc']} & "
            f"{r70['shallow_auc']} {r70['shallow_ci95']} & {r70['null_auc']} {r70['null_ci95']} & {r70['delta_auc']} \\\\"
        )
    tex_lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table*}",
    ])
    tex_path.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")

    md_out = OUT_DIR / "STAGE4B_FULL_TIER1_BENCHMARK_v001.md"
    md_out.write_text(
        "# Stage 4B - Full Tier-1 (M >= 6.5) 1:1 Paired Multi-Domain Benchmark (v001)\n\n"
        f"**Strictly Paired 1:1 Cohort ($M \\ge 6.5$):** {all_m65[0]['shallow_events']} Primary Shallow Targets + {all_m65[0]['null_ctrl_events']} Physical Null Controls\n"
        f"**Strictly Paired 1:1 Sub-Cohort ($M \\ge 7.0$):** {maj_m70[0]['shallow_events']} Primary Shallow Targets + {maj_m70[0]['null_ctrl_events']} Physical Null Controls\n",
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
        'Write-Host "ALL CHECKS PASSED (Stage 4B full Tier-1 benchmark and bootstrap CIs verified)." -ForegroundColor Cyan\n',
        encoding="utf-8",
    )

    rel_files = [
        "STAGE4B_FULL_TIER1_BENCHMARK_v001.md",
        "VERIFY_PACKAGE.ps1",
        "analysis/stage4b_paired_tier1_events_v001.csv",
        "analysis/stage4b_full_tier1_ablation_v001.csv",
        "analysis/stage4b_full_tier1_ablation_table.tex",
    ]
    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in rel_files:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])

    print("\nStage 4B Complete.")


if __name__ == "__main__":
    main()
