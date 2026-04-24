#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
query_movers — 某 ETF 在指定時間區間內加碼/減碼最多的個股

用法：
  ./tools/query_movers.py 00981A --from 20260401       # 4 月以來加碼/減碼前 10
  ./tools/query_movers.py 00981A --from 20260101 --top 20
  ./tools/query_movers.py 00981A --from 20260401 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_shares(etf: str) -> dict[str, list[dict]]:
    """回 {code: [{date, name, weight, lots}, ...]} 時序升冪"""
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        print(f"[error] {path} not found", file=sys.stderr)
        sys.exit(1)
    rows = json.loads(path.read_text()).get("Data", [])
    by_code: dict[str, list] = {}
    for r in rows:
        if len(r) < 5:
            continue
        code = r[1]
        if code in ("C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"):
            continue
        try:
            by_code.setdefault(code, []).append({
                "date": r[0],
                "name": r[2],
                "weight": float(r[3]) if r[3] not in (None, "") else 0.0,
                "lots": int(float(r[4])) / 1000,
            })
        except Exception:
            continue
    for v in by_code.values():
        v.sort(key=lambda x: x["date"])
    return by_code


def load_prices(etf: str) -> dict[str, dict[str, float]]:
    path = Path(f"site/preview/{etf.lower()}-prices.json")
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text())
        out = {}
        for code, arr in (d.get("prices") or {}).items():
            out[code] = {p["date"]: float(p["close"]) for p in arr
                         if p.get("date") and p.get("close") is not None}
        return out
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="ETF 指定時間區間加碼/減碼排行")
    ap.add_argument("etf", help="ETF 代號，如 00981A")
    ap.add_argument("--from", dest="from_date", required=True, help="起始日期 YYYYMMDD")
    ap.add_argument("--to", dest="to_date", default=None, help="結束日期 YYYYMMDD（預設最新）")
    ap.add_argument("--top", type=int, default=10, help="顯示前 N 名（預設 10）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    by_code = load_shares(args.etf)
    prices = load_prices(args.etf)

    movers = []
    for code, rows in by_code.items():
        # anchor：from_date 前最近一筆
        before = [r for r in rows if r["date"] < args.from_date]
        anchor_lots = before[-1]["lots"] if before else 0.0

        # latest：to_date 以內最新一筆
        after = [r for r in rows if r["date"] >= args.from_date]
        if args.to_date:
            after = [r for r in after if r["date"] <= args.to_date]
        if not after:
            continue
        latest = after[-1]

        delta = latest["lots"] - anchor_lots
        if delta == 0:
            continue

        px = (prices.get(code) or {}).get(latest["date"])
        invest = abs(delta) * px * 1000 / 1e8 if px else None

        movers.append({
            "code": code,
            "name": latest["name"],
            "anchor_lots": anchor_lots,
            "latest_lots": latest["lots"],
            "delta_lots": delta,
            "latest_date": latest["date"],
            "weight": latest["weight"],
            "price": px,
            "invest_yi": invest,
        })

    adds = sorted([m for m in movers if m["delta_lots"] > 0],
                  key=lambda x: x["delta_lots"], reverse=True)[:args.top]
    cuts = sorted([m for m in movers if m["delta_lots"] < 0],
                  key=lambda x: x["delta_lots"])[:args.top]

    if args.json:
        print(json.dumps({"etf": args.etf, "from": args.from_date,
                          "adds": adds, "cuts": cuts}, ensure_ascii=False, indent=2))
        return

    period = f"{args.from_date} → {args.to_date or '最新'}"
    print(f"\n{args.etf}  {period}\n")

    def print_table(title, rows, sign):
        print(f"── {title} ──")
        header = f"{'代號':<6}  {'名稱':<10}  {'起始(張)':>9}  {'最新(張)':>9}  {'增減(張)':>9}  {'權重%':>6}  {'金額':>9}"
        print(header)
        print("-" * len(header))
        for r in rows:
            inv = f"{r['invest_yi']:.2f}億" if r["invest_yi"] else "    —"
            print(f"{r['code']:<6}  {r['name']:<10}  {r['anchor_lots']:>9.0f}  "
                  f"{r['latest_lots']:>9.0f}  {r['delta_lots']:>+9.0f}  "
                  f"{r['weight']:>6.2f}  {inv:>9}")
        print()

    print_table(f"加碼 Top {args.top}", adds, "+")
    print_table(f"減碼 Top {args.top}", cuts, "-")


if __name__ == "__main__":
    main()
