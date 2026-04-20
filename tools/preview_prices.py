#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_prices — 批次抓 site/preview/<etf>.json 裡所有股票的日收盤價，
                 輸出 <etf>-prices.json 供前端 overlay / P&L 計算。

Source (2026-04-20 Round 48): **FinMind API**（api.finmindtrade.com/api/v4/data）
  - TaiwanStockPrice dataset，TWSE + TPEx 統一一個 endpoint
  - 一次請求拿整段歷史 daily OHLC（無需 .TW/.TWO 區分、無需月月打）
  - ISO date 輸出（YYYY-MM-DD），會轉成 repo 內 convention YYYYMMDD
  - 免費 tier 免 token，~600 req/hr，對 500+ 檔主動 ETF 持股夠用
  - 非 TW 股（AMD US / 268A JP / 202605TX）skip 不抓

棄用原因：
  - TWSE STOCK_DAY legacy endpoint：每檔每月要一個 request（12× 請求量），常 429
  - Yahoo Finance chart v8：IP-level rate limiting 從 pod 打很容易被擋
  - 改走 FinMind 後預期 10× 快 + 穩定

Output shape:
  {
    "as_of": "20260417",
    "first_date": "20250526",
    "codes": [...],
    "prices": {"2330": [{"date": "20260401", "close": 1855.0}, ...], ...},
    "source": "finmind_v4"
  }

Usage:
  ./tools/preview_prices.py site/preview/00981a.json
  ./tools/preview_prices.py site/preview/00981a.json --sleep 0.2
  ./tools/preview_prices.py site/preview/00981a.json --codes 2330,2317  # debug
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (tw-active preview_prices)"}
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TOKEN_FILE = Path("/home/node/.finmind-token")
# 跨 ETF 共用的 per-stock 快取：2330 在多個 ETF 裡都出現，只抓一次。
# 以首次抓取時的最寬日期範圍儲存，讀取時 clip 成該 ETF 需要的範圍。
CACHE_DIR = Path(".cache/prices")

# TW 股代號格式：4-6 digits，可選 1 個大寫英文後綴（例 00981A）
# 排除：AMD US / 268A JP / 202605TX / C_NTD / BLSH US 等
_TW_CODE_RE = re.compile(r"^\d{4,6}[A-Z]?$")


def _load_token() -> str | None:
    """讀 /home/node/.finmind-token；無 token 則走 no-auth tier（較低 rate limit）。"""
    if TOKEN_FILE.exists():
        try:
            tok = TOKEN_FILE.read_text().strip()
            return tok if tok else None
        except Exception:
            return None
    return None


def _is_tw_stock_code(code: str) -> bool:
    return bool(_TW_CODE_RE.fullmatch(code))


def _get(url: str, token: str | None = None, timeout: int = 30) -> bytes:
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _to_iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _to_yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


def fetch_finmind(code: str, start: str, end: str, token: str | None = None) -> tuple[list[dict], int]:
    """抓 FinMind TaiwanStockPrice；回 (series, status)。
    status: 200 = 成功（series 可能空 = 無交易）、402 = rate limit、其他 = 失敗。"""
    qs = urllib.parse.urlencode({
        "dataset": "TaiwanStockPrice",
        "data_id": code,
        "start_date": _to_iso(start),
        "end_date": _to_iso(end),
    })
    url = f"{FINMIND_URL}?{qs}"
    raw = _get(url, token=token)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return [], -1
    status = data.get("status", -1)
    if status != 200:
        return [], status
    rows = data.get("data") or []
    series = []
    for r in rows:
        iso = r.get("date")
        close = r.get("close")
        if not iso or close is None:
            continue
        series.append({"date": _to_yyyymmdd(iso), "close": round(float(close), 2)})
    series.sort(key=lambda x: x["date"])
    return series, 200


