#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_all — 一鍵 build preview：掃 raw/cmoney/ 所有 ETF、跑 preview_build、
             輸出 site/preview/<code>.json + site/preview/etfs.json 索引。

Usage:
  ./tools/preview_all.py                   # build 所有 ETF
  ./tools/preview_all.py 00981A 00982A     # 只 build 指定
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import preview_build  # same dir
import fundclear       # same dir — 規模 / 受益人數 primary source


def _load_fundclear_map() -> dict[str, dict]:
    """一次打 FundClear /api/etf/product/list，回 {code: {totalAv, benefit, ...}}"""
    try:
        rows = fundclear.query_all()
    except Exception as e:
        print(f"[warn] fundclear fetch failed: {e}", file=sys.stderr)
        return {}
    out = {}
    for r in rows:
        code = (r.get("stockNo") or "").upper()
        if code:
            out[code] = r
    return out


def build_all(codes: list[str]) -> list[dict]:
    fc_map = _load_fundclear_map()
    summaries: list[dict] = []
    for code in codes:
        try:
            d = preview_build.build(code)
        except SystemExit as e:
            print(f"[skip] {code}: {e}", file=sys.stderr)
            continue
        out_path = Path(f"site/preview/{code.lower()}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(d, ensure_ascii=False))

        n_main = sum(1 for h in d["current"] if h["weight"] > 1.0)
        n_new = sum(1 for v in d["is_new"].values() if v)
        top3 = sorted(d["current"], key=lambda h: -h["weight"])[:3]
        fc = fc_map.get(code.upper(), {})
        total_av_yi = fc.get("totalAv")   # 單位：億 NT$
        benefit = fc.get("benefit")       # 受益人數
        listing_date = fc.get("listingDate")
        summaries.append({
            "code": d["etf"]["code"],
            "name": d["etf"]["name"],
            "issuer": d["etf"]["issuer"],
            "as_of": d["as_of"],
            "first_date": d["first_date"],
            "n_days": d["n_days"],
            "n_current": len(d["current"]),
            "n_main": n_main,  # weight > 1%
            "n_exited": len(d["exited_codes"]),
            "n_new": n_new,
            "top3": [
                {"code": h["code"], "name": h["name"], "weight": round(h["weight"], 2)}
                for h in top3
            ],
            # FundClear：規模（億 NT$）、受益人數、上市日。未揭露 → null
            "total_av_yi": float(total_av_yi) if total_av_yi not in (None, "") else None,
            "benefit": int(benefit) if benefit not in (None, "") else None,
            "listing_date": listing_date or None,
        })
        print(
            f"[done] {code}  n_days={d['n_days']:<4} current={len(d['current']):<4} "
            f"main>1%={n_main:<3} new={n_new:<3} exited={len(d['exited_codes'])}",
            file=sys.stderr,
        )
    return summaries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    args = ap.parse_args()

    if args.codes:
        codes = [c.upper() for c in args.codes]
    else:
        codes = sorted(p.name for p in Path("raw/cmoney").iterdir() if p.is_dir())

    summaries = build_all(codes)
    # 預設按規模 desc（總資產 億 NT$），null 排最後
    summaries.sort(
        key=lambda s: (s.get("total_av_yi") is None, -(s.get("total_av_yi") or 0), s["code"])
    )

    idx_path = Path("site/preview/etfs.json")
    idx_path.write_text(json.dumps({
        "as_of": max((s["as_of"] for s in summaries), default=""),
        "n_etfs": len(summaries),
        "etfs": summaries,
    }, ensure_ascii=False))
    print(f"\n[index] {idx_path} · {len(summaries)} ETFs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
