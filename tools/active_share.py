#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
active_share — 算 21 檔台灣主動 ETF 的 Active Share（Cremers-Petajisto 2009）。

定義：AS = 0.5 × Σ|w_fund - w_bench|

因為手上沒有 0050 持股 raw，這版做兩種 benchmark：
1. **vs industry-mean**：用 21 檔自己的均權當 benchmark，看誰跟「平均主動 ETF」差最遠
2. **pairwise matrix**：兩兩之間的 AS，找擁擠交易（pair AS 低 = 持股高度重疊）

只保留 TW 4-digit 股票代號（過濾現金 / 保證金 / 應收付 / 期權 / 外股 / 公司債），
再 renormalize 到 100%。TW 曝險 < 50% 的 ETF 視為非 TW-focused，從報表排除。

Usage:
  uv run tools/active_share.py                    # 預設兩種 benchmark 都印
  uv run tools/active_share.py --pairs 10         # 印 pairwise 最近 10 對
  uv run tools/active_share.py --json             # JSON 輸出
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CMONEY_DIR = REPO_ROOT / "raw" / "cmoney"

TW_STOCK_RE = re.compile(r"^\d{4}[A-Z]?$")  # 2330 / 6781 / 9148B 等


def load_latest_holdings(etf_code: str) -> tuple[str, dict[str, float], float]:
    """
    讀某檔 ETF 最新一天的持股 → (date, {stock_code: weight%}, tw_exposure_pct)。

    只保留 TW 4-digit 股票代號（過濾現金/保證金/應收付/外股/公司債/期權）。
    回傳的 weight dict 已 renormalize 到 100%（純 TW 股票相對權重）。
    第三個 element 是「TW 曝險占整檔 ETF 的比例」（renorm 前的原始 sum）。
    """
    files = sorted(
        f for f in glob.glob(str(CMONEY_DIR / etf_code / "batch_*.json"))
        if not f.endswith(".meta.json")
    )
    if not files:
        return "", {}, 0.0
    d = json.loads(Path(files[-1]).read_text())
    rows = d.get("Data", [])
    if not rows:
        return "", {}, 0.0
    dates = sorted({r[0] for r in rows}, reverse=True)
    latest = dates[0]
    raw: dict[str, float] = {}
    for date_, name, w_pct, code in rows:
        if date_ != latest:
            continue
        if not TW_STOCK_RE.match(code):
            continue
        try:
            raw[code] = float(w_pct)
        except (TypeError, ValueError):
            continue
    tw_exposure = sum(raw.values())
    if tw_exposure <= 0:
        return latest, {}, 0.0
    return latest, {k: v * 100.0 / tw_exposure for k, v in raw.items()}, tw_exposure


def active_share(w_a: dict[str, float], w_b: dict[str, float]) -> float:
    """AS = 0.5 × Σ|w_a - w_b|（單位 %）"""
    codes = set(w_a) | set(w_b)
    return 0.5 * sum(abs(w_a.get(c, 0.0) - w_b.get(c, 0.0)) for c in codes)


def industry_mean(holdings: dict[str, dict[str, float]]) -> dict[str, float]:
    """每檔股票在所有 ETF 的平均權重（沒持有者視為 0）。最後 sum = 100。"""
    n = len(holdings)
    if not n:
        return {}
    all_codes = set().union(*holdings.values())
    return {c: sum(h.get(c, 0.0) for h in holdings.values()) / n for c in all_codes}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pairs", type=int, default=8, help="印最近 / 最遠 N 對 pairwise（預設 8）")
    p.add_argument("--json", action="store_true", help="JSON 輸出")
    args = p.parse_args()

    etfs = sorted(d.name for d in CMONEY_DIR.iterdir() if d.is_dir() and d.name[0].isdigit())
    holdings: dict[str, dict[str, float]] = {}
    dates: dict[str, str] = {}
    tw_exposure: dict[str, float] = {}
    skipped: dict[str, float] = {}
    for etf in etfs:
        date_, h, exp = load_latest_holdings(etf)
        if not h:
            continue
        if exp < 50.0:  # 非 TW-focused（外股 ETF 等）
            skipped[etf] = exp
            continue
        holdings[etf] = h
        dates[etf] = date_
        tw_exposure[etf] = exp

    if not holdings:
        print(json.dumps({"status": "error", "error": "no holdings loaded"}))
        return 1

    mean_w = industry_mean(holdings)

    # AS vs industry-mean
    as_vs_mean = {etf: active_share(h, mean_w) for etf, h in holdings.items()}

    # pairwise
    pair_as: list[tuple[str, str, float]] = []
    sorted_etfs = sorted(holdings)
    for i, a in enumerate(sorted_etfs):
        for b in sorted_etfs[i + 1 :]:
            pair_as.append((a, b, active_share(holdings[a], holdings[b])))
    pair_as.sort(key=lambda t: t[2])

    if args.json:
        print(json.dumps({
            "as_of": max(dates.values()) if dates else None,
            "skipped_non_tw": {etf: round(exp, 1) for etf, exp in skipped.items()},
            "etfs": {etf: {"date": dates[etf], "n_tw_holdings": len(holdings[etf]), "tw_exposure_pct": round(tw_exposure[etf], 1), "as_vs_mean": round(as_vs_mean[etf], 2)} for etf in sorted_etfs},
            "pairs_closest": [{"a": a, "b": b, "as": round(v, 2)} for a, b, v in pair_as[: args.pairs]],
            "pairs_farthest": [{"a": a, "b": b, "as": round(v, 2)} for a, b, v in pair_as[-args.pairs :][::-1]],
        }, ensure_ascii=False, indent=2))
        return 0

    # human format
    print(f"# Active Share — Taiwan Active ETF（純 TW 股票部分，as_of {max(dates.values())}）\n")
    if skipped:
        print(f"已排除非 TW-focused ETF（TW 曝險 < 50%）：")
        for etf, exp in skipped.items():
            print(f"  {etf}  TW 曝險 {exp:.1f}%")
        print()
    print("## AS vs industry-mean（高 = 偏離主動 ETF 共識最遠）\n")
    print(f"{'ETF':<10}{'date':<12}{'N_TW':>5}{'TW%':>7}  {'AS_vs_mean':>10}")
    for etf in sorted(sorted_etfs, key=lambda e: -as_vs_mean[e]):
        print(f"{etf:<10}{dates[etf]:<12}{len(holdings[etf]):>5}{tw_exposure[etf]:>6.1f}%  {as_vs_mean[etf]:>9.1f}%")
    print()

    print(f"## Pairwise AS — 最重疊（低 = 兩家持股近似 / 擁擠）{args.pairs} 對\n")
    for a, b, v in pair_as[: args.pairs]:
        print(f"  {a} ↔ {b}   AS = {v:5.1f}%")
    print()
    print(f"## Pairwise AS — 最分歧（高 = 兩家持股完全不同）{args.pairs} 對\n")
    for a, b, v in pair_as[-args.pairs :][::-1]:
        print(f"  {a} ↔ {b}   AS = {v:5.1f}%")
    print()
    print("note: industry-mean ≠ Cremers-Petajisto 原始 benchmark（應 vs 0050 / TAIEX）；")
    print("      此 v0 用 21 檔均權近似，AS 數字不能直接套 60/80 門檻。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
