#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_build — 從 raw/cmoney/<ETF>/batch_*_r<largest>.json 產出
                site/preview/<etf>.json（前端壓縮版）。

Filter 規則（見 feedback_preview_new_position_flag memory）：
  收錄條件 = days_held ≥ 30  OR  (last_date == as_of AND days_held < 30)
  後者額外 is_new=true 標記

Usage:
  ./tools/preview_build.py 00981A
  ./tools/preview_build.py 00981A --min-days 30
  ./tools/preview_build.py 00981A --out site/preview/00981a.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

# cash-like markers to exclude from single-stock analysis
_CASH_MARKERS = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"}


def _load_daily_shares_delta(etf: str) -> dict | None:
    """讀 raw/cmoney/shares/<etf>.json 算「最新交易日 vs 上一個交易日」的股數變動。

    研究動機：30 日視窗看趨勢，單日視窗看經理人當天的動作。每日揭露延遲 T+1，
    所以「最新 vs 前一天」= 經理人最近一次可觀察的交易決策。

    schema: [日期, 標的代號, 標的名稱, 權重(%), 持有數, 單位]

    回 {
        latest_date, prev_date,
        top_adds:[...], top_reductions:[...],
        new_positions:[...], exits:[...],
        n_adds_total, n_reductions_total, n_holdings,
    } or None（無資料或只有一天）
    """
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    rows = data.get("Data") or []
    if not rows:
        return None

    by_date: dict[str, dict[str, dict]] = {}
    for r in rows:
        if not r or len(r) < 5:
            continue
        d_str, ccode, name, w, sh = r[0], r[1], r[2], r[3], r[4]
        if ccode in _CASH_MARKERS:
            continue
        try:
            shares = float(sh) if sh not in (None, "") else 0.0
            weight = float(w) if w not in (None, "") else 0.0
        except Exception:
            continue
        by_date.setdefault(d_str, {})[ccode] = {
            "name": name, "shares": shares, "weight": weight,
        }
    if len(by_date) < 2:
        return None

    dates_desc = sorted(by_date.keys(), reverse=True)
    latest_date, prev_date = dates_desc[0], dates_desc[1]
    latest, prev = by_date[latest_date], by_date[prev_date]

    WEIGHT_FLOOR = 0.3  # 跟 _load_shares_raw 對齊，過濾試水溫
    adds, reductions, new_positions = [], [], []
    for ccode, cur in latest.items():
        pr = prev.get(ccode)
        if pr is None:
            if cur["weight"] >= WEIGHT_FLOOR:
                new_positions.append({
                    "code": ccode, "name": cur["name"],
                    "shares": cur["shares"], "weight": round(cur["weight"], 2),
                })
            continue
        delta = cur["shares"] - pr["shares"]
        if delta == 0:
            continue
        max_weight = max(cur["weight"], pr["weight"])
        if max_weight < WEIGHT_FLOOR:
            continue
        pct = (delta / pr["shares"] * 100.0) if pr["shares"] > 0 else None
        entry = {
            "code": ccode, "name": cur["name"],
            "shares": cur["shares"], "prev_shares": pr["shares"],
            "delta": delta,
            "pct": round(pct, 2) if pct is not None else None,
            "weight": round(cur["weight"], 2),
            "prev_weight": round(pr["weight"], 2),
        }
        (adds if delta > 0 else reductions).append(entry)

    exits = []
    for ccode, pr in prev.items():
        if ccode not in latest and pr["weight"] >= WEIGHT_FLOOR:
            exits.append({
                "code": ccode, "name": pr["name"],
                "prev_shares": pr["shares"], "prev_weight": round(pr["weight"], 2),
            })

    # 排序：絕對股數變動大的在前（pct 輔助）
    adds.sort(key=lambda e: -abs(e["delta"]))
    reductions.sort(key=lambda e: -abs(e["delta"]))
    new_positions.sort(key=lambda e: -e["weight"])
    exits.sort(key=lambda e: -e["prev_weight"])

    return {
        "latest_date": latest_date,
        "prev_date": prev_date,
        "top_adds": adds[:10],
        "top_reductions": reductions[:10],
        "new_positions": new_positions[:10],
        "exits": exits[:10],
        "n_adds_total": len(adds),
        "n_reductions_total": len(reductions),
        "n_new_total": len(new_positions),
        "n_exits_total": len(exits),
        "n_holdings": len(latest),
    }


