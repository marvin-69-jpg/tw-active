#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
query_holdings — 查詢某 ETF 對某檔個股的歷史持倉

用法：
  ./tools/query_holdings.py 00981A 2454              # 聯發科完整歷史
  ./tools/query_holdings.py 00981A 2303 --from 20260401  # 聯電 4 月起
  ./tools/query_holdings.py 00981A 2330 --tail 10    # 台積電最近 10 筆
  ./tools/query_holdings.py 00981A 2454 --json       # JSON 輸出

輸出欄：日期 / 持倉(張) / 增減(張) / 權重(%) / 收盤價 / 投入(億) / 帳面值(億) / 浮損益(億)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_shares(etf: str, code: str) -> list[dict]:
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        print(f"[error] {path} not found", file=sys.stderr)
        sys.exit(1)
    rows = json.loads(path.read_text()).get("Data", [])
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        if r[1] != code:
            continue
        try:
            out.append({
                "date": r[0],
                "code": r[1],
                "name": r[2],
                "weight": float(r[3]) if r[3] not in (None, "") else 0.0,
                "shares": int(float(r[4])),
                "lots": int(float(r[4])) / 1000,
            })
        except Exception:
            continue
    return sorted(out, key=lambda x: x["date"])


def load_prices(etf: str, code: str) -> dict[str, float]:
    path = Path(f"site/preview/{etf.lower()}-prices.json")
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text())
        arr = (d.get("prices") or {}).get(code, [])
        return {p["date"]: float(p["close"]) for p in arr if p.get("date") and p.get("close") is not None}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="ETF 個股歷史持倉查詢")
    ap.add_argument("etf", help="ETF 代號，如 00981A")
    ap.add_argument("code", help="股票代號，如 2454")
    ap.add_argument("--from", dest="from_date", default=None, help="起始日期 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", default=None, help="結束日期 YYYYMMDD")
    ap.add_argument("--tail", type=int, default=None, help="只顯示最後 N 筆")
    ap.add_argument("--json", action="store_true", help="JSON 輸出")
    args = ap.parse_args()

    rows = load_shares(args.etf, args.code)
    if not rows:
        print(f"[warn] {args.etf} 無 {args.code} 持倉記錄", file=sys.stderr)
        sys.exit(0)

    prices = load_prices(args.etf, args.code)

    # date filter
    if args.from_date:
        rows = [r for r in rows if r["date"] >= args.from_date]
    if args.to_date:
        rows = [r for r in rows if r["date"] <= args.to_date]
    if args.tail:
        rows = rows[-args.tail:]

    # enrich with delta + pnl
    enriched = []
    for i, r in enumerate(rows):
        prev_lots = rows[i - 1]["lots"] if i > 0 else 0
        delta_lots = r["lots"] - prev_lots
        px = prices.get(r["date"])
        value = r["lots"] * px * 1000 / 1e8 if px else None
        # cost basis: sum of delta * price up to this row (simplified: show per-row invest)
        invest = delta_lots * px * 1000 / 1e8 if px and delta_lots > 0 else None
        enriched.append({**r, "delta_lots": delta_lots, "price": px, "value_yi": value, "invest_yi": invest})

    # total invested (sum of all positive deltas × price on that day)
    total_invest = sum(
        r["delta_lots"] * r["price"] * 1000 / 1e8
        for r in enriched
        if r["delta_lots"] > 0 and r["price"]
    )
    latest = enriched[-1] if enriched else None
    name = rows[0]["name"] if rows else args.code

    if args.json:
        print(json.dumps({"etf": args.etf, "code": args.code, "name": name,
                          "total_invest_yi": round(total_invest, 2),
                          "rows": enriched}, ensure_ascii=False, indent=2))
        return

    # human-readable table
    print(f"\n{args.etf} × {args.code} {name}  （{rows[0]['date']} → {rows[-1]['date']}）\n")
    header = f"{'日期':<10}  {'持倉(張)':>9}  {'增減(張)':>9}  {'權重%':>6}  {'收盤':>7}  {'增減投入':>9}  {'帳面值':>9}"
    print(header)
    print("-" * len(header))
    for r in enriched:
        px_str = f"{r['price']:.1f}" if r["price"] else "   —"
        val_str = f"{r['value_yi']:.2f}億" if r["value_yi"] is not None else "      —"
        inv_str = f"{r['invest_yi']:+.2f}億" if r["invest_yi"] is not None else "      —"
        delta_str = f"{r['delta_lots']:+.0f}" if r["delta_lots"] != 0 else "      —"
        print(f"{r['date']}  {r['lots']:>9.0f}  {delta_str:>9}  {r['weight']:>6.2f}  {px_str:>7}  {inv_str:>9}  {val_str:>9}")

    print()
    if latest and latest["price"]:
        latest_val = latest["value_yi"] or 0
        pnl = latest_val - total_invest
        print(f"總投入：{total_invest:.2f}億　帳面值：{latest_val:.2f}億　浮損益：{pnl:+.2f}億")
    else:
        print(f"總投入（估）：{total_invest:.2f}億")
    print()


if __name__ == "__main__":
    main()
