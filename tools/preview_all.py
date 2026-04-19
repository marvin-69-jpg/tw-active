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
import preview_prices  # same dir — TWSE STOCK_DAY 月抓，共用於 ETF 本身價格
import fundclear       # same dir — 規模 / 受益人數 primary source
import etfdaily        # same dir — 每日 NAV（7/21 檔投信有公開 API）


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


def _last_n_months(n: int) -> list[str]:
    """回 YYYYMM list，含今天往前 n 個月（含今月）"""
    from datetime import date
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def _fetch_etf_price_series(code: str, months: int = 4) -> list[dict]:
    """抓 ETF 本身最近 months 月的日收盤；跟個股共用 preview_prices 模組。
    第一個月用 TWSE 試，失敗改打 TPEx（幾檔主動 ETF 在 TPEx 上櫃，如 00998A）。
    回 [{date, close}, ...] 依日期遞增。"""
    import time
    series: list[dict] = []
    src = None  # "twse" | "tpex"
    for ym in _last_n_months(months):
        rows = None
        if src in (None, "twse"):
            try:
                rows = preview_prices.fetch_twse_month(code, ym)
            except Exception:
                rows = None
            if rows:
                src = "twse"
        if not rows and src in (None, "tpex"):
            try:
                rows = preview_prices.fetch_tpex_month(code, ym)
            except Exception:
                rows = None
            if rows:
                src = "tpex"
        if rows:
            series.extend(rows)
        time.sleep(0.25)  # 友善間隔
    # dedupe + sort
    seen = set()
    uniq = []
    for p in sorted(series, key=lambda x: x["date"]):
        if p["date"] in seen:
            continue
        seen.add(p["date"])
        uniq.append(p)
    return uniq


def _fetch_nav(code: str) -> tuple[float | None, str | None]:
    """跑 etfdaily.fetch_holdings 取 NAV。只有 5 檔（群益3/安聯2）會回 nav；
    其他 issuer 的 API 目前沒揭露 NAV → (None, None)。"""
    if code not in etfdaily.CATALOG:
        return None, None
    try:
        d = etfdaily.fetch_holdings(code)
    except Exception as e:
        print(f"[warn] etfdaily {code} failed: {e}", file=sys.stderr)
        return None, None
    nav = d.get("nav")
    date = d.get("data_date")
    if isinstance(date, str) and "T" in date:
        date = date.split("T")[0]
    try:
        nav_f = float(nav) if nav not in (None, "") else None
    except Exception:
        nav_f = None
    return nav_f, date


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
        close_price = fc.get("closingPrice")
        try:
            close_f = float(close_price) if close_price not in (None, "") else None
        except Exception:
            close_f = None

        # 每日 NAV：只對 etfdaily 支援的 10 檔嘗試，其中 5 檔（群益3+安聯2）會回 nav
        nav, nav_date = _fetch_nav(code.upper())
        if nav and close_f:
            premium_pct = (close_f - nav) / nav * 100.0
        else:
            premium_pct = None

        # ETF 自己的近 ~4 個月日收盤，供卡片 sparkline
        try:
            etf_prices = _fetch_etf_price_series(code.upper(), months=4)
        except Exception as e:
            print(f"[warn] etf price {code}: {e}", file=sys.stderr)
            etf_prices = []

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
            # FundClear：規模（億 NT$）、受益人數、上市日、收盤價。未揭露 → null
            "total_av_yi": float(total_av_yi) if total_av_yi not in (None, "") else None,
            "benefit": int(benefit) if benefit not in (None, "") else None,
            "listing_date": listing_date or None,
            "close_price": close_f,
            # NAV/溢折價：只對 etfdaily 有 API 的 5 檔（群益3+安聯2）有值
            "nav": nav,
            "nav_date": nav_date,
            "premium_pct": round(premium_pct, 3) if premium_pct is not None else None,
            # ETF 自身價格序列（最近 ~4 個月交易日日收盤）供 sparkline
            "price_series": [{"d": p["date"], "c": p["close"]} for p in etf_prices],
        })
        nav_str = f"NAV={nav:.2f} prem={premium_pct:+.2f}%" if nav else "NAV=-"
        print(
            f"[done] {code}  n_days={d['n_days']:<4} current={len(d['current']):<4} "
            f"main>1%={n_main:<3} new={n_new:<3} exited={len(d['exited_codes']):<3} "
            f"spark={len(etf_prices):<3} {nav_str}",
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
