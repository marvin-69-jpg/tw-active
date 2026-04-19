#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_prices — 批次抓 site/preview/<etf>.json 裡所有股票的日收盤價，
                 輸出 <etf>-prices.json 供前端 overlay。

Source:
  - TWSE STOCK_DAY（月為單位，legacy endpoint /exchangeReport/STOCK_DAY）
  - 找不到 → 改打 TPEx tradingStock（月為單位）

Output shape:
  {
    "as_of": "20260417",
    "codes": [...],
    "prices": {"2330": [{"date": "20260401", "close": 1855.0}, ...], ...}
  }

Usage:
  ./tools/preview_prices.py site/preview/00981a.json
  ./tools/preview_prices.py site/preview/00981a.json --sleep 0.3
  ./tools/preview_prices.py site/preview/00981a.json --codes 2330,2317  # 只抓部分（debug）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (tw-active preview_prices)"}
TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _month_iter(start: str, end: str) -> list[str]:
    """回傳 YYYYMM 清單（start/end 為 YYYYMMDD）"""
    y, m = int(start[:4]), int(start[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _parse_roc_date(s: str) -> str | None:
    """115/04/01 -> 20260401"""
    s = s.strip()
    try:
        roc_y, mm, dd = s.split("/")
        y = int(roc_y) + 1911
        return f"{y:04d}{int(mm):02d}{int(dd):02d}"
    except Exception:
        return None


def _parse_num(s: str) -> float | None:
    s = s.strip().replace(",", "").replace("+", "")
    if s in ("", "--", "---"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def fetch_twse_month(code: str, yyyymm: str) -> list[dict] | None:
    """
    回傳 [{"date": "YYYYMMDD", "close": float}, ...] 或 None（查無資料）
    """
    date_param = f"{yyyymm}01"
    qs = urllib.parse.urlencode({"response": "json", "date": date_param, "stockNo": code})
    try:
        data = json.loads(_get(f"{TWSE_URL}?{qs}").decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise
        return None
    except Exception:
        return None
    if data.get("stat") != "OK":
        return None
    rows = data.get("data") or []
    out = []
    # TWSE cols: 日期,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數,註記
    for row in rows:
        d = _parse_roc_date(row[0])
        close = _parse_num(row[6])
        if d and close is not None:
            out.append({"date": d, "close": close})
    return out or None


def fetch_tpex_month(code: str, yyyymm: str) -> list[dict] | None:
    y, m = yyyymm[:4], yyyymm[4:6]
    date_param = f"{y}/{m}/01"
    qs = urllib.parse.urlencode({"code": code, "date": date_param, "response": "json"})
    try:
        data = json.loads(_get(f"{TPEX_URL}?{qs}").decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise
        return None
    except Exception:
        return None
    tables = data.get("tables") or []
    if not tables:
        return None
    rows = tables[0].get("data") or []
    out = []
    # TPEx cols: 日期, 成交千股, 成交千元, 開盤, 最高, 最低, 收盤, 漲跌, 成交筆數
    for row in rows:
        d = _parse_roc_date(row[0])
        close = _parse_num(row[6])
        if d and close is not None:
            out.append({"date": d, "close": close})
    return out or None


def fetch_history(code: str, start: str, end: str, sleep_s: float = 0.3) -> list[dict]:
    """回傳整段排序後的 close 序列；自動 TWSE→TPEx fallback；保證月內只打一次成功的來源"""
    months = _month_iter(start, end)
    series: list[dict] = []
    # 判定：先試 TWSE。第一個月如果 TWSE 有回，後續月份都打 TWSE；否則整段改打 TPEx
    src = None
    for i, ym in enumerate(months):
        if src == "twse" or src is None:
            twse = fetch_twse_month(code, ym)
            if twse:
                series.extend(twse)
                src = "twse"
                time.sleep(sleep_s)
                continue
            elif src is None:
                # 第一個月 TWSE 沒資料 → 改試 TPEx
                tpex = fetch_tpex_month(code, ym)
                if tpex:
                    series.extend(tpex)
                    src = "tpex"
                    time.sleep(sleep_s)
                    continue
                else:
                    # 兩邊都沒 → 這檔可能停牌/退市，跳過
                    src = "none"
                    time.sleep(sleep_s)
                    continue
            else:
                # src=twse 但此月沒資料（可能下市）
                time.sleep(sleep_s)
                continue
        elif src == "tpex":
            tpex = fetch_tpex_month(code, ym)
            if tpex:
                series.extend(tpex)
            time.sleep(sleep_s)
    # filter to [start, end]
    series = [p for p in series if start <= p["date"] <= end]
    series.sort(key=lambda x: x["date"])
    return series


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch stock price history for preview overlay")
    ap.add_argument("preview_json", help="e.g. site/preview/00981a.json")
    ap.add_argument("--sleep", type=float, default=0.3, help="delay between requests (s)")
    ap.add_argument("--codes", help="comma-separated subset (debug)")
    ap.add_argument("--out", help="output path (default: <stem>-prices.json next to input)")
    args = ap.parse_args()

    src = Path(args.preview_json)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2
    d = json.loads(src.read_text())
    start = d["first_date"]
    end = d["as_of"]
    all_codes = list(d.get("series", {}).keys())
    if args.codes:
        all_codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    out_path = Path(args.out) if args.out else src.with_name(src.stem + "-prices.json")
    # resume support: if out_path exists, reuse existing codes, only fetch missing
    existing = {}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
            if prev.get("as_of") == end:
                existing = prev.get("prices", {})
                print(f"[resume] {len(existing)}/{len(all_codes)} codes already cached", file=sys.stderr)
        except Exception:
            pass

    prices = dict(existing)
    todo = [c for c in all_codes if c not in prices]
    print(f"[start] {len(todo)} codes to fetch, range {start}–{end}", file=sys.stderr)

    for i, code in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {code} ...", file=sys.stderr, end=" ", flush=True)
        t0 = time.time()
        try:
            series = fetch_history(code, start, end, sleep_s=args.sleep)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                print(f"429 rate limited, sleep 10s and retry", file=sys.stderr)
                time.sleep(10)
                try:
                    series = fetch_history(code, start, end, sleep_s=args.sleep * 2)
                except Exception as exc2:
                    print(f"skip ({exc2})", file=sys.stderr)
                    continue
            else:
                print(f"skip ({exc})", file=sys.stderr)
                continue
        except Exception as exc:
            print(f"skip ({exc})", file=sys.stderr)
            continue
        prices[code] = series
        dt = time.time() - t0
        print(f"{len(series)} pts ({dt:.1f}s)", file=sys.stderr)
        # incremental save every 10 codes so we don't lose progress
        if i % 10 == 0:
            out_path.write_text(json.dumps({"as_of": end, "first_date": start, "codes": all_codes, "prices": prices}, ensure_ascii=False))

    out = {"as_of": end, "first_date": start, "codes": all_codes, "prices": prices, "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    out_path.write_text(json.dumps(out, ensure_ascii=False))
    total_pts = sum(len(v) for v in prices.values())
    empty = sum(1 for v in prices.values() if not v)
    print(f"[done] {out_path} · {len(prices)} codes · {total_pts} points · {empty} empty", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