def _compute_stock_pnl(etf: str) -> tuple[dict, dict, list[str]] | None:
    """Per-stock P&L from shares × close price.

    研究動機：權重% 被股價漲跌 confound，光看權重軌跡看不出實際賺賠。
    有了股數（raw/cmoney/shares/）× 股價（preview_prices FinMind）就能算：
      CF_t = -Δshares_t × close_t          # buy → 負, sell → 正
      MV_t = shares_t × close_t
      Total P&L_t = MV_t + Σ_{s≤t} CF_s    # 每日累計（未實現 + 已實現）
      cost_basis = Σ max(0, -CF_t)         # 累計買入成本
      return_pct = P&L_final / cost_basis

    假設：當日揭露的 shares 變動發生在那日盤中/收盤，用該日 close 當成交價。
    無股價的日子（FinMind 缺值）記 missing_price_days，P&L 略偏。

    回 (summary_dict, curves_dict, dates_list) 或 None（缺檔）。
      summary_dict: {code: {has_prices, pnl, pnl_pct, mv_now, cost_basis, ...}}
      curves_dict:  {code: [int_pnl_at_date_i for i in 0..len(dates)-1]} (只含 has_prices=true)
      dates_list:   [YYYYMMDD, ...] ETF 全交易日軸（跨 stocks 共用）"""
    shares_path = Path(f"raw/cmoney/shares/{etf}.json")
    prices_path = Path(f"site/preview/{etf.lower()}-prices.json")
    if not shares_path.exists() or not prices_path.exists():
        return None
    try:
        shares_data = json.loads(shares_path.read_text())
        prices_data = json.loads(prices_path.read_text())
    except Exception:
        return None

    # shares: code -> [(date, shares), ...] asc
    by_code: dict[str, list[tuple[str, float]]] = {}
    for r in shares_data.get("Data") or []:
        if not r or len(r) < 5:
            continue
        d_str, ccode, _name, _w, sh = r[0], r[1], r[2], r[3], r[4]
        if ccode in _CASH_MARKERS:
            continue
        try:
            shares = float(sh) if sh not in (None, "") else 0.0
        except Exception:
            continue
        by_code.setdefault(ccode, []).append((d_str, shares))
    for code in by_code:
        by_code[code].sort(key=lambda t: t[0])

    prices_by_code = prices_data.get("prices") or {}

    # 全交易日軸：所有股票 shares 紀錄日期的聯集（CMoney 每日都報 → 即 ETF 交易日集合）
    all_dates: list[str] = sorted({d for s in by_code.values() for d, _ in s})

    def _close_on_or_before(price_series: list[dict], d: str) -> float | None:
        # 線性掃（price_series 已排序 asc）：找 ≤ d 的最後一筆 close
        last = None
        for p in price_series:
            pd = p.get("date")
            if pd and pd <= d:
                last = p.get("close")
            elif pd and pd > d:
                break
        return last

    result: dict[str, dict] = {}
    curves: dict[str, list[int]] = {}
    for code, series in by_code.items():
        price_series = prices_by_code.get(code) or []
        has_prices = len(price_series) > 0
        price_map = {p["date"]: p["close"] for p in price_series if p.get("date")}
        shares_on = {d: sh for d, sh in series}

        prev_shares = 0.0
        cash_flow = 0.0
        cost_basis = 0.0
        missing_price_days = 0
        total_delta_days = 0
        for d_str, shares in series:
            delta = shares - prev_shares
            if delta != 0:
                total_delta_days += 1
                close = price_map.get(d_str)
                if close is None:
                    close = _close_on_or_before(price_series, d_str)
                    if close is None:
                        missing_price_days += 1
                if close is not None:
                    cf = -delta * close
                    cash_flow += cf
                    if cf < 0:
                        cost_basis += -cf
            prev_shares = shares

        latest_date, latest_shares = series[-1]
        latest_price = price_map.get(latest_date)
        if latest_price is None and price_series:
            latest_price = price_series[-1]["close"]

        if not has_prices or latest_price is None:
            result[code] = {
                "has_prices": False,
                "shares_latest": latest_shares,
                "latest_date": latest_date,
            }
            continue

        mv_now = latest_shares * latest_price
        pnl = mv_now + cash_flow
        pnl_pct = (pnl / cost_basis * 100.0) if cost_basis > 0 else None

        result[code] = {
            "has_prices": True,
            "shares_latest": latest_shares,
            "latest_date": latest_date,
            "latest_price": round(latest_price, 2),
            "mv_now": round(mv_now, 0),
            "cost_basis": round(cost_basis, 0),
            "pnl": round(pnl, 0),
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "missing_price_days": missing_price_days,
            "total_delta_days": total_delta_days,
        }

        # 累計 P&L 曲線（對齊 all_dates）
        # walk through ETF date axis，每日算 cf_cum + mv_t（shares_t × last_known_close）
        curve: list[int] = []
        cf_cum = 0.0
        last_shares = 0.0
        last_close = None
        for d in all_dates:
            cur_shares = shares_on.get(d, last_shares)  # 缺值 carry forward（理論上 CMoney 每日都有）
            delta = cur_shares - last_shares
            close_today = price_map.get(d)
            if close_today is None:
                close_today = _close_on_or_before(price_series, d)
            if delta != 0 and close_today is not None:
                cf_cum += -delta * close_today
            if close_today is not None:
                last_close = close_today
            mv = cur_shares * last_close if (last_close is not None and cur_shares > 0) else 0.0
            curve.append(int(round(mv + cf_cum)))
            last_shares = cur_shares
        curves[code] = curve

    return result, curves, all_dates


