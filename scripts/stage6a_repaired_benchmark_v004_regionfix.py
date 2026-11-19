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

OUT_DIR = ROOT / "reports/stage6a/audit_repaired_v004_regionfix"
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


def bootstrap_auc_ci_by_group(
    samples: list[dict],
    preds: list[float],
    gkey: str,
    n_boot: int = 1000,
    seed: int = 42,
) -> tuple[float, float]:
    """Group bootstrap; confidence interval conditional on fixed OOF predictions."""
    if len(samples) != len(preds):
        raise ValueError("Samples/predictions length mismatch.")

    by_group: dict[str, list[tuple[float, int]]] = {}
    for sample, pred in zip(samples, preds):
        by_group.setdefault(str(sample[gkey]), []).append(
            (pred, int(sample["label"]))
        )

    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError("At least two validation groups are required.")

    for group in groups:
        labels = {label for _, label in by_group[group]}
        if labels != {0, 1}:
            raise ValueError(
                f"Group {group} does not contain both paired labels."
            )

    rng = random.Random(seed)
    aucs = []

    for _ in range(n_boot):
        selected = [groups[rng.randrange(len(groups))] for _ in groups]
        scores, labels = [], []

        for group in selected:
            for pred, label in by_group[group]:
                scores.append(pred)
                labels.append(label)

        aucs.append(roc_auc(scores, labels))

    aucs.sort()
    return (
        aucs[int(0.025 * len(aucs))],
        aucs[min(len(aucs) - 1, int(0.975 * len(aucs)))],
    )


def perm_auc_pvalue_group_refit(
    samples: list[dict],
    fkeys: list[str],
    gkey: str,
    observed_preds: list[float],
    n_perm: int = 99,
    seed: int = 42,
) -> float:
    """
    Component-level paired label-swap test with complete grouped-LOEO refitting.

    All event pairs in a dependence component are flipped together.
    The test assumes component-level exchangeability under the null.
    """
    if n_perm < 1:
        raise ValueError("n_perm must be positive.")
    if len(samples) != len(observed_preds):
        raise ValueError("Samples/predictions length mismatch.")

    labels = [int(s["label"]) for s in samples]
    if any(y not in (0, 1) for y in labels):
        raise ValueError("Labels must be binary.")

    by_event: dict[str, list[dict]] = {}
    by_group: dict[str, list[int]] = {}

    for i, sample in enumerate(samples):
        event_id = str(sample["event_id"])
        group_id = str(sample[gkey])
        by_event.setdefault(event_id, []).append(sample)
        by_group.setdefault(group_id, []).append(i)

    for event_id, pair in by_event.items():
        if len(pair) != 2 or sorted(int(s["label"]) for s in pair) != [0, 1]:
            raise ValueError(f"Event {event_id} is not one complete 0/1 pair.")
        if str(pair[0][gkey]) != str(pair[1][gkey]):
            raise ValueError(f"Event {event_id} spans multiple groups.")

    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError("At least two dependence groups are required.")

    observed_auc = roc_auc(observed_preds, labels)
    if not math.isfinite(observed_auc):
        raise ValueError("Observed AUC is not finite.")

    observed_stat = abs(observed_auc - 0.5)
    rng = random.Random(seed)
    extreme = 0

    for _ in range(n_perm):
        flipped = {
            group for group in groups
            if rng.random() < 0.5
        }

        permuted = []
        for sample in samples:
            item = dict(sample)
            if str(item[gkey]) in flipped:
                item["label"] = 1 - int(item["label"])
            permuted.append(item)

        # Refit the complete grouped cross-validation procedure.
        perm_preds = grouped_loeo(permuted, fkeys, gkey)
        perm_labels = [int(s["label"]) for s in permuted]
        perm_auc = roc_auc(perm_preds, perm_labels)

        if not math.isfinite(perm_auc):
            raise ValueError("A permutation produced a non-finite AUC.")

        if abs(perm_auc - 0.5) >= observed_stat - 1e-12:
            extreme += 1

    return (extreme + 1) / (n_perm + 1)


def component_signflip_pvalue(
    diffs: list[float],
    group_ids: list[str],
    n_perm: int = 9999,
    seed: int = 2026,
) -> dict:
    """
    Two-sided sign-flip test at the dependence-component level.

    The effect estimate is the equally weighted mean of component means.
    Every event within a component receives the same sign flip.
    Exact enumeration is used for <=16 components; otherwise Monte Carlo.
    """
    if len(diffs) != len(group_ids):
        raise ValueError("Difference/group-ID length mismatch.")
    if not diffs:
        raise ValueError("No paired differences supplied.")
    if n_perm < 1:
        raise ValueError("n_perm must be positive.")

    by_group: dict[str, list[float]] = {}

    for diff, group_id in zip(diffs, group_ids):
        value = float(diff)
        if not math.isfinite(value):
            raise ValueError("Non-finite paired difference.")
        key = str(group_id).strip()
        if not key:
            raise ValueError("Blank dependence-component ID.")
        by_group.setdefault(key, []).append(value)

    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError("At least two dependence components are required.")

    # Equal component weighting avoids allowing the largest block to
    # dominate the primary estimand.
    component_effects = [
        sum(by_group[group]) / len(by_group[group])
        for group in groups
    ]

    n_groups = len(component_effects)
    observed = sum(component_effects) / n_groups
    observed_abs = abs(observed)
    tolerance = 1e-12

    if n_groups <= 16:
        total = 1 << n_groups
        extreme = 0

        for mask in range(total):
            stat = sum(
                (1.0 if (mask >> i) & 1 else -1.0) * effect
                for i, effect in enumerate(component_effects)
            ) / n_groups

            if abs(stat) >= observed_abs - tolerance:
                extreme += 1

        p_value = extreme / total
        method = "EXACT_COMPONENT_SIGN_FLIP"
        actual_n = total
        actual_seed = "NA"

    else:
        rng = random.Random(seed)
        extreme = 0

        for _ in range(n_perm):
            stat = sum(
                (1.0 if rng.random() < 0.5 else -1.0) * effect
                for effect in component_effects
            ) / n_groups

            if abs(stat) >= observed_abs - tolerance:
                extreme += 1

        p_value = (extreme + 1) / (n_perm + 1)
        method = "MONTE_CARLO_COMPONENT_SIGN_FLIP"
        actual_n = n_perm
        actual_seed = seed

    return {
        "effect_mean_component_means": observed,
        "p_value_two_sided": p_value,
        "n_events": len(diffs),
        "n_components": n_groups,
        "method": method,
        "n_permutations": actual_n,
        "seed": actual_seed,
        "weighting": "equal_weight_per_component",
    }


