#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
cumulative_drag — H4：主動 ETF 高 turnover × per-event front-running 累積成的年度 cost
              是否比同期被動 ETF 大？

mechanism: [[wiki/mechanisms/etf-transparency-frontrunning]] H4

H1 v2 翻盤後重新找 angle：active per-event abnormal vol（1.31）反而比 passive（2.12）小。
但主動 ETF 高頻調倉，事件數密度高出非常多——若 cumulative implied cost / AUM / 年
比 passive 大，IP-leak 框架的「主動特別吃虧」依然成立，只是 magnitude 不在單事件而在累積。

方法：
  1. 重用 frontrunning helpers 抓 events + abnormal ratio at T
  2. 同步抓收盤價（FinMind TaiwanStockPrice 同 endpoint，cache 在 .cache/closes/）
  3. 每 event 算兩個 metric：
     - excess_turnover_ntd = max(r_T - 1, 0) × baseline_med_vol × close_T
       （揭露日比 baseline 多出來的「市場成交金額」）
     - manager_drag_proxy = |Δshares| × close_T × max(r_T - 1, 0)
       （manager 調倉曝光金額 × 揭露日溢出強度）
  4. 加總到 ETF 層級
  5. 年化（按 time window 比例 → 12 個月）+ normalize by AUM_NTD
  6. 對照 passive ETFs 同方法

H4 預期：active 年化 / AUM 顯著大於 passive。

Usage:
  uv run tools/cumulative_drag.py                  # 全 pipeline（含 fetch close）
  uv run tools/cumulative_drag.py --no-fetch       # 只用 cache
  uv run tools/cumulative_drag.py --json           # 輸出 JSON
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

# 重用 frontrunning 的所有 helper
sys.path.insert(0, str(Path(__file__).parent))
from frontrunning import (  # noqa: E402
    BASELINE_WINDOW,
    PASSIVE_SHARES_DIR,
    REPO_ROOT,
    SHARES_DIR,
    build_events,
    ensure_volumes,
    load_aum,
    load_shares,
    load_volume_cache,
)

OUT_PATH = REPO_ROOT / "site" / "preview" / "cumulative_drag.json"

# 被動 ETF AUM（億 NTD）— 取自 FundClear totalAv，2026-04-25 抓
# load_aum() 只讀 raw/cmoney/meta/，那邊只有主動 21 檔，這裡補被動 5 檔
PASSIVE_AUM_YI = {
    "0050": 16612.06,
    "0056": 5835.74,
    "006208": 3887.81,
    "00692": 500.40,
    "00891": 410.36,
}


def baseline_median_vol(vols: dict[str, int], event_date: str) -> float | None:
    if not vols:
        return None
    sorted_dates = sorted(vols.keys())
    pos = None
    for i, d in enumerate(sorted_dates):
        if d >= event_date:
            pos = i
            break
    if pos is None or pos < BASELINE_WINDOW:
        return None
    baseline = [vols[sorted_dates[j]] for j in range(pos - BASELINE_WINDOW, pos)]
    baseline = [v for v in baseline if v > 0]
    if len(baseline) < BASELINE_WINDOW // 2:
        return None
    return float(statistics.median(baseline))


def vol_at(vols: dict[str, int], event_date: str) -> float | None:
    if not vols:
        return None
    sorted_dates = sorted(vols.keys())
    for d in sorted_dates:
        if d >= event_date:
            v = vols.get(d)
            return float(v) if v else None
    return None


def close_at(closes: dict[str, float], event_date: str) -> float | None:
    if not closes:
        return None
    sorted_dates = sorted(closes.keys())
    for d in sorted_dates:
        if d >= event_date:
            return closes.get(d)
    return None


