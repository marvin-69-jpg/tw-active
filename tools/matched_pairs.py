#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
matched_pairs — H4'：同檔股票被 active vs passive 加碼時 abnormal vol 配對比較。

mechanism: [[wiki/mechanisms/etf-transparency-frontrunning]] H4'

H1 v2 翻盤後最大的 confound 是 stock mix：
  - active ETF 偏小型股（baseline vol 低 → ratio 容易看起來大或小都不準）
  - passive ETF 偏權值股（baseline vol 高 → ratio 較穩）
  - portfolio-level 的 active vs passive abnormal vol 比較，分母不同

H4' 思路：對「**被 active 也被 passive 加過碼的同一支股票**」分別算 abnormal vol，
做 paired test（同股票自我配對）。如果 active median < passive median 在配對控制下
仍然成立 → H1 v2 結論成立、stock mix 不是主因。如果反過來 → 翻案。

方法：
  1. 重用 frontrunning events（active + passive，window-aligned）
  2. 找出 overlap stocks：在 active events 和 passive events 都出現的代號
  3. 對每檔 overlap stock，分別算 active 那組事件的 median r_T，passive 那組的 median r_T
  4. paired comparison：對每檔 stock 算 (active_med - passive_med)，看 distribution
  5. Wilcoxon-style sign 比例 + median-of-differences

Usage:
  uv run tools/matched_pairs.py --no-fetch
  uv run tools/matched_pairs.py --json --no-fetch
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from frontrunning import (  # noqa: E402
    PASSIVE_SHARES_DIR,
    REPO_ROOT,
    SHARES_DIR,
    abnormal_ratio,
    build_events,
    ensure_volumes,
    load_shares,
    load_volume_cache,
)

OUT_PATH = REPO_ROOT / "site" / "preview" / "matched_pairs.json"


