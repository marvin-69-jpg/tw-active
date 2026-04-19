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


def _load_meta_raw(code: str) -> dict | None:
    """讀 raw/cmoney/meta/<code>.json 取 ETF 基本資料（含費率原文、規模）。
    raw 由私有 CI push；欄位順序見 dump tool。
    回 {mgmt_fee_raw, custody_fee_raw, total_fee_raw, fee_tiered, fee_rates,
        issuer, listing_date, dividend_policy, aum_yi, shares_k} or None。"""
    import re
    path = Path(f"raw/cmoney/meta/{code}.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    rows = data.get("Data") or []
    if not rows:
        return None
    r = rows[0]
    # Title: [年度, 股票代號, 股票名稱, 追蹤指數, 指數追蹤方式, ETF類型, 槓桿/反向,
    #        資產規模(億), 資產種類, 流通單位數(千), 發行商, 發行日期,
    #        管理費, 保管費, 總費用, 配息制度, 計價幣別]
    def _get(i):
        try:
            return r[i]
        except Exception:
            return None

    mgmt_raw = (_get(12) or "").strip()
    cust_raw = (_get(13) or "").strip()

    # 抽出所有 X.X% 當 fee_rates；>1 個不同值 → 階梯式
    def _rates(txt: str) -> list[float]:
        if not txt:
            return []
        found = re.findall(r"(\d+(?:\.\d+)?)\s*[％%]", txt)
        # 把「百分之零點柒」這種中文也補抓（rough）
        rates = []
        for x in found:
            try:
                rates.append(float(x))
            except Exception:
                pass
        return rates

    m_rates = _rates(mgmt_raw)
    c_rates = _rates(cust_raw)
    tiered = len(set(m_rates)) > 1  # 同一欄位有多個不同 % → 階梯

    try:
        aum = float(_get(7)) if _get(7) not in (None, "") else None
    except Exception:
        aum = None
    try:
        shares_k = float(_get(9)) if _get(9) not in (None, "") else None
    except Exception:
        shares_k = None

    listing = _get(11) or ""
    if isinstance(listing, str) and listing:
        # "2025/5/27 上午 12:00:00" → "2025-05-27"
        try:
            head = listing.split()[0]
            y, m, d = head.split("/")
            listing = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except Exception:
            pass

    return {
        "mgmt_fee_raw": mgmt_raw,
        "custody_fee_raw": cust_raw,
        "total_fee_raw": (_get(14) or "").strip(),
        "mgmt_fee_rates": m_rates,
        "custody_fee_rates": c_rates,
        "fee_tiered": tiered,
        "issuer_full": _get(10),
        "listing_date_cmoney": listing or None,
        "dividend_policy": _get(15),
        "aum_yi_cmoney": aum,
        "shares_k": shares_k,
    }


def _effective_fee(meta: dict, aum_yi: float | None) -> dict | None:
    """從階梯文字 + 當前規模推估實付費率。

    很多主動 ETF 公開說明書寫「200 億以下 X%、逾 200 億 Y%」。Yahoo 只顯示最低階
    當作「當前費率」造成散戶低估實付。這個函數抽出階梯門檻 + 費率，計算 blended。

    限制：只處理單一門檻（大多數階梯）；多段階梯直接回 None 讓前端顯示原文。
    """
    import re
    if not meta or aum_yi is None:
        return None
    txt = meta.get("mgmt_fee_raw") or ""
    if not meta.get("fee_tiered"):
        # 固定費率：直接取第一個 rate
        rates = meta.get("mgmt_fee_rates") or []
        if rates:
            return {"mgmt_effective": rates[0], "tiered": False,
                    "threshold_yi": None, "high_rate": rates[0],
                    "low_rate": rates[0]}
        return None

    # 階梯：抽「XXX 億」門檻 + 兩個費率
    # 取第一個數字 + 億 當門檻
    thr_match = re.search(r"(\d+)\s*億", txt)
    rates = meta.get("mgmt_fee_rates") or []
    if not thr_match or len(rates) < 2:
        return None
    try:
        threshold = float(thr_match.group(1))
    except Exception:
        return None
    # 費率高低：通常前面寫門檻以下高、之後低
    high = max(rates[0], rates[1])
    low = min(rates[0], rates[1])
    if aum_yi <= threshold:
        effective = high
    else:
        # blended: threshold 額度按高費率、超出部分按低費率
        effective = (threshold * high + (aum_yi - threshold) * low) / aum_yi
    return {
        "mgmt_effective": round(effective, 3),
        "tiered": True,
        "threshold_yi": threshold,
        "high_rate": high,
        "low_rate": low,
    }


def _load_premium_raw(code: str) -> dict | None:
    """讀 raw/cmoney/premium/<code>.json 取最新一筆 NAV/折溢價。
    21 檔全覆蓋的 primary source；由私有 CI 每日 push raw JSON 到此。
    回 {date: YYYYMMDD, close, nav, premium_pct} or None。"""
    path = Path(f"raw/cmoney/premium/{code}.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    rows = data.get("Data") or []
    if not rows:
        return None
    # Title: [日期, 收盤價, 淨值, 折溢價(%)]，Data 降冪（最新 [0]）
    latest = rows[0]
    try:
        return {
            "date": latest[0],
            "close": float(latest[1]),
            "nav": float(latest[2]),
            "premium_pct": float(latest[3]),
        }
    except Exception:
        return None


def _fetch_nav(code: str) -> tuple[float | None, str | None]:
    """保留作為 secondary source（pocket.tw 下線時 fallback）。"""
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

        # ETF 基本資料（費率、發行商、配息制度、規模、上市日）— CMoney M326
        # raw 由私有 CI push；公開 repo 只消費
        meta = _load_meta_raw(code.upper())
        # FundClear 有些規模欄位會缺；CMoney meta 的 aum_yi 可當備援
        aum_for_fee = total_av_yi if total_av_yi not in (None, "") else (
            meta.get("aum_yi_cmoney") if meta else None)
        try:
            aum_for_fee_f = float(aum_for_fee) if aum_for_fee not in (None, "") else None
        except Exception:
            aum_for_fee_f = None
        fee_effective = _effective_fee(meta, aum_for_fee_f) if meta else None

        # 每日 NAV / 折溢價：primary 從 raw/cmoney/premium/<code>.json 讀（21 檔全覆蓋）
        # raw 由私有 CI 維護、每日 push；此處只是 consumer
        # fallback：etfdaily（投信官網直取、5 檔）當 raw 缺檔時備援
        pd = _load_premium_raw(code.upper())
        if pd:
            nav = pd["nav"]
            nav_date = pd["date"]
            premium_pct = pd["premium_pct"]
        else:
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
            # 費率 / 基本資料（M326）— 研究主題核心：階梯費率拆解，反 Yahoo 誤讀
            "mgmt_fee_raw": meta.get("mgmt_fee_raw") if meta else None,
            "custody_fee_raw": meta.get("custody_fee_raw") if meta else None,
            "fee_tiered": meta.get("fee_tiered") if meta else None,
            "fee_effective": fee_effective,  # {mgmt_effective, tiered, threshold_yi, high_rate, low_rate}
            "dividend_policy": meta.get("dividend_policy") if meta else None,
            "listing_date_cmoney": meta.get("listing_date_cmoney") if meta else None,
            "issuer_full": meta.get("issuer_full") if meta else None,
            "shares_k": meta.get("shares_k") if meta else None,
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
        # ETF code = 5 digits + 1 letter（如 00981A）；過濾 premium/ 等 subdir
        codes = sorted(
            p.name for p in Path("raw/cmoney").iterdir()
            if p.is_dir() and len(p.name) == 6 and p.name[:5].isdigit() and p.name[5].isalpha()
        )

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