def paired_delta_auc_component_swap(
    preds_a: list[float],
    preds_b: list[float],
    labels: list[int],
    group_ids: list[str],
    event_ids: list[str],
    n_perm: int = 9999,
    seed: int = 2027,
) -> dict:
    """
    Paired component-block model-swap test.

    Swaps model A/B prediction blocks for every row in a component together.
    This is conditional on fixed OOF predictions; it does not refit models.
    """
    n = len(labels)

    if not (
        len(preds_a) == len(preds_b) == len(group_ids)
        == len(event_ids) == n
    ):
        raise ValueError("Model-comparison input length mismatch.")
    if n_perm < 1:
        raise ValueError("n_perm must be positive.")
    if any(int(y) not in (0, 1) for y in labels):
        raise ValueError("Comparison labels must be binary.")

    by_event: dict[str, list[int]] = {}
    by_group: dict[str, list[int]] = {}

    for i in range(n):
        event = str(event_ids[i]).strip()
        group = str(group_ids[i]).strip()

        if not event or not group:
            raise ValueError("Blank event or group ID.")

        by_event.setdefault(event, []).append(i)
        by_group.setdefault(group, []).append(i)

    for event, indices in by_event.items():
        if len(indices) != 2:
            raise ValueError(f"Event {event} does not have exactly two rows.")

        pair_labels = sorted(int(labels[i]) for i in indices)
        if pair_labels != [0, 1]:
            raise ValueError(f"Event {event} is not a complete 0/1 pair.")

        if group_ids[indices[0]] != group_ids[indices[1]]:
            raise ValueError(f"Event {event} spans multiple components.")

    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError("At least two dependence components are required.")

    auc_a = roc_auc(preds_a, labels)
    auc_b = roc_auc(preds_b, labels)
    delta_obs = auc_a - auc_b

    if not math.isfinite(delta_obs):
        raise ValueError("Observed model delta is not finite.")

    extreme = 0
    threshold = abs(delta_obs) - 1e-12

    def permuted_delta(flipped):
        pa = list(preds_a)
        pb = list(preds_b)

        for group in flipped:
            for i in by_group[group]:
                pa[i], pb[i] = pb[i], pa[i]

        return roc_auc(pa, labels) - roc_auc(pb, labels)

    if len(groups) <= 16:
        total = 1 << len(groups)

        for mask in range(total):
            flipped = {
                groups[i]
                for i in range(len(groups))
                if (mask >> i) & 1
            }
            if abs(permuted_delta(flipped)) >= threshold:
                extreme += 1

        p_value = extreme / total
        method = "EXACT_COMPONENT_BLOCK_MODEL_SWAP"
        actual_n = total
        actual_seed = "NA"

    else:
        rng = random.Random(seed)

        for _ in range(n_perm):
            flipped = {
                group for group in groups
                if rng.random() < 0.5
            }
            if abs(permuted_delta(flipped)) >= threshold:
                extreme += 1

        p_value = (extreme + 1) / (n_perm + 1)
        method = "MONTE_CARLO_COMPONENT_BLOCK_MODEL_SWAP"
        actual_n = n_perm
        actual_seed = seed

    return {
        "auc_model_a": auc_a,
        "auc_model_b": auc_b,
        "delta_auc_a_minus_b": delta_obs,
        "p_value_two_sided": p_value,
        "n_events": len(by_event),
        "n_components": len(groups),
        "method": method,
        "n_permutations": actual_n,
        "seed": actual_seed,
        "interpretation": "conditional_on_fixed_OOF_predictions",
        "assumption": "model_identity_exchangeable_at_component_level",
    }