ISSUER_OF = {
    # minimal mapping for preview caption; extend as needed
    "00981A": ("主動統一台股增長", "統一投信"),
    "00982A": ("主動統一台股動能", "統一投信"),
    "00980A": ("主動群益台灣強棒", "群益投信"),
    "00988A": ("主動野村臺灣優選", "野村投信"),
    "00983A": ("主動國泰台灣領航", "國泰投信"),
    "00984A": ("主動凱基台灣優勢", "凱基投信"),
    "00985A": ("主動富邦台灣中小", "富邦投信"),
    "00986A": ("主動中信台灣老將", "中信投信"),
    "00987A": ("主動元大台灣優質", "元大投信"),
    "00989A": ("主動群益科技高息", "群益投信"),
    "00990A": ("主動永豐高息優選", "永豐投信"),
    "00991A": ("主動兆豐台灣指數", "兆豐投信"),
    "00992A": ("主動野村台灣股息", "野村投信"),
    "00993A": ("主動富邦台灣智慧", "富邦投信"),
    "00994A": ("主動永豐科技百強", "永豐投信"),
    "00995A": ("主動國泰息收雙王", "國泰投信"),
    "00996A": ("主動中信台灣多元", "中信投信"),
    "00997A": ("主動元大台灣先驅", "元大投信"),
    "00998A": ("主動群益潛力旗艦", "群益投信"),
    "00400A": ("主動宏遠複合", "宏遠投信"),
    "00401A": ("主動凱基多資產", "凱基投信"),
}


