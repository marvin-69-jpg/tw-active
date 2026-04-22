#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_scale — 跨主動 ETF 的「規模/申購/自肥」儀表板資料產生器。

研究動機：主動 ETF 的「賺錢」可拆三塊：
1. Selection（選股）— 拿錢買的標的是否跑贏大盤
2. Timing（擇時）— 進出時點是否增值
3. Scale/自肥（規模）— 申購進來當天 basket buy 自己持股，推高 NAV 吸更多申購

第 3 塊是制度層效應、不是 alpha。要看到它，要重建每檔 ETF 每日的：
    - AUM（從 shares × close + cash 推算）
    - 流通單位數（= AUM / NAV）
    - 日淨申購 ≈ Δ流通單位 × NAV

然後把「累計淨申購 / 總 AUM 成長」跟「股價貢獻 / 總 AUM 成長」拆開，
就能看出成長是申購送進來的還是漲出來的。

輸出：site/preview/scale.json
    {
      "as_of": "YYYYMMDD",
      "etfs": [
        {
          "code": "00981A", "name": "...", "issuer": "...",
          "first_date": "YYYYMMDD", "n_days": 220,
          "aum_current": <float, 億元>,
          "aum_first": <float, 億元>,
          "growth_mult": <float>,
          "inflow_cum": <float, 億元>,
          "inflow_share_of_growth": <float, 0-1>,
          "nav_current": <float>,
          "units_current": <float, 億單位>,
          "top_inflow_day": {"date": "YYYYMMDD", "inflow": <float, 億元>},
          "top_outflow_day": {"date": "YYYYMMDD", "inflow": <float, 億元>},
          "series": [{"date": "YYYYMMDD", "aum": <億元>, "nav": <float>,
                      "units": <億單位>, "inflow": <億元>}, ...]
        }, ...
      ]
    }

內部資料路徑：
    raw/cmoney/shares/<ETF>.json     — 每日持股（含 C_NTD 現金）
    raw/cmoney/premium/<ETF>.json    — 每日 NAV/折溢價
    raw/cmoney/meta/<ETF>.json       — ETF 基本資料（名稱/發行商）
    site/preview/<etf>-prices.json   — 每檔持股的歷史收盤

注意：在現金揭露（約 2025-12 起）之前，AUM = holdings × close；
之後加上 C_NTD。早期低估幅度小（現金佔比 <5%）可接受。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_CASH_MARKERS = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"}


def _load_shares(etf: str) -> list | None:
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("Data") or []
    except Exception:
        return None


def _load_nav(etf: str) -> dict[str, float]:
    """raw/cmoney/premium/<ETF>.json → {date: nav}."""
    path = Path(f"raw/cmoney/premium/{etf}.json")
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text()).get("Data") or []
    except Exception:
        return {}
    out: dict[str, float] = {}
    for r in rows:
        if not r or len(r) < 3:
            continue
        try:
            out[r[0]] = float(r[2])
        except Exception:
            continue
    return out


def _load_meta(etf: str) -> dict:
    path = Path(f"raw/cmoney/meta/{etf}.json")
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text())
        rows = d.get("Data") or []
        if not rows:
            return {}
        r = rows[0]
        return {
            "name": r[2] if len(r) > 2 else "",
            "issuer": r[10] if len(r) > 10 else "",
        }
    except Exception:
        return {}


def _load_prices(etf: str) -> dict[str, dict[str, float]]:
    """site/preview/<etf>-prices.json → {code: {date: close}}."""
    path = Path(f"site/preview/{etf.lower()}-prices.json")
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text())
    except Exception:
        return {}
    out: dict[str, dict[str, float]] = {}
    for code, arr in (d.get("prices") or {}).items():
        if not isinstance(arr, list):
            continue
        out[code] = {p["date"]: float(p["close"]) for p in arr
                     if p.get("date") and p.get("close") is not None}
    return out


def _fill_forward(series: list[tuple[str, float]], dates: list[str]) -> dict[str, float]:
    """把稀疏的 (date, val) fill-forward 到 dates 清單上。"""
    by_date = dict(series)
    out = {}
    last = None
    for d in sorted(dates):
        if d in by_date:
            last = by_date[d]
        if last is not None:
            out[d] = last
    return out