def compute_drag(
    events: list[dict],
    vols: dict[str, dict[str, int]],
) -> list[dict]:
    """
    每 event 計算兩個 metric（單位：股數，不乘 close 避開 FinMind 配額）:
      - excess_volume_shares = max(r_T - 1, 0) × baseline_med_vol
        揭露日比 baseline 多出來的「市場成交股數」
      - manager_drag = |Δshares| × max(r_T - 1, 0)
        manager 調倉曝光股數 × 揭露日溢出強度
    """
    out = []
    for e in events:
        v = vols.get(e["code"], {})
        base = baseline_median_vol(v, e["date"])
        vt = vol_at(v, e["date"])
        if base is None or vt is None or base <= 0:
            continue
        ratio = vt / base
        excess_ratio = max(ratio - 1.0, 0.0)
        excess_volume_shares = excess_ratio * base
        manager_drag = abs(e["delta_shares"]) * excess_ratio
        e2 = dict(e)
        e2["r_t"] = ratio
        e2["excess_ratio"] = excess_ratio
        e2["base_med_vol"] = base
        e2["excess_volume_shares"] = excess_volume_shares
        e2["manager_drag"] = manager_drag
        out.append(e2)
    return out


def aggregate(
    enriched: list[dict],
    aum: dict[str, float],
    label: str,
) -> dict:
    """Per ETF 加總、年化、normalize by AUM。"""
    by_etf: dict[str, dict] = {}
    for etf in sorted({e["etf"] for e in enriched}):
        es = [e for e in enriched if e["etf"] == etf]
        if not es:
            continue
        dates = sorted({e["date"] for e in es})
        first = datetime.strptime(dates[0], "%Y%m%d")
        last = datetime.strptime(dates[-1], "%Y%m%d")
        days_span = max((last - first).days, 1)
        years = days_span / 365.0
        annualizer = 1.0 / years if years > 0 else 0.0

        total_excess_volume = sum(e["excess_volume_shares"] for e in es)
        total_manager_drag = sum(e["manager_drag"] for e in es)
        n_evt = len(es)
        n_evt_per_yr = n_evt * annualizer
        annual_excess_volume = total_excess_volume * annualizer
        annual_manager_drag = total_manager_drag * annualizer

        aum_yi = aum.get(etf)
        # normalize per 億 AUM：annual_excess_shares per 億 AUM = shares/(億 NTD)/year
        per_aum_excess = (annual_excess_volume / aum_yi) if aum_yi else None
        per_aum_drag = (annual_manager_drag / aum_yi) if aum_yi else None

        by_etf[etf] = {
            "aum_yi": aum_yi,
            "n_events": n_evt,
            "days_span": days_span,
            "events_per_year": round(n_evt_per_yr, 0),
            "annual_excess_volume_shares": round(annual_excess_volume, 0),
            "annual_manager_drag": round(annual_manager_drag, 0),
            "per_aum_excess_kshares": round(per_aum_excess / 1000, 1) if per_aum_excess is not None else None,
            "per_aum_manager_drag_kshares": round(per_aum_drag / 1000, 1) if per_aum_drag is not None else None,
        }

    # 群組 pooled：總和 / 總 AUM = AUM 加權的 per-AUM 指標
    total_annual_excess = 0.0
    total_annual_drag = 0.0
    total_aum = 0.0
    total_evt = 0
    total_annual_evt = 0.0
    spans = []
    for etf, d in by_etf.items():
        aum_yi = d["aum_yi"]
        if not aum_yi:
            continue
        # reconstruct annual values from rounded ones is fine for aggregation
        if d["per_aum_excess_kshares"] is not None:
            total_annual_excess += d["per_aum_excess_kshares"] * 1000 * aum_yi
            total_annual_drag += d["per_aum_manager_drag_kshares"] * 1000 * aum_yi
            total_aum += aum_yi
        total_evt += d["n_events"]
        total_annual_evt += d["events_per_year"] or 0
        spans.append(d["days_span"])

    pooled = {
        "label": label,
        "n_etfs": len(by_etf),
        "total_aum_yi": round(total_aum, 1),
        "total_events": total_evt,
        "total_events_per_year": round(total_annual_evt, 0),
        "median_days_span": int(statistics.median(spans)) if spans else 0,
        "aum_weighted_excess_kshares_per_yi": round(total_annual_excess / total_aum / 1000, 1) if total_aum > 0 else None,
        "aum_weighted_drag_kshares_per_yi": round(total_annual_drag / total_aum / 1000, 1) if total_aum > 0 else None,
    }

    return {"pooled": pooled, "by_etf": by_etf}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--etfs", default="", help="逗號分隔 ETF（預設 raw/cmoney/shares/ 全部）")
    p.add_argument("--min-pct", type=float, default=5.0)
    p.add_argument("--min-shares", type=float, default=100_000)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--sleep", type=float, default=0.2)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    # ===== ACTIVE =====
    if args.etfs:
        active_etfs = [e.strip().upper() for e in args.etfs.split(",") if e.strip()]
    else:
        active_etfs = sorted(f.stem for f in SHARES_DIR.glob("*.json"))
    active_shares = {etf: load_shares(etf) for etf in active_etfs}
    active_shares = {k: v for k, v in active_shares.items() if v}
    active_events = build_events(active_shares, args.min_pct, args.min_shares)
    sys.stderr.write(f"active events: {len(active_events)} from {len(active_shares)} ETFs\n")

    # ===== PASSIVE =====
    passive_etfs = sorted(f.stem for f in PASSIVE_SHARES_DIR.glob("*.json"))
    passive_shares = {etf: load_shares(etf, PASSIVE_SHARES_DIR) for etf in passive_etfs}
    passive_shares = {k: v for k, v in passive_shares.items() if v}
    passive_events = build_events(passive_shares, args.min_pct, args.min_shares)
    sys.stderr.write(f"raw passive events: {len(passive_events)} from {len(passive_shares)} ETFs\n")

    # 對齊時間窗口：passive 事件限制到 active 的時間範圍內，apples-to-apples
    if active_events:
        active_dates = sorted({e["date"] for e in active_events})
        window_start, window_end = active_dates[0], active_dates[-1]
        passive_events = [e for e in passive_events if window_start <= e["date"] <= window_end]
        sys.stderr.write(
            f"passive events after window-align [{window_start}..{window_end}]: {len(passive_events)}\n"
        )

    all_events = active_events + passive_events
    if not all_events:
        print(json.dumps({"status": "no_events"}))
        return 1

    # 抓 vol + close
    dates = sorted({e["date"] for e in all_events})
    earliest = (datetime.strptime(dates[0], "%Y%m%d").replace(day=1)).strftime("%Y%m%d")
    earliest = (datetime.strptime(earliest, "%Y%m%d")).strftime("%Y%m%d")
    # leave 45 days lookback for baseline
    earliest_dt = datetime.strptime(dates[0], "%Y%m%d")
    earliest_back = earliest_dt.toordinal() - 45
    earliest = datetime.fromordinal(earliest_back).strftime("%Y%m%d")
    latest = dates[-1]

    codes = {e["code"] for e in all_events}
    if args.no_fetch:
        vols = {c: load_volume_cache(c) for c in codes}
    else:
        vols = ensure_volumes(codes, earliest, latest, args.sleep)

    aum = load_aum()
    # 補上被動 ETF AUM（cmoney meta 沒這幾檔）
    for k, v in PASSIVE_AUM_YI.items():
        aum.setdefault(k, v)

    active_enriched = compute_drag(active_events, vols)
    passive_enriched = compute_drag(passive_events, vols)
    sys.stderr.write(f"active enriched: {len(active_enriched)} / {len(active_events)}\n")
    sys.stderr.write(f"passive enriched: {len(passive_enriched)} / {len(passive_events)}\n")

    active_agg = aggregate(active_enriched, aum, "active")
    passive_agg = aggregate(passive_enriched, aum, "passive")

    summary = {
        "method": {
            "min_pct": args.min_pct,
            "min_shares": args.min_shares,
            "baseline_window": BASELINE_WINDOW,
            "window_aligned": True,
            "metrics": [
                "excess_volume_shares = max(r_T-1, 0) × baseline_med_vol",
                "manager_drag = |Δshares| × max(r_T-1, 0)",
                "annualized = sum(metric) × (365 / days_span)",
                "per_aum_kshares_per_yi = annual_shares / 1000 / AUM_yi",
                "passive events restricted to active window for apples-to-apples",
            ],
        },
        "active": active_agg,
        "passive": passive_agg,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    # human format
    print("\n# H4 Cumulative Drag — 主動 ETF 高 turnover × front-running 年化累積暴露\n")
    print(f"事件條件: Δshares ≥ {args.min_shares:,.0f} 且 (Δ% ≥ {args.min_pct}% 或 新建倉)")
    print(f"baseline: median(vol[T-{BASELINE_WINDOW} : T-1])\n")

    print("## Group pooled (AUM-weighted, window-aligned)\n")
    print("  excess_kshares_per_yi = 揭露日 abnormal vol 在 baseline 之上多出來的「年化額外成交股數」"
          " / 億 AUM × 1000")
    print("  drag_kshares_per_yi   = manager 調倉曝光股數 × 揭露日 abnormal 強度，年化 / 億 AUM × 1000\n")
    print(f"{'group':<10} {'n_etf':>6} {'AUM(億)':>10} {'evt/yr':>8} "
          f"{'excess_k/yi':>13} {'drag_k/yi':>12}")
    for label, agg in [("active", active_agg), ("passive", passive_agg)]:
        p = agg["pooled"]
        ex = p['aum_weighted_excess_kshares_per_yi']
        dg = p['aum_weighted_drag_kshares_per_yi']
        ex_str = f"{ex:.1f}" if ex is not None else "-"
        dg_str = f"{dg:.1f}" if dg is not None else "-"
        print(f"{label:<10} {p['n_etfs']:>6} {p['total_aum_yi']:>10.1f} "
              f"{p['total_events_per_year']:>8.0f} "
              f"{ex_str:>13} {dg_str:>12}")
    print()
    a_p = active_agg["pooled"]
    p_p = passive_agg["pooled"]
    if a_p["aum_weighted_drag_kshares_per_yi"] and p_p["aum_weighted_drag_kshares_per_yi"]:
        ratio_excess = a_p["aum_weighted_excess_kshares_per_yi"] / p_p["aum_weighted_excess_kshares_per_yi"]
        ratio_drag = a_p["aum_weighted_drag_kshares_per_yi"] / p_p["aum_weighted_drag_kshares_per_yi"]
        ratio_evt = a_p["total_events_per_year"] / max(p_p["total_events_per_year"], 1)
        print(f"  active / passive ratio:")
        print(f"    events_per_year       = {ratio_evt:>6.1f}×")
        print(f"    excess_volume_per_AUM = {ratio_excess:>6.2f}×")
        print(f"    manager_drag_per_AUM  = {ratio_drag:>6.2f}×")
        if ratio_drag > 1.5:
            print(f"  → H4 supported: 主動 ETF 年化 cumulative drag/AUM 比被動高 {ratio_drag:.1f}×")
        elif ratio_drag > 1.0:
            print(f"  → H4 weak: 主動高 {ratio_drag:.1f}×（差距小）")
        else:
            print(f"  → H4 not supported: 主動反而較低（{ratio_drag:.2f}×）")
    print()

    print("## Active by ETF（per-AUM drag 排序）\n")
    print(f"{'ETF':<8} {'AUM(億)':>10} {'evt/yr':>7} "
          f"{'excess_k/yi':>13} {'drag_k/yi':>12}")
    rows = sorted(active_agg["by_etf"].items(), key=lambda kv: -(kv[1].get("per_aum_manager_drag_kshares") or 0))
    for etf, d in rows:
        aum_str = f"{d['aum_yi']:.1f}" if d['aum_yi'] is not None else "-"
        ex = d.get("per_aum_excess_kshares")
        dg = d.get("per_aum_manager_drag_kshares")
        print(f"{etf:<8} {aum_str:>10} {d['events_per_year']:>7.0f} "
              f"{(ex if ex is not None else 0):>13.1f} "
              f"{(dg if dg is not None else 0):>12.1f}")
    print()

    print("## Passive by ETF\n")
    print(f"{'ETF':<8} {'AUM(億)':>10} {'evt/yr':>7} "
          f"{'excess_k/yi':>13} {'drag_k/yi':>12}")
    rows = sorted(passive_agg["by_etf"].items(), key=lambda kv: -(kv[1].get("per_aum_manager_drag_kshares") or 0))
    for etf, d in rows:
        aum_str = f"{d['aum_yi']:.1f}" if d['aum_yi'] is not None else "-"
        ex = d.get("per_aum_excess_kshares")
        dg = d.get("per_aum_manager_drag_kshares")
        print(f"{etf:<8} {aum_str:>10} {d['events_per_year']:>7.0f} "
              f"{(ex if ex is not None else 0):>13.1f} "
              f"{(dg if dg is not None else 0):>12.1f}")
    print()

    print(f"saved → {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