def load_latest_raw(etf: str) -> tuple[list[list], str]:
    """Return (merged_rows, source_desc). Union all batch_*_r*.json files and dedupe by (date, code).

    Why union: daily CI pushes r=3 (3-day delta) batches; weekly/ad-hoc pushes r=400 / r=800
    backfills. Picking a single batch either loses freshness (stale r=400) or loses history
    (today's r=3 only has 3 days → everything looks "new"). Union gives both: today's rows
    from the latest r=3 plus full history from the newest r=400/r=800 backfill.
    """
    pattern = f"raw/cmoney/{etf}/batch_*_r*.json"
    files = [p for p in glob.glob(pattern) if not p.endswith(".meta.json")]
    if not files:
        raise SystemExit(f"no raw data files for {etf} under raw/cmoney/")
    # Sort oldest-first so newer batches overwrite older ones on collision.
    def _rank(p: str) -> tuple[str, int]:
        name = Path(p).stem
        try:
            r = int(name.split("_r")[-1])
        except Exception:
            r = 0
        ts = name.split("_")[1] if "_" in name else ""
        return (ts, r)
    files.sort(key=_rank)
    merged: dict[tuple, list] = {}
    for p in files:
        data = json.loads(Path(p).read_text())
        rows = data.get("Data") or data.get("data") or []
        for r in rows:
            if len(r) < 4:
                continue
            key = (r[0], r[3])  # (date, code)
            merged[key] = r
    all_rows = list(merged.values())
    return all_rows, f"{len(files)} batches merged ({len(all_rows)} rows)"


def _load_shares_map(etf: str) -> dict[tuple[str, str], float]:
    """(date, code) -> shares from raw/cmoney/shares/<etf>.json.

    研究動機：series 裡權重受股價 confound，ETF inflow 時 shares 增但 weight 可能不動甚至降。
    event detection 要用 shares 當 ground truth（見 feedback_shares_not_weight_for_comparison）。
    schema: [date, code, name, weight, shares, unit]"""
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    out: dict[tuple[str, str], float] = {}
    for r in data.get("Data") or []:
        if not r or len(r) < 5:
            continue
        d_str, ccode, _name, _w, sh = r[0], r[1], r[2], r[3], r[4]
        try:
            out[(d_str, ccode)] = float(sh) if sh not in (None, "") else 0.0
        except Exception:
            continue
    return out