class RateLimitError(Exception):
    pass


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _load_cache(code: str) -> dict | None:
    """回 {first_date, as_of, series} 或 None。"""
    p = _cache_path(code)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save_cache(code: str, start: str, end: str, series: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(code).write_text(json.dumps({
        "code": code,
        "first_date": start,
        "as_of": end,
        "series": series,
    }, ensure_ascii=False))


def fetch_history(code: str, start: str, end: str, sleep_s: float = 0.2,
                  token: str | None = None, use_cache: bool = True) -> list[dict]:
    """TW 股歷史日收盤。優先走 per-stock 全域快取（.cache/prices/），
    快取涵蓋目標範圍 → 直接 clip 回傳；否則抓 FinMind 並更新快取。"""
    if not _is_tw_stock_code(code):
        return []

    if use_cache:
        cached = _load_cache(code)
        if cached and cached["first_date"] <= start and cached["as_of"] >= end:
            return [p for p in cached["series"] if start <= p["date"] <= end]

    # 抓更寬範圍：若快取已存在但範圍不夠，直接抓快取的 union
    fetch_start, fetch_end = start, end
    if use_cache:
        cached = _load_cache(code)
        if cached:
            fetch_start = min(fetch_start, cached["first_date"])
            fetch_end = max(fetch_end, cached["as_of"])

    try:
        series, status = fetch_finmind(code, fetch_start, fetch_end, token=token)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitError("HTTP 429")
        return []
    finally:
        time.sleep(sleep_s)

    if status == 402:
        raise RateLimitError("FinMind status 402 (hourly quota exceeded)")
    if status != 200:
        return []

    if use_cache:
        _save_cache(code, fetch_start, fetch_end, series)

    return [p for p in series if start <= p["date"] <= end]


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch stock price history from FinMind for preview overlay & P&L")
    ap.add_argument("preview_json", help="e.g. site/preview/00981a.json")
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between requests (s)")
    ap.add_argument("--codes", help="comma-separated subset (debug)")
    ap.add_argument("--out", help="output path (default: <stem>-prices.json next to input)")
    ap.add_argument("--no-cache", action="store_true", help="disable per-stock global cache")
    args = ap.parse_args()
    token = _load_token()
    if token:
        print(f"[auth] FinMind token loaded from {TOKEN_FILE}", file=sys.stderr)

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
    existing = {}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
            if prev.get("as_of") == end and prev.get("source") == "finmind_v4":
                existing = prev.get("prices", {})
                print(f"[resume] {len(existing)}/{len(all_codes)} codes already cached (finmind_v4)", file=sys.stderr)
        except Exception:
            pass

    prices = dict(existing)
    todo = [c for c in all_codes if c not in prices]
    skipped_foreign = [c for c in all_codes if not _is_tw_stock_code(c)]
    if skipped_foreign:
        preview = skipped_foreign[:5]
        suffix = "..." if len(skipped_foreign) > 5 else ""
        print(f"[info] skip {len(skipped_foreign)} non-TW codes: {preview}{suffix}", file=sys.stderr)
    print(f"[start] {len(todo)} codes via FinMind, range {start}–{end}", file=sys.stderr)

    for i, code in enumerate(todo, 1):
        if not _is_tw_stock_code(code):
            prices[code] = []
            continue
        print(f"[{i}/{len(todo)}] {code} ...", file=sys.stderr, end=" ", flush=True)
        t0 = time.time()
        try:
            series = fetch_history(code, start, end, sleep_s=args.sleep,
                                   token=token, use_cache=not args.no_cache)
        except RateLimitError as exc:
            print(f"RATE LIMIT ({exc}); stop here — 已存的 cache 保留，等 reset 後再跑", file=sys.stderr)
            break
        except urllib.error.HTTPError as exc:
            print(f"skip HTTP {exc.code}", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"skip ({exc})", file=sys.stderr)
            continue
        prices[code] = series
        dt = time.time() - t0
        print(f"{len(series)} pts ({dt:.1f}s)", file=sys.stderr)
        if i % 20 == 0:
            out_path.write_text(json.dumps({"as_of": end, "first_date": start, "codes": all_codes, "prices": prices, "source": "finmind_v4"}, ensure_ascii=False))

    out = {
        "as_of": end,
        "first_date": start,
        "codes": all_codes,
        "prices": prices,
        "source": "finmind_v4",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False))
    total_pts = sum(len(v) for v in prices.values())
    empty_tw = sum(1 for c, v in prices.items() if _is_tw_stock_code(c) and not v)
    tw_count = sum(1 for c in prices if _is_tw_stock_code(c))
    print(f"[done] {out_path} · {tw_count} TW codes · {total_pts} points · {empty_tw} empty TW", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