def build_etf(etf: str) -> dict | None:
    shares = _load_shares(etf)
    nav = _load_nav(etf)
    meta = _load_meta(etf)
    px = _load_prices(etf)
    if not shares or not nav:
        return None

    # aggregate shares by (date, code) — keep weight for cash AUM derivation
    by_date: dict[str, dict[str, tuple[float, float, bool]]] = {}
    for r in shares:
        if not r or len(r) < 5:
            continue
        d, code, _name, w, sh = r[0], r[1], r[2], r[3], r[4]
        try:
            s = float(sh)
            weight = float(w) if w not in (None, "") else 0.0
        except Exception:
            continue
        is_cash = code in _CASH_MARKERS
        by_date.setdefault(d, {})[code] = (s, weight, is_cash)

    dates = sorted(by_date.keys())
    if len(dates) < 2:
        return None

    # per-date AUM = cash + Σ (shares × close_on_date) for non-cash
    series = []
    for d in dates:
        if d not in nav:
            continue
        # C_NTD (primary cash) alone gives cleanest AUM proxy:
        #   AUM = C_NTD_value / (C_NTD_weight / 100)
        # Because cmoney discloses receivables/payables (RDI_NTD etc.) with negative weights
        # that net out — summing all markers double-counts or cancels. Primary cash is the
        # stable denominator.
        c_ntd_value = 0.0
        c_ntd_weight = 0.0
        cash_total = 0.0
        mkt = 0.0
        missing = 0
        for code, (s, w, is_cash) in by_date[d].items():
            if is_cash:
                cash_total += s
                if code == "C_NTD":
                    c_ntd_value = s
                    c_ntd_weight = w
                continue
            p = px.get(code, {}).get(d)
            if p is None:
                missing += 1
                continue
            mkt += s * p
        if c_ntd_value > 0 and c_ntd_weight > 0.1:
            aum = c_ntd_value / (c_ntd_weight / 100.0)
        else:
            aum = cash_total + mkt
        if aum <= 0:
            continue
        n = nav[d]
        units = aum / n if n > 0 else 0
        series.append({
            "date": d,
            "aum": aum / 1e8,          # 億元
            "nav": n,
            "units": units / 1e8,      # 億單位
            "cash": c_ntd_value / 1e8, # 億元（primary cash only）
        })

    if len(series) < 2:
        return None

    # derive per-day net inflow = Δunits × NAV
    prev_units = None
    inflow_cum = 0.0
    top_in = {"date": None, "inflow": float("-inf")}
    top_out = {"date": None, "inflow": float("inf")}
    for p in series:
        if prev_units is None:
            p["inflow"] = 0.0
        else:
            d_units = p["units"] - prev_units   # 億
            inflow = d_units * p["nav"]          # 億元
            p["inflow"] = inflow
            inflow_cum += inflow
            if inflow > top_in["inflow"]:
                top_in = {"date": p["date"], "inflow": inflow}
            if inflow < top_out["inflow"]:
                top_out = {"date": p["date"], "inflow": inflow}
        prev_units = p["units"]

    aum_first = series[0]["aum"]
    aum_cur = series[-1]["aum"]
    growth_mult = aum_cur / aum_first if aum_first > 0 else 0
    aum_growth = aum_cur - aum_first
    inflow_share = (inflow_cum / aum_growth) if aum_growth > 0 else 0

    return {
        "code": etf,
        "name": meta.get("name", ""),
        "issuer": meta.get("issuer", ""),
        "first_date": series[0]["date"],
        "as_of": series[-1]["date"],
        "n_days": len(series),
        "aum_current": aum_cur,
        "aum_first": aum_first,
        "aum_growth": aum_growth,
        "growth_mult": growth_mult,
        "inflow_cum": inflow_cum,
        "inflow_share_of_growth": inflow_share,
        "nav_current": series[-1]["nav"],
        "units_current": series[-1]["units"],
        "top_inflow_day": top_in if top_in["date"] else None,
        "top_outflow_day": top_out if top_out["date"] else None,
        "series": series,
    }


def main():
    shares_dir = Path("raw/cmoney/shares")
    if not shares_dir.exists():
        print("no raw/cmoney/shares directory", file=sys.stderr)
        sys.exit(1)

    etfs = sorted(p.stem for p in shares_dir.glob("*.json"))
    out = {"etfs": []}
    as_of_max = ""
    for etf in etfs:
        r = build_etf(etf)
        if r is None:
            print(f"  skip {etf} (no data)", file=sys.stderr)
            continue
        out["etfs"].append(r)
        if r["as_of"] > as_of_max:
            as_of_max = r["as_of"]
        print(f"  {etf}: {r['n_days']}d, AUM {r['aum_first']:.0f}→{r['aum_current']:.0f}億"
              f" (×{r['growth_mult']:.1f}), 申購 {r['inflow_cum']:+.0f}億"
              f" ({r['inflow_share_of_growth']*100:.0f}%)", file=sys.stderr)
    out["as_of"] = as_of_max

    # sort by current AUM desc
    out["etfs"].sort(key=lambda x: x["aum_current"], reverse=True)

    dest = Path("site/preview/scale.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nwrote {dest} — {len(out['etfs'])} ETFs, as_of={as_of_max}", file=sys.stderr)


if __name__ == "__main__":
    main()