def build(etf: str, min_days: int = 30) -> dict:
    rows, src = load_latest_raw(etf)
    shares_map = _load_shares_map(etf)
    # rows: [date, name, weight(%), code]
    by_code: dict[str, list[dict]] = {}
    name_of: dict[str, str] = {}
    for r in rows:
        if len(r) < 4:
            continue
        date, name, wt, code = r[0], r[1], r[2], r[3]
        try:
            weight = float(wt)
        except Exception:
            continue
        if not code or not date:
            continue
        entry = {"date": date, "weight": weight}
        sh = shares_map.get((date, code))
        if sh is not None:
            entry["shares"] = sh
        by_code.setdefault(code, []).append(entry)
        name_of[code] = name

    for code in by_code:
        by_code[code].sort(key=lambda x: x["date"])

    all_dates = sorted({r[0] for r in rows if len(r) >= 1 and r[0]})
    as_of = all_dates[-1] if all_dates else ""
    first_date = all_dates[0] if all_dates else ""
    n_days = len(all_dates)

    # Today's holdings
    current = []
    for code, s in by_code.items():
        last = s[-1]
        if last["date"] == as_of and last["weight"] > 0:
            current.append({"date": as_of, "code": code, "name": name_of[code], "weight": last["weight"]})
    current.sort(key=lambda x: -x["weight"])

    # days_held: number of distinct dates the stock appeared
    days_held = {code: len(s) for code, s in by_code.items()}

    # Apply filter
    series_out: dict[str, list[dict]] = {}
    is_new: dict[str, bool] = {}
    for code, s in by_code.items():
        # 跳過從未持有（weight 全 0）的 cash-like 條目（PFUR_NTD 等）
        if not any(p["weight"] > 0 for p in s):
            continue
        n = days_held[code]
        last_date = s[-1]["date"]
        held_now = last_date == as_of and s[-1]["weight"] > 0
        if n >= min_days:
            series_out[code] = s
        elif held_now:
            # 新建倉，仍在場上：保留並打 NEW 標記
            series_out[code] = s
            is_new[code] = True
        # else: 短期已出清，丟掉（noise）

    # Exited codes: only long-held (days_held >= min_days) positions that are no longer held.
    # 短期已出清（days_held < min_days）= 試水溫/停損雜訊，跟 current side 的 filter 對齊，一併丟掉。
    # 這層 filter 保證 exited_codes 都在 series_out 裡 → 有 name/chart data 可點看歷史。
    #
    # Raw 資料源（CMoney）對「出清」有兩種表示法：
    #   (a) 出清後補 weight=0 rows 一路到 as_of（e.g. 2357 華碩）
    #   (b) 出清後直接不再出現（e.g. 1326 台化）
    # 為了前端 chart 一致呈現「權重一路降到 0%」，(b) 類要在 last_date 之後補一筆 weight=0 synthetic row。
    exited_codes = []
    exit_date: dict[str, str] = {}   # code -> last date with weight > 0（真正出清日）
    active_days: dict[str, int] = {} # code -> 非零權重的天數（真正持有天數）
    for code, s in series_out.items():
        if is_new.get(code):
            continue  # NEW 倉位本來就還在場上，不算 exited
        last = s[-1]
        if last["date"] != as_of or last["weight"] == 0:
            exited_codes.append(code)
            nz = [p for p in s if p["weight"] > 0]
            exit_date[code] = nz[-1]["date"] if nz else s[-1]["date"]
            active_days[code] = len(nz)
            # 補 synthetic zero row 讓 chart 視覺化出「降到 0」
            if last["weight"] > 0:
                # 找 last_date 後的下一個交易日（優先），否則放 as_of
                next_day = next((d for d in all_dates if d > last["date"]), as_of)
                s.append({"date": next_day, "weight": 0.0})
    # 按實際出清日倒序（最近出清的排前面）
    exited_codes.sort(key=lambda c: exit_date.get(c, ""), reverse=True)

    name, issuer = ISSUER_OF.get(etf, (etf, ""))
    pnl_tuple = _compute_stock_pnl(etf)
    if pnl_tuple is not None:
        pnl_summary, pnl_curves, pnl_dates = pnl_tuple
    else:
        pnl_summary, pnl_curves, pnl_dates = None, None, None
    out = {
        "etf": {"code": etf, "name": name, "issuer": issuer},
        "as_of": as_of,
        "first_date": first_date,
        "n_days": n_days,
        "current": current,
        "exited_codes": exited_codes,
        "exit_date": exit_date,
        "active_days": active_days,
        "series": series_out,
        "name_of": {k: name_of[k] for k in series_out},
        "days_held": {k: days_held[k] for k in series_out},
        "is_new": is_new,  # {code: true} only for brand-new positions
        "daily_shares": _load_daily_shares_delta(etf),
        "pnl": pnl_summary,
        "pnl_curve_dates": pnl_dates,
        "pnl_curves": pnl_curves,
        "_source_file": src,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build preview JSON from raw/cmoney/")
    ap.add_argument("etf", help="ETF code, e.g. 00981A")
    ap.add_argument("--min-days", type=int, default=30, help="default 30")
    ap.add_argument("--out", help="output path; default site/preview/<etf lower>.json")
    args = ap.parse_args()

    out = build(args.etf, min_days=args.min_days)
    default_out = f"site/preview/{args.etf.lower()}.json"
    out_path = Path(args.out or default_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False))
    newly = [c for c, v in out["is_new"].items() if v]
    print(f"[done] {out_path}", file=sys.stderr)
    print(f"  range: {out['first_date']} → {out['as_of']} ({out['n_days']} days)", file=sys.stderr)
    print(f"  current: {len(out['current'])} · kept series: {len(out['series'])} · exited: {len(out['exited_codes'])}", file=sys.stderr)
    print(f"  NEW positions: {len(newly)}" + (" (" + ", ".join(newly) + ")" if newly else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
