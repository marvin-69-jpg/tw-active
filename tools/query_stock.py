#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
query_stock — 查詢某個股被哪幾家主動 ETF 持有

用法：
  ./tools/query_stock.py 2454              # 聯發科：哪幾家持有、各幾張、最近變動
  ./tools/query_stock.py 2330 --date 20260401  # 查特定日期的持倉快照
  ./tools/query_stock.py 2454 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_etf_list() -> list[str]:
    return sorted(p.stem for p in Path("raw/cmoney/shares").glob("*.json"))


def load_shares_for_stock(etf: str, code: str) -> list[dict]:
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        return []
    rows = json.loads(path.read_text()).get("Data", [])
    out = []
    for r in rows:
        if len(r) < 5 or r[1] != code:
            continue
        try:
            out.append({
                "date": r[0],
                "name": r[2],
                "weight": float(r[3]) if r[3] not in (None, "") else 0.0,
                "lots": int(float(r[4])) / 1000,
            })
        except Exception:
            continue
    return sorted(out, key=lambda x: x["date"])


def main():
    ap = argparse.ArgumentParser(description="查詢個股被哪些 ETF 持有")
    ap.add_argument("code", help="股票代號，如 2454")
    ap.add_argument("--date", default=None, help="查指定日期快照 YYYYMMDD（預設最新）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    etfs = load_etf_list()
    results = []

    for etf in etfs:
        rows = load_shares_for_stock(etf, args.code)
        if not rows:
            continue

        if args.date:
            # 找最接近且不超過指定日期的那筆
            candidates = [r for r in rows if r["date"] <= args.date]
            if not candidates:
                continue
            snap = candidates[-1]
            prev = rows[rows.index(snap) - 1] if rows.index(snap) > 0 else None
        else:
            snap = rows[-1]
            prev = rows[-2] if len(rows) >= 2 else None

        delta = snap["lots"] - prev["lots"] if prev else snap["lots"]
        results.append({
            "etf": etf,
            "date": snap["date"],
            "name": snap["name"],
            "lots": snap["lots"],
            "delta_lots": delta,
            "weight": snap["weight"],
            "prev_date": prev["date"] if prev else None,
        })

    results.sort(key=lambda x: x["lots"], reverse=True)

    stock_name = results[0]["name"] if results else args.code

    if args.json:
        print(json.dumps({"code": args.code, "name": stock_name, "holders": results},
                         ensure_ascii=False, indent=2))
        return

    if not results:
        print(f"無任何主動 ETF 持有 {args.code}")
        return

    print(f"\n{args.code} {stock_name}  共 {len(results)} 家 ETF 持有\n")
    header = f"{'ETF':<8}  {'最新日':>10}  {'持倉(張)':>9}  {'增減(張)':>9}  {'權重%':>6}"
    print(header)
    print("-" * len(header))
    for r in results:
        delta_str = f"{r['delta_lots']:+.0f}" if r["delta_lots"] != 0 else "      —"
        print(f"{r['etf']:<8}  {r['date']:>10}  {r['lots']:>9.0f}  {delta_str:>9}  {r['weight']:>6.2f}")

    total = sum(r["lots"] for r in results)
    print(f"\n合計持倉：{total:,.0f} 張\n")


if __name__ == "__main__":
    main()