def holm_adjust_pvalues(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values, preserving input key order."""
    if not pvalues:
        raise ValueError("No p-values supplied.")

    clean = {}
    for key, value in pvalues.items():
        p_value = float(value)
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError(f"Invalid p-value for {key}: {value}")
        clean[key] = p_value

    ordered = sorted(clean.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted = {}
    running_max = 0.0

    for rank, (key, p_value) in enumerate(ordered):
        candidate = min(1.0, (m - rank) * p_value)
        running_max = max(running_max, candidate)
        adjusted[key] = running_max

    return {key: adjusted[key] for key in clean}


def build_dependency_components(rows: list[dict], mode: str) -> list[str]:
    """
    Build dependence components from events in the supplied cohort.

    Analysis interval: [origin - 45 days, origin - 1 day).
    Modes:
      time        : overlapping analysis intervals
      primary     : overlap OR same nonblank station within 50 days
      station_any : overlap OR same nonblank station at any time
    """
    prefixes = {
        "time": "TIME",
        "primary": "DEP",
        "station_any": "STA",
    }
    if mode not in prefixes:
        raise ValueError(f"Unknown dependence mode: {mode}")

    n = len(rows)
    if n == 0:
        return []

    times = [
        datetime.fromisoformat(
            r["origin_time_utc"].replace("Z", "+00:00")
        ).replace(minute=0, second=0, microsecond=0)
        for r in rows
    ]
    stations = [
        str(r.get("station_id", "")).strip().upper()
        for r in rows
    ]

    starts = [t - timedelta(hours=1080) for t in times]
    ends = [t - timedelta(hours=24) for t in times]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            shared_interval = (
                starts[i] < ends[j] and starts[j] < ends[i]
            )
            same_station = (
                bool(stations[i]) and stations[i] == stations[j]
            )
            gap_days = abs(
                (times[j] - times[i]).total_seconds()
            ) / 86400.0

            if mode == "time":
                connected = shared_interval
            elif mode == "primary":
                connected = (
                    shared_interval
                    or (same_station and gap_days <= 50.0)
                )
            else:
                connected = shared_interval or same_station

            if connected:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    members = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    ordered_roots = sorted(
        members, key=lambda root: min(members[root])
    )
    labels = {
        root: f"{prefixes[mode]}{rank:03d}"
        for rank, root in enumerate(ordered_roots, start=1)
    }

    return [labels[find(i)] for i in range(n)]


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
        reg_s1d = str(m.get("frozen_macro_region_v001", "")).strip()
        reg_s4b = str(ev.get("frozen_macro_region_v001", "")).strip()
        if not reg_s1d or not reg_s4b:
            raise ValueError(
                f"{eid}: missing frozen macro-region in Stage 1D or Stage 4B."
            )
        if reg_s1d != reg_s4b:
            raise ValueError(
                f"{eid}: frozen macro-region mismatch: "
                f"Stage1D={reg_s1d!r}, Stage4B={reg_s4b!r}."
            )
        reg = reg_s1d
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
            "event_id": eid, "origin_time_utc": ev["origin_time_utc"],
            "station_id": sid, "region": reg,
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
    # Diagnostic grouping IDs across the complete feature-eligible cohort.
    time_ids = build_dependency_components(ev_rows, "time")
    primary_ids = build_dependency_components(ev_rows, "primary")
    station_any_ids = build_dependency_components(ev_rows, "station_any")

    for row, time_id, primary_id, station_id in zip(
        ev_rows, time_ids, primary_ids, station_any_ids
    ):
        row["dep_component_time_v004"] = time_id
        row["dep_component_primary_v004"] = primary_id
        row["dep_component_station_any_v004"] = station_id

    print(
        "v004 feature-eligible dependence components: "
        f"time={len(set(time_ids))}, "
        f"primary={len(set(primary_ids))}, "
        f"station_any={len(set(station_any_ids))}"
    )

    unique_stns = len(set(e["station_id"] for e in ev_rows))
    unique_regs = len(set(e["region"] for e in ev_rows))
    unique_ov = len(set(e["overlap_id"] for e in ev_rows))
    print(f"Verified v004 cohort: {len(ev_rows)} events across {unique_stns} unique stations, {unique_regs} regions, {unique_ov} overlap-graph components.")

    summary_rows = []
    oof_store = {}

    def eval_v004(desc: str, dom: str, sub: list[dict], fp: list[str], ft: list[str], dkey: str, gk: str = "event_id", paired_dkeys: list[str] | None = None):
        dependency_modes = {
            "dep_component_time_v004": "time",
            "dep_component_primary_v004": "primary",
            "dep_component_station_any_v004": "station_any",
        }

        if len(fp) != len(ft):
            raise ValueError(f"{desc}: baseline/target feature mismatch.")
        if len({e["event_id"] for e in sub}) != len(sub):
            raise ValueError(f"{desc}: duplicate event IDs.")
        if not sub:
            raise ValueError(f"{desc}: empty evaluation cohort.")

        # Rebuild dependence groups using this evaluation's exact cohort.
        if gk in dependency_modes:
            local_ids = build_dependency_components(
                sub, dependency_modes[gk]
            )
            local_group_by_event = {
                e["event_id"]: group_id
                for e, group_id in zip(sub, local_ids)
            }
            group_scope = "exact_analysis_subcohort"
        else:
            local_group_by_event = {}
            group_scope = "specified_group_key"

        samps = []
        for e in sub:
            d0 = {
                "event_id": e["event_id"],
                "station_id": e["station_id"],
                "region": e["region"],
                "cluster_id": e["cluster_id"],
                "overlap_id": e["overlap_id"],
                "label": 0,
            }
            d1 = {
                "event_id": e["event_id"],
                "station_id": e["station_id"],
                "region": e["region"],
                "cluster_id": e["cluster_id"],
                "overlap_id": e["overlap_id"],
                "label": 1,
            }

            if gk in dependency_modes:
                group_id = local_group_by_event[e["event_id"]]
            else:
                if gk not in e:
                    raise KeyError(f"{desc}: grouping field {gk!r} missing.")
                group_id = e[gk]

            d0[gk] = group_id
            d1[gk] = group_id

            for j, (kp, kt) in enumerate(zip(fp, ft)):
                d0[f"f{j}"] = e[kp]
                d1[f"f{j}"] = e[kt]

            samps.extend([d0, d1])

        if len(samps) != 2 * len(sub):
            raise ValueError(f"{desc}: paired sample count mismatch.")

        for i in range(0, len(samps), 2):
            a, b = samps[i], samps[i + 1]
            if a["event_id"] != b["event_id"]:
                raise ValueError(f"{desc}: event-pair order mismatch.")
            if (a["label"], b["label"]) != (0, 1):
                raise ValueError(f"{desc}: invalid pair labels.")
            if a[gk] != b[gk]:
                raise ValueError(f"{desc}: paired rows have different groups.")

        group_ids = sorted({str(s[gk]) for s in samps})
        if len(group_ids) < 2:
            raise ValueError(
                f"{desc}: fewer than two independent validation groups."
            )

        fkeys = [f"f{j}" for j in range(len(fp))]
        preds = grouped_loeo(samps, fkeys, gk)

        if len(preds) != len(samps):
            raise ValueError(f"{desc}: OOF prediction count mismatch.")

        y = [s["label"] for s in samps]
        auc_v = roc_auc(preds, y)
        lo, hi = bootstrap_auc_ci_by_group(samps, preds, gk)

        # Full-refit component-level permutation is the primary AUC test.
        if gk == "dep_component_primary_v004":
            auc_perm_n = 99
            auc_perm_seed = 42
            p_auc = perm_auc_pvalue_group_refit(
                samps, fkeys, gk, preds,
                n_perm=auc_perm_n,
                seed=auc_perm_seed,
            )
        else:
            auc_perm_n = 0
            auc_perm_seed = "NA"
            p_auc = "NOT_RUN_SECONDARY_ANALYSIS"

        # Physical paired-difference inference: primary component tests only.
        paired_feature_tests = {}

        if gk == "dep_component_primary_v004":
            physical_keys = paired_dkeys if paired_dkeys is not None else [dkey]

            if not physical_keys:
                raise ValueError(f"{desc}: no physical paired endpoints specified.")

            for physical_key in physical_keys:
                p_field = f"p_{physical_key}_q95"
                t_field = f"t_{physical_key}_q95"

                diffs = [
                    float(e[t_field]) - float(e[p_field])
                    for e in sub
                ]
                component_ids = [
                    local_group_by_event[e["event_id"]]
                    for e in sub
                ]

                paired_feature_tests[physical_key] = component_signflip_pvalue(
                    diffs,
                    component_ids,
                    n_perm=9999,
                    seed=2026,
                )
        else:
            paired_feature_tests = {
                "status": "NOT_RUN_SECONDARY_ANALYSIS"
            }

        p_q95 = json.dumps(
            paired_feature_tests,
            sort_keys=True,
            separators=(",", ":"),
        )

        oof_store[desc] = (
            preds,
            y,
            [s[gk] for s in samps],
            gk,
            [s["event_id"] for s in samps],
        )

        summary_rows.append({
            "domain": dom,
            "model_or_stratum": desc,
            "status": "EVALUATED",
            "n_events": len(sub),
            "n_paired_samples": len(samps),
            "validation_group_key": gk,
            "validation_group_scope": group_scope,
            "n_validation_groups": len(group_ids),
            "roc_auc": f"{auc_v:.3f}",
            "ci95": f"[{lo:.3f}, {hi:.3f}]",
            "ci95_scope": "group bootstrap conditional on fixed OOF predictions",
            "pr_auc": f"{pr_auc(preds, y):.3f}",
            "p_auc_refit_group_permutation": (
                f"{p_auc:.5f}" if isinstance(p_auc, float) else p_auc
            ),
            "n_auc_permutations": auc_perm_n,
            "auc_permutation_seed": auc_perm_seed,
            "p_q95_group_sign_flip": p_q95,
        })
    sh = [e for e in ev_rows if e["role"] == "PRIMARY_SHALLOW_TARGET"]
    nc = [e for e in ev_rows if e["role"] == "PHYSICAL_NULL_CONTROL_SLAB_OR_OUTER_RISE"]

    # Troposphere v004
    eval_v004("M2a: Raw GNSS ZTD-Only (Shallow, Event-LOEO)", "Troposphere", sh, ["p_ztd_max", "p_ztd_q95"], ["t_ztd_max", "t_ztd_q95"], "ztd", "event_id")
    eval_v004("M2a: Raw GNSS ZTD-Only (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)", "Troposphere", sh, ["p_ztd_max", "p_ztd_q95"], ["t_ztd_max", "t_ztd_q95"], "ztd", "dep_component_primary_v004")
    eval_v004("M2b: Uncalibrated GNSS - ERA5 (Repaired Units, Shallow)", "Troposphere", sh, ["p_raw_max", "p_raw_q95"], ["t_raw_max", "t_raw_q95"], "raw", "event_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Event-LOEO)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "dep_component_primary_v004")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Cluster-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "cluster_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Station-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "station_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Overlap-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "overlap_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Shallow, Region-CV)", "Troposphere", sh, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "region")
    eval_v004("M2c_pos: Signed Positive ERA5 Residual (Shallow, Event-LOEO)", "Troposphere", sh, ["p_cpos_max", "p_cpos_q95"], ["t_cpos_max", "t_cpos_q95"], "cpos", "event_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Slab/Outer Controls)", "Troposphere", nc, ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Megathrust N=62)", "Troposphere", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")
    eval_v004("M2c: Baseline-Calibrated ERA5 Residual (Crustal/Splay N=28)", "Troposphere", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95"], ["t_cal_max", "t_cal_q95"], "cal", "event_id")

    # Ionosphere v004
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Event-LOEO)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "dep_component_primary_v004")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Cluster-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "cluster_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Station-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "station_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Overlap-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "overlap_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Shallow, Region-CV)", "Ionosphere", sh, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "region")
    eval_v004("M3_pos: Signed Positive Quiet VTEC (Shallow, Event-LOEO)", "Ionosphere", sh, ["p_vpos_max", "p_vpos_q95"], ["t_vpos_max", "t_vpos_q95"], "vpos", "event_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Slab/Outer Controls)", "Ionosphere", nc, ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Megathrust N=62)", "Ionosphere", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet F10.7-Adj. GIM VTEC (Crustal/Splay N=28)", "Ionosphere", [e for e in sh if e["src"] != "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Major Shallow M>=7.0)", "Ionosphere", [e for e in sh if e["mag"] >= 7.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Geomag |lambda_m| <= 25 deg)", "Ionosphere", [e for e in sh if abs(e["gm"]) <= 25.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Geomag |lambda_m| > 25 deg)", "Ionosphere", [e for e in sh if abs(e["gm"]) > 25.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Modip |modip| > 30 deg)", "Ionosphere", [e for e in sh if abs(e["modip"]) > 30.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Station d <= 50 km)", "Ionosphere", [e for e in sh if e["dist_km"] <= 50.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")
    eval_v004("M3: Quiet GIM VTEC (Station 50 < d <= 150 km)", "Ionosphere", [e for e in sh if e["dist_km"] > 50.0], ["p_vtec_max", "p_vtec_q95"], ["t_vtec_max", "t_vtec_q95"], "vtec", "event_id")

    # Joint Multi-Domain Fusion v004
    eval_v004("M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, LOEO)", "Multi-Domain", sh, ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal", "event_id")
    eval_v004("M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)", "Multi-Domain", sh, ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal", "dep_component_primary_v004", paired_dkeys=["cal", "vtec"])
    eval_v004("M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Megathrust N=62)", "Multi-Domain", [e for e in sh if e["src"] == "MEGATHRUST_INTERFACE_CANDIDATE"], ["p_cal_max", "p_cal_q95", "p_vtec_max", "p_vtec_q95"], ["t_cal_max", "t_cal_q95", "t_vtec_max", "t_vtec_q95"], "cal", "event_id")

    # Matched primary component-held-out model comparisons.
    key_m2c = "M2c: Baseline-Calibrated ERA5 Residual (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)"
    key_m2a = "M2a: Raw GNSS ZTD-Only (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)"
    key_m4 = "M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)"
    key_m3 = "M3: Quiet F10.7-Adj. GIM VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)"

    def compare_primary_models(key_a: str, key_b: str) -> dict:
        if key_a not in oof_store or key_b not in oof_store:
            raise KeyError(f"Missing primary OOF result: {key_a} or {key_b}")

        a = oof_store[key_a]
        b = oof_store[key_b]

        # Require identical event ordering, labels, groups and validation keys.
        if a[1] != b[1]:
            raise ValueError("Model comparison labels are not aligned.")
        if a[2] != b[2]:
            raise ValueError("Model comparison dependence groups are not aligned.")
        if a[3] != b[3]:
            raise ValueError("Model comparison validation keys differ.")
        if a[4] != b[4]:
            raise ValueError("Model comparison event ordering differs.")

        if a[3] != "dep_component_primary_v004":
            raise ValueError("Model comparison is not using primary components.")

        return paired_delta_auc_component_swap(
            a[0], b[0], a[1], a[2], a[4],
            n_perm=9999,
            seed=2027,
        )

    cmp_m2c_m2a = compare_primary_models(key_m2c, key_m2a)
    cmp_m4_m3 = compare_primary_models(key_m4, key_m3)

    d_m2c_m2a = cmp_m2c_m2a["delta_auc_a_minus_b"]
    p_m2c_m2a = cmp_m2c_m2a["p_value_two_sided"]
    d_m4_m3 = cmp_m4_m3["delta_auc_a_minus_b"]
    p_m4_m3 = cmp_m4_m3["p_value_two_sided"]

    print(
        f"Conditional component-block comparison M2c vs M2a: "
        f"delta_AUC={d_m2c_m2a:+.3f}, p={p_m2c_m2a:.5f}"
    )
    print(
        f"Conditional component-block comparison M4 vs M3: "
        f"delta_AUC={d_m4_m3:+.3f}, p={p_m4_m3:.5f}"
    )

    # Pre-specified multiple-testing families.
    def get_summary_record(model_key: str) -> dict:
        matches = [
            row for row in summary_rows
            if row["model_or_stratum"] == model_key
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one row for {model_key}; found {len(matches)}."
            )
        return matches[0]

    # Family 1: four primary classifier AUC tests.
    primary_auc_keys = [key_m2a, key_m2c, key_m3, key_m4]
    auc_raw = {
        key: float(get_summary_record(key)["p_auc_refit_group_permutation"])
        for key in primary_auc_keys
    }
    auc_holm = holm_adjust_pvalues(auc_raw)

    # Family 2: three unique physical q95 endpoints.
    # M4 repeats the M2c and M3 physical measurements on the same cohort;
    # those duplicate tests are recorded but not counted again.
    physical_specs = {
        "raw_gnss_ztd_q95": (key_m2a, "ztd"),
        "calibrated_era5_residual_q95": (key_m2c, "cal"),
        "quiet_adjusted_vtec_q95": (key_m3, "vtec"),
    }

    physical_raw = {}
    for family_name, (model_key, endpoint) in physical_specs.items():
        record = get_summary_record(model_key)
        payload = json.loads(record["p_q95_group_sign_flip"])
        physical_raw[family_name] = float(
            payload[endpoint]["p_value_two_sided"]
        )

    physical_holm = holm_adjust_pvalues(physical_raw)

    # Family 3: two primary component-matched model comparisons.
    comparison_raw = {
        "M2c_vs_M2a": float(cmp_m2c_m2a["p_value_two_sided"]),
        "M4_vs_M3": float(cmp_m4_m3["p_value_two_sided"]),
    }
    comparison_holm = holm_adjust_pvalues(comparison_raw)

    cmp_m2c_m2a["p_value_holm"] = comparison_holm["M2c_vs_M2a"]
    cmp_m4_m3["p_value_holm"] = comparison_holm["M4_vs_M3"]
    cmp_m2c_m2a["multiplicity_family"] = "two_primary_model_comparisons"
    cmp_m4_m3["multiplicity_family"] = "two_primary_model_comparisons"

    # Add consistent columns to every benchmark summary row.
    for record in summary_rows:
        record["p_auc_holm_four_primary_models"] = "NOT_IN_PRIMARY_FAMILY"
        record["p_physical_holm_three_distinct_endpoints"] = "NOT_IN_PRIMARY_FAMILY"

    for key, adjusted in auc_holm.items():
        get_summary_record(key)["p_auc_holm_four_primary_models"] = (
            f"{adjusted:.6f}"
        )

    for family_name, (model_key, endpoint) in physical_specs.items():
        get_summary_record(model_key)[
            "p_physical_holm_three_distinct_endpoints"
        ] = json.dumps({
            endpoint: {
                "raw_p": physical_raw[family_name],
                "holm_adjusted_p": physical_holm[family_name],
                "family": "three_distinct_physical_endpoints",
            }
        }, sort_keys=True, separators=(",", ":"))

    get_summary_record(key_m4)[
        "p_physical_holm_three_distinct_endpoints"
    ] = json.dumps({
        "cal": {
            "status": "DUPLICATE_NOT_RECOUNTED",
            "primary_outcome": "calibrated_era5_residual_q95",
        },
        "vtec": {
            "status": "DUPLICATE_NOT_RECOUNTED",
            "primary_outcome": "quiet_adjusted_vtec_q95",
        },
    }, sort_keys=True, separators=(",", ":"))

    multiple_testing = {
        "method": "Holm step-down within three pre-specified families",
        "families": {
            "four_primary_model_auc_tests": {
                "raw_p_values": auc_raw,
                "holm_adjusted_p_values": auc_holm,
            },
            "three_distinct_physical_endpoint_tests": {
                "raw_p_values": physical_raw,
                "holm_adjusted_p_values": physical_holm,
            },
            "two_primary_model_comparisons": {
                "raw_p_values": comparison_raw,
                "holm_adjusted_p_values": comparison_holm,
            },
        },
        "duplicate_policy": (
            "M4 physical tests repeat M2c residual and M3 VTEC "
            "measurements on the same cohort and are not recounted."
        ),
        "auc_permutation_resolution_warning": (
            "The four primary AUC tests currently use 99 refitted "
            "permutations as a computational pilot. Minimum attainable "
            "Monte Carlo p-value is 0.01; this is not final confirmatory "
            "resolution."
        ),
    }

    primary_group_counts = {
        "time_overlap": len(set(build_dependency_components(sh, "time"))),
        "shared_time_or_station_50d": len(
            set(build_dependency_components(sh, "primary"))
        ),
        "shared_time_or_station_any": len(
            set(build_dependency_components(sh, "station_any"))
        ),
    }

    with (ANALYSIS_DIR / "stage6a_v004_benchmark_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    with (ANALYSIS_DIR / "stage6a_v004_event_features.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ev_rows[0].keys()))
        w.writeheader()
        w.writerows(ev_rows)

    (ANALYSIS_DIR / "stage6a_unit_and_window_tests_v004.json").write_text(
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
                "M2c_vs_M2a": cmp_m2c_m2a,
                "M4_vs_M3": cmp_m4_m3,
            },
            "dependence_group_counts_primary_shallow": primary_group_counts,
            "multiple_testing": multiple_testing,
            "scientific_scope": (
                "Retrospective early-versus-late pre-event temporal "
                "discrimination; not prospective earthquake prediction."
            )
        }, indent=2),
        encoding="utf-8",
    )

    # Build a substantive audit report from this run's actual outputs.
    report_lines = [
        "# Stage 6A Audit-Compliant Repaired Benchmark (v004)",
        "",
        "**Report status:** Generated from the completed v004 region-fix benchmark run.",
        "",
        "**Regional metadata correction:** Frozen macro-regions are read from "
        "Stage 1D `frozen_macro_region_v001` and checked against the Stage 4B "
        "field for every event. Blank or mismatched labels stop the run.",
        "",
        "## 1. Scientific question and scope",
        "",
        "This analysis evaluates retrospective discrimination between an earlier",
        "pre-event window (W0) and a later pre-event window (W1). Each eligible",
        "earthquake contributes a paired W0/W1 classifier sample.",
        "",
        "**This is not prospective earthquake prediction.** It does not establish",
        "operational warning capability, prospective lead time, earthquake-versus-",
        "non-earthquake discrimination, or causal effects.",
        "",
        "## 2. Event-relative temporal design",
        "",
        "All intervals are event-relative hours and use half-open boundaries:",
        "",
        "| Interval | Event-relative hours |",
        "|---|---:|",
        "| B0 | [-1080, -792) |",
        "| W0 | [-792, -552) |",
        "| B1 | [-552, -264) |",
        "| W1 | [-264, -24) |",
        "| Guard | [-24, 0) |",
        "",
        "The classifier compares W0 (label 0) with W1 (label 1). Both are",
        "pre-event periods. The final 24 hours are reserved as a guard interval.",
        "",
        "## 3. Cohort and dependence structure",
        "",
        f"- Retained event-feature rows: {len(ev_rows)}",
        f"- Primary shallow-target events: {len(sh)}",
        f"- Physical null-control events: {len(nc)}",
        f"- Unique stations: {unique_stns}",
        f"- Unique regions: {unique_regs}",
        f"- Original overlap-graph components: {unique_ov}",
        "",
        "The primary dependence grouping connects events when their",
        "event-relative [origin-45 days, origin-1 day) data intervals overlap,",
        "or when they use the same station within 50 days. Components are",
        "reconstructed within each exact analysis cohort after eligibility",
        "filtering. Sensitivity groupings use shared time intervals alone and",
        "shared time intervals or the same station at any temporal separation.",
        "",
        f"- Time-overlap-only components: {primary_group_counts['time_overlap']}",
        "- Shared-time or same-station-within-50-days components: "
        f"{primary_group_counts['shared_time_or_station_50d']}",
        "- Shared-time or same-station-at-any-time components: "
        f"{primary_group_counts['shared_time_or_station_any']}",
        "",
        "These grouping choices address dependence in the available event/station",
        "data. They do not demonstrate generalisation to unseen stations, regions,",
        "or future earthquakes.",
        "",
        "## 4. Primary model families",
        "",
        "- M2a: raw GNSS ZTD-only features.",
        "- M2c: baseline-calibrated ERA5 residual features.",
        "- M3: F10.7-adjusted quiet GIM VTEC features.",
        "- M4: joint calibrated ERA5 residual and VTEC features.",
        "",
        "The benchmark also retains secondary analyses, controls, and sensitivity",
        "subsets. The benchmark summary CSV is the authoritative row-level record",
        "of the numerical model results.",
        "",
        "## 5. Validation and uncertainty procedures",
        "",
        "- Primary validation holds out complete dependence components rather",
        "  than splitting paired observations from the same component across",
        "  training and test folds.",
        "- Feature scaling and model fitting are performed within training folds.",
        "- Group-bootstrap confidence intervals resample complete dependence",
        "  groups and are conditional on the already-computed out-of-fold",
        "  predictions; they do not refit the full pipeline in each bootstrap.",
        "- Primary AUC permutation tests flip paired label orientation at the",
        "  component level and refit the classifier for each permutation.",
        "- Physical endpoint tests use two-sided component-level sign flips.",
        "  Components, rather than individual events, receive equal weight.",
        "- Model comparisons swap complete component-level blocks of fixed",
        "  out-of-fold predictions. These comparisons are conditional on the",
        "  fixed predictions and do not retrain models for each swap.",
        "",
        "The permutation and sign-flip procedures rely on their stated",
        "component-level exchangeability or sign-symmetry assumptions. Those",
        "assumptions are not guaranteed merely by constructing components.",
        "",
        "## 6. Multiple-testing correction",
        "",
        "Holm step-down correction is applied separately to three defined",
        "families: four primary AUC tests, three distinct physical endpoints,",
        "and two matched primary model comparisons.",
        "",
        "M4 repeats the calibrated ERA5 and VTEC physical endpoints already",
        "represented by M2c and M3 on the same cohort. Those duplicate M4",
        "physical tests are not counted again in the three-endpoint family.",
        "",
        "## 7. Permutation-resolution limitation",
        "",
        "The four primary refitted AUC permutation tests currently use 99",
        "permutations as a computational pilot. Their minimum attainable",
        "Monte Carlo p-value is 0.01. This is coarse resolution and is not",
        "suitable as final confirmatory evidence. The pilot count must be",
        "increased and the full-run computational cost assessed before any",
        "confirmatory interpretation.",
        "",
        "## 8. Interpretation limits",
        "",
        "1. The target is earlier-versus-later pre-event temporal discrimination,",
        "   not prospective earthquake prediction.",
        "2. The evaluated cohort is the selected paired Stage 4B cohort; results",
        "   do not automatically generalise to all earthquakes or stations.",
        "3. Grouped validation and component-level resampling reduce specified",
        "   dependence risks but cannot eliminate unmeasured confounding or",
        "   establish physical causality.",
        "4. Bootstrap intervals based on fixed out-of-fold predictions are",
        "   conditional uncertainty estimates, not full-pipeline retraining",
        "   intervals.",
        "5. The 99-permutation AUC analysis is a pilot with limited p-value",
        "   resolution and must not be presented as final confirmation.",
        "6. No operational false-alarm rate, warning lead time, or prospective",
        "   forecast skill is established by this experiment.",
        "",
        "## 9. Output files",
        "",
        "- `analysis/stage6a_v004_benchmark_summary.csv`: model-level results",
        "  and adjusted p-values.",
        "- `analysis/stage6a_v004_event_features.csv`: retained event-level",
        "  feature and metadata rows.",
        "- `analysis/stage6a_unit_and_window_tests_v004.json`: unit/window",
        "  tests, cohort counts, dependence-group counts, model comparisons,",
        "  multiple-testing definitions, and scientific-scope metadata.",
        "- `SHA256SUMS.csv`: file sizes and SHA256 digests for package files.",
        "- `VERIFY_PACKAGE.ps1`: package integrity and scientific-metadata checks.",
        "",
        "## 10. Machine-readable multiple-testing metadata",
        "",
        "```json",
        json.dumps(multiple_testing, indent=2),
        "```",
        "",
        "## 11. Reproducibility note",
        "",
        "This report is written by the v004 script from the values calculated",
        "during that run. It should be distributed together with the CSV/JSON",
        "outputs and the checksum manifest. Do not interpret this report as",
        "evidence that the benchmark has run until the output package exists",
        "and `VERIFY_PACKAGE.ps1` passes.",
        "",
    ]

    report_text = "\n".join(report_lines) + "\n"
    (OUT_DIR / "STAGE6A_AUDIT_REPAIRED_v004.md").write_text(
        report_text, encoding="utf-8"
    )

    # Strict package verifier. The manifest intentionally does not hash itself.
    verifier = r"""
param([string]$PackageRoot = $PSScriptRoot)
$ErrorActionPreference = "Stop"

$manifestPath = Join-Path $PackageRoot "SHA256SUMS.csv"
if (!(Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Missing SHA256SUMS.csv"
}

$expectedPaths = @(
    "STAGE6A_AUDIT_REPAIRED_v004.md",
    "VERIFY_PACKAGE.ps1",
    "analysis/stage6a_v004_benchmark_summary.csv",
    "analysis/stage6a_v004_event_features.csv",
    "analysis/stage6a_unit_and_window_tests_v004.json"
)

$entries = @(Import-Csv -LiteralPath $manifestPath)
if ($entries.Count -ne $expectedPaths.Count) {
    throw "Manifest must contain exactly $($expectedPaths.Count) entries."
}

$rootFull = [System.IO.Path]::GetFullPath($PackageRoot)
$rootFull = $rootFull.TrimEnd([char[]]@(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
))
$rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar

$seen = New-Object 'System.Collections.Generic.HashSet[string]'

foreach ($required in $expectedPaths) {
    $matchesForPath = @($entries | Where-Object {
        [string]$_.relative_path -eq $required
    })
    if ($matchesForPath.Count -ne 1) {
        throw "Manifest entry missing or duplicated: $required"
    }
}

foreach ($entry in $entries) {
    $relativePath = ([string]$entry.relative_path).Trim()
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        throw "Manifest contains a blank relative path."
    }
    if ($expectedPaths -notcontains $relativePath) {
        throw "Unexpected manifest path: $relativePath"
    }
    if (-not $seen.Add($relativePath)) {
        throw "Duplicate manifest path: $relativePath"
    }

    $fullPath = [System.IO.Path]::GetFullPath(
        (Join-Path $PackageRoot $relativePath)
    )
    if (-not $fullPath.StartsWith(
        $rootPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Path escapes package root: $relativePath"
    }
    if (!(Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Missing package file: $relativePath"
    }

    $file = Get-Item -LiteralPath $fullPath
    if ($file.Length -le 0) {
        throw "Empty package file: $relativePath"
    }

    $expectedSize = 0L
    if (-not [long]::TryParse([string]$entry.size_bytes, [ref]$expectedSize)) {
        throw "Invalid size_bytes in manifest: $relativePath"
    }
    if ($file.Length -ne $expectedSize) {
        throw "Size mismatch: $relativePath"
    }

    $expectedHash = ([string]$entry.sha256).Trim().ToLowerInvariant()
    if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA256 field in manifest: $relativePath"
    }

    $actualHash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "SHA256 mismatch: $relativePath"
    }

    Write-Host "PASS: size and SHA256 - $relativePath" -ForegroundColor Green
}

# Validate event-level CSV identity and completeness.
$eventPath = Join-Path $PackageRoot "analysis\stage6a_v004_event_features.csv"
$eventRows = @(Import-Csv -LiteralPath $eventPath)
if ($eventRows.Count -lt 1) {
    throw "Event-features CSV is empty."
}

$idSet = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($row in $eventRows) {
    $eventId = ([string]$row.event_id).Trim()
    if ([string]::IsNullOrWhiteSpace($eventId)) {
        throw "Blank event_id in event-features CSV."
    }
    if (-not $idSet.Add($eventId)) {
        throw "Duplicate event_id in event-features CSV: $eventId"
    }
}

# Validate summary CSV and its adjusted-p-value columns.
$summaryPath = Join-Path $PackageRoot "analysis\stage6a_v004_benchmark_summary.csv"
$summaryRows = @(Import-Csv -LiteralPath $summaryPath)
if ($summaryRows.Count -lt 1) {
    throw "Benchmark summary CSV is empty."
}

$columns = @($summaryRows[0].PSObject.Properties.Name)
$requiredColumns = @(
    "p_auc_holm_four_primary_models",
    "p_physical_holm_three_distinct_endpoints"
)
foreach ($column in $requiredColumns) {
    if ($columns -notcontains $column) {
        throw "Required adjusted-p-value column missing: $column"
    }
}

$aucAdjustedCount = 0
$physicalAdjustedCount = 0
$physicalAdjustedValues = @{}
$duplicatePhysicalKeys = @()
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$numberStyle = [System.Globalization.NumberStyles]::Float

foreach ($row in $summaryRows) {
    $number = 0.0
    $aucValue = [string]$row.p_auc_holm_four_primary_models
    if ([double]::TryParse($aucValue, $numberStyle, $culture, [ref]$number)) {
        if ($number -lt 0.0 -or $number -gt 1.0) {
            throw "AUC Holm-adjusted p-value outside [0,1]."
        }
        $aucAdjustedCount++
    }

    $physicalValue = ([string]$row.p_physical_holm_three_distinct_endpoints).Trim()
    if (
        $physicalValue -and
        $physicalValue -ne "NOT_IN_PRIMARY_FAMILY"
    ) {
        try {
            $physicalObject = ConvertFrom-Json -InputObject $physicalValue -ErrorAction Stop
        }
        catch {
            throw "Invalid JSON physical Holm field in summary row '$($row.model_or_stratum)': $($_.Exception.Message)"
        }

        foreach ($endpointProperty in $physicalObject.PSObject.Properties) {
            $endpoint = [string]$endpointProperty.Name
            $endpointValue = $endpointProperty.Value

            if ([string]$endpointValue.status -eq "DUPLICATE_NOT_RECOUNTED") {
                $duplicatePhysicalKeys += $endpoint
                continue
            }

            $rawPhysicalP = 0.0
            $adjustedPhysicalP = 0.0

            if (-not [double]::TryParse(
                [string]$endpointValue.raw_p,
                $numberStyle,
                $culture,
                [ref]$rawPhysicalP
            )) {
                throw "Invalid raw physical p-value for endpoint '$endpoint'."
            }

            if (-not [double]::TryParse(
                [string]$endpointValue.holm_adjusted_p,
                $numberStyle,
                $culture,
                [ref]$adjustedPhysicalP
            )) {
                throw "Invalid physical Holm-adjusted p-value for endpoint '$endpoint'."
            }

            if (
                $rawPhysicalP -lt 0.0 -or $rawPhysicalP -gt 1.0 -or
                $adjustedPhysicalP -lt 0.0 -or $adjustedPhysicalP -gt 1.0
            ) {
                throw "Physical raw or Holm-adjusted p-value outside [0,1]: $endpoint"
            }

            if ($physicalAdjustedValues.ContainsKey($endpoint)) {
                throw "Duplicate distinct physical endpoint in summary: $endpoint"
            }

            $physicalAdjustedValues[$endpoint] = $adjustedPhysicalP
            $physicalAdjustedCount++
        }
    }
}

if ($aucAdjustedCount -lt 4) {
    throw "Expected four numeric primary AUC Holm-adjusted values; found $aucAdjustedCount."
}
if ($physicalAdjustedCount -ne 3) {
    throw "Expected exactly three distinct physical Holm-adjusted JSON values; found $physicalAdjustedCount."
}
foreach ($expectedEndpoint in @("ztd", "cal", "vtec")) {
    if (-not $physicalAdjustedValues.ContainsKey($expectedEndpoint)) {
        throw "Missing distinct physical Holm-adjusted endpoint: $expectedEndpoint"
    }
}
foreach ($expectedDuplicate in @("cal", "vtec")) {
    if ($duplicatePhysicalKeys -notcontains $expectedDuplicate) {
        throw "Expected M4 duplicate marker missing for endpoint: $expectedDuplicate"
    }
}

# Validate JSON metadata and ensure cohort counts match the CSV.
$jsonPath = Join-Path $PackageRoot "analysis\stage6a_unit_and_window_tests_v004.json"
$meta = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json

if ($null -eq $meta.cohort_counts) {
    throw "JSON missing cohort_counts."
}
if ([int]$meta.cohort_counts.n_total_paired -ne $eventRows.Count) {
    throw "JSON event count does not match event-features CSV row count."
}
if ([string]$meta.scientific_scope -notmatch "not prospective earthquake prediction") {
    throw "JSON scientific-scope limitation is missing."
}

$groups = $meta.dependence_group_counts_primary_shallow
if ($null -eq $groups) {
    throw "JSON missing primary dependence-group counts."
}
foreach ($key in @(
    "time_overlap",
    "shared_time_or_station_50d",
    "shared_time_or_station_any"
)) {
    $value = $groups.$key
    if ($null -eq $value -or [int]$value -lt 1) {
        throw "Missing or invalid dependence-group count: $key"
    }
}

$multipleTesting = $meta.multiple_testing
if ($null -eq $multipleTesting) {
    throw "JSON multiple_testing metadata is missing."
}
if ([string]$multipleTesting.method -notmatch "Holm step-down") {
    throw "JSON multiple_testing method is missing or unexpected."
}

$families = $multipleTesting.families
if ($null -eq $families) {
    throw "JSON multiple_testing.families object is missing."
}

$familySpecifications = @(
    @{ Name = "four_primary_model_auc_tests"; ExpectedCount = 4 },
    @{ Name = "three_distinct_physical_endpoint_tests"; ExpectedCount = 3 },
    @{ Name = "two_primary_model_comparisons"; ExpectedCount = 2 }
)

foreach ($spec in $familySpecifications) {
    $familyProperty = $families.PSObject.Properties[$spec.Name]
    if ($null -eq $familyProperty) {
        throw "Missing multiple-testing family: $($spec.Name)"
    }

    $family = $familyProperty.Value
    if ($null -eq $family.raw_p_values -or $null -eq $family.holm_adjusted_p_values) {
        throw "Family lacks raw or Holm-adjusted p-values: $($spec.Name)"
    }

    $rawProperties = @($family.raw_p_values.PSObject.Properties | ForEach-Object { $_ })
    $adjustedProperties = @($family.holm_adjusted_p_values.PSObject.Properties | ForEach-Object { $_ })

    if ($rawProperties.Count -ne $spec.ExpectedCount) {
        throw "Unexpected raw p-value count in family $($spec.Name): $($rawProperties.Count)"
    }
    if ($adjustedProperties.Count -ne $spec.ExpectedCount) {
        throw "Unexpected Holm-adjusted p-value count in family $($spec.Name): $($adjustedProperties.Count)"
    }

    $rawNames = @($rawProperties | ForEach-Object { $_.Name } | Sort-Object)
    $adjustedNames = @($adjustedProperties | ForEach-Object { $_.Name } | Sort-Object)
    $keyDifferences = @(Compare-Object -ReferenceObject $rawNames -DifferenceObject $adjustedNames)

    if ($keyDifferences.Count -ne 0) {
        throw "Raw and adjusted p-value keys differ in family $($spec.Name)."
    }

    foreach ($entry in $rawProperties) {
        $pValue = 0.0
        if (-not [double]::TryParse(
            [string]$entry.Value,
            $numberStyle,
            $culture,
            [ref]$pValue
        )) {
            throw "Nonnumeric raw p-value in family $($spec.Name): $($entry.Name)"
        }
        if ($pValue -lt 0.0 -or $pValue -gt 1.0) {
            throw "Raw p-value outside [0,1] in family $($spec.Name): $($entry.Name)"
        }
    }

    foreach ($entry in $adjustedProperties) {
        $pValue = 0.0
        if (-not [double]::TryParse(
            [string]$entry.Value,
            $numberStyle,
            $culture,
            [ref]$pValue
        )) {
            throw "Nonnumeric Holm-adjusted p-value in family $($spec.Name): $($entry.Name)"
        }
        if ($pValue -lt 0.0 -or $pValue -gt 1.0) {
            throw "Holm-adjusted p-value outside [0,1] in family $($spec.Name): $($entry.Name)"
        }
    }

    Write-Host "PASS: family $($spec.Name) contains $($spec.ExpectedCount) matched raw/adjusted p-values." -ForegroundColor Green
}

if ([string]$multipleTesting.duplicate_policy -notmatch "not recounted") {
    throw "JSON does not document the M4 duplicate physical-endpoint policy."
}
$warning = [string]$multipleTesting.auc_permutation_resolution_warning
if ($warning -notmatch "99" -or $warning -notmatch "pilot") {
    throw "JSON does not document the 99-permutation AUC pilot limitation."
}

# Validate both matched model comparisons and their Holm-adjusted values.
$comparisons = $meta.paired_model_comparisons
foreach ($key in @("M2c_vs_M2a", "M4_vs_M3")) {
    $comparison = $comparisons.$key
    if ($null -eq $comparison) {
        throw "Missing model comparison metadata: $key"
    }
    $adjusted = 0.0
    if (-not [double]::TryParse(
        [string]$comparison.p_value_holm,
        $numberStyle,
        $culture,
        [ref]$adjusted
    )) {
        throw "Missing numeric Holm-adjusted comparison p-value: $key"
    }
    if ($adjusted -lt 0.0 -or $adjusted -gt 1.0) {
        throw "Comparison Holm-adjusted p-value outside [0,1]: $key"
    }
}

# Validate report substance and scope.
$reportPath = Join-Path $PackageRoot "STAGE6A_AUDIT_REPAIRED_v004.md"
$reportText = Get-Content -LiteralPath $reportPath -Raw
if ($reportText.Length -lt 1000) {
    throw "Audit report is unexpectedly short."
}
if ($reportText -notmatch "not prospective earthquake prediction") {
    throw "Audit report does not state the scientific-scope limitation."
}
if ($reportText -notmatch "Multiple-testing correction") {
    throw "Audit report is missing the multiple-testing section."
}
if ($reportText -notmatch "99" -or $reportText -notmatch "pilot") {
    throw "Audit report is missing the AUC permutation pilot warning."
}

Write-Host "PASS: unique, nonblank event IDs ($($eventRows.Count) rows)." -ForegroundColor Green
Write-Host "PASS: four primary AUC Holm values and three distinct physical Holm values." -ForegroundColor Green
Write-Host "PASS: cohort, dependence groups, duplicate policy, and scientific scope." -ForegroundColor Green
Write-Host "PASS: both matched model comparisons have Holm-adjusted p-values." -ForegroundColor Green
Write-Host "PASS: substantive audit report and 99-permutation pilot caveat." -ForegroundColor Green
Write-Host "ALL CHECKS PASSED (Stage 6A v004 package verified)." -ForegroundColor Cyan
"""
    (OUT_DIR / "VERIFY_PACKAGE.ps1").write_text(
        verifier.lstrip(), encoding="utf-8"
    )

    with (OUT_DIR / "SHA256SUMS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "size_bytes", "sha256"])
        for rel in [
            "STAGE6A_AUDIT_REPAIRED_v004.md",
            "VERIFY_PACKAGE.ps1",
            "analysis/stage6a_v004_benchmark_summary.csv",
            "analysis/stage6a_v004_event_features.csv",
            "analysis/stage6a_unit_and_window_tests_v004.json",
        ]:
            fp = OUT_DIR / rel
            w.writerow([rel, fp.stat().st_size, hashlib.sha256(fp.read_bytes()).hexdigest().lower()])


if __name__ == "__main__":
    main()