def collect_event_ratios(
    events: list[dict],
    vols: dict[str, dict[str, int]],
) -> dict[str, list[float]]:
    """{code: [r_T, r_T, ...]} 對每檔股票收集所有 event 的 abnormal ratio at T."""
    out: dict[str, list[float]] = {}
    for e in events:
        v = vols.get(e["code"], {})
        r = abnormal_ratio(v, e["date"], 0)
        if r is None or r <= 0:
            continue
        out.setdefault(e["code"], []).append(r)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--min-pct", type=float, default=5.0)
    p.add_argument("--min-shares", type=float, default=100_000)
    p.add_argument("--min-events-per-side", type=int, default=2,
                   help="overlap 股票至少 active/passive 各 N 個 event 才入配對（預設 2）")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--sleep", type=float, default=0.2)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    # ===== ACTIVE =====
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
    sys.stderr.write(f"raw passive events: {len(passive_events)}\n")

    # window align passive to active
    active_dates = sorted({e["date"] for e in active_events})
    if not active_dates:
        print(json.dumps({"status": "no_active_events"}))
        return 1
    win_start, win_end = active_dates[0], active_dates[-1]
    passive_events = [e for e in passive_events if win_start <= e["date"] <= win_end]
    sys.stderr.write(f"passive events after window-align [{win_start}..{win_end}]: {len(passive_events)}\n")

    # vols
    codes = {e["code"] for e in active_events + passive_events}
    if args.no_fetch:
        vols = {c: load_volume_cache(c) for c in codes}
    else:
        all_dates = sorted({e["date"] for e in active_events + passive_events})
        earliest_dt = datetime.strptime(all_dates[0], "%Y%m%d").toordinal() - 45
        earliest = datetime.fromordinal(earliest_dt).strftime("%Y%m%d")
        latest = all_dates[-1]
        vols = ensure_volumes(codes, earliest, latest, args.sleep)

    active_ratios = collect_event_ratios(active_events, vols)
    passive_ratios = collect_event_ratios(passive_events, vols)
    sys.stderr.write(f"active stocks with ≥1 ratio: {len(active_ratios)}\n")
    sys.stderr.write(f"passive stocks with ≥1 ratio: {len(passive_ratios)}\n")

    # overlap codes with min events per side
    pairs = []
    for code in sorted(set(active_ratios) & set(passive_ratios)):
        a = active_ratios[code]
        pp = passive_ratios[code]
        if len(a) < args.min_events_per_side or len(pp) < args.min_events_per_side:
            continue
        a_med = statistics.median(a)
        p_med = statistics.median(pp)
        a_mean = statistics.mean(a)
        p_mean = statistics.mean(pp)
        diff_med = a_med - p_med
        # name lookup
        name = ""
        for e in active_events:
            if e["code"] == code:
                name = e["name"]
                break
        if not name:
            for e in passive_events:
                if e["code"] == code:
                    name = e["name"]
                    break
        pairs.append({
            "code": code,
            "name": name,
            "n_active": len(a),
            "n_passive": len(pp),
            "active_median": round(a_med, 3),
            "passive_median": round(p_med, 3),
            "active_mean": round(a_mean, 3),
            "passive_mean": round(p_mean, 3),
            "diff_median": round(diff_med, 3),
        })

    if not pairs:
        print(json.dumps({"status": "no_pairs"}))
        return 1

    # paired summary
    diffs = [p["diff_median"] for p in pairs]
    n_total = len(diffs)
    n_active_higher = sum(1 for d in diffs if d > 0)
    n_passive_higher = sum(1 for d in diffs if d < 0)
    n_equal = n_total - n_active_higher - n_passive_higher
    sign_ratio_active = n_active_higher / n_total if n_total else 0

    summary = {
        "method": {
            "min_pct": args.min_pct,
            "min_shares": args.min_shares,
            "min_events_per_side": args.min_events_per_side,
            "metric": "median(r_T at active events) - median(r_T at passive events) per code; positive = active higher abnormal vol",
            "interpretation": (
                "如果 paired diff median > 0 → 同股票配對下 active 仍較 passive 高，H1 v2 翻盤被 stock mix confound"
                " | "
                "如果 < 0 → 配對控制後 active 真的較弱，H1 v2 結論成立"
            ),
        },
        "n_overlap_codes": n_total,
        "n_active_higher": n_active_higher,
        "n_passive_higher": n_passive_higher,
        "n_equal": n_equal,
        "active_higher_ratio": round(sign_ratio_active, 3),
        "median_of_diffs": round(statistics.median(diffs), 3),
        "mean_of_diffs": round(statistics.mean(diffs), 3),
        "p25_of_diffs": round(statistics.quantiles(diffs, n=4)[0], 3) if n_total >= 4 else None,
        "p75_of_diffs": round(statistics.quantiles(diffs, n=4)[2], 3) if n_total >= 4 else None,
        "pairs": pairs,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("\n# H4' Matched-Pair Test — 同股票 active vs passive abnormal vol\n")
    print(f"事件條件: Δshares ≥ {args.min_shares:,.0f} 且 (Δ% ≥ {args.min_pct}% 或 新建倉)")
    print(f"配對門檻: 同股票需 ≥ {args.min_events_per_side} active events 且 ≥ {args.min_events_per_side} passive events\n")

    print(f"## Paired summary\n")
    print(f"  overlap codes (符合配對門檻):  {n_total}")
    print(f"  active median > passive:      {n_active_higher} ({sign_ratio_active:.0%})")
    print(f"  passive median > active:      {n_passive_higher} ({n_passive_higher/n_total:.0%})")
    print(f"  equal:                        {n_equal}")
    print()
    print(f"  median of (active - passive):  {summary['median_of_diffs']:+.3f}")
    print(f"  mean of (active - passive):    {summary['mean_of_diffs']:+.3f}")
    if summary["p25_of_diffs"] is not None:
        print(f"  p25 / p75:                     {summary['p25_of_diffs']:+.3f} / {summary['p75_of_diffs']:+.3f}")
    print()

    median_diff = summary["median_of_diffs"]
    if median_diff > 0.05:
        print(f"  → H1 v2 翻盤被 stock-mix confound：配對控制後 active 仍高 {median_diff:+.2f}")
    elif median_diff < -0.05:
        print(f"  → H1 v2 結論成立：配對控制後 active 仍較弱 ({median_diff:+.2f})")
    else:
        print(f"  → 配對下 active ≈ passive ({median_diff:+.2f})；H1 v2 portfolio-level 差距可能來自 stock mix")
    print()

    print("## Top 15 active 較強（diff_median 大→小）\n")
    print(f"{'code':<6} {'name':<14} {'n_a':>4} {'n_p':>4} {'a_med':>7} {'p_med':>7} {'diff':>7}")
    for p in sorted(pairs, key=lambda x: -x["diff_median"])[:15]:
        print(f"{p['code']:<6} {p['name'][:14]:<14} {p['n_active']:>4} {p['n_passive']:>4} "
              f"{p['active_median']:>7.2f} {p['passive_median']:>7.2f} {p['diff_median']:>+7.2f}")
    print()

    print("## Top 15 passive 較強（diff_median 小→大）\n")
    print(f"{'code':<6} {'name':<14} {'n_a':>4} {'n_p':>4} {'a_med':>7} {'p_med':>7} {'diff':>7}")
    for p in sorted(pairs, key=lambda x: x["diff_median"])[:15]:
        print(f"{p['code']:<6} {p['name'][:14]:<14} {p['n_active']:>4} {p['n_passive']:>4} "
              f"{p['active_median']:>7.2f} {p['passive_median']:>7.2f} {p['diff_median']:>+7.2f}")
    print()

    print(f"saved → {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
