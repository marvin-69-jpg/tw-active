#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
frontrunning — 主動 ETF 揭露日的「異常成交量」實證（H1, etf-transparency-frontrunning）。

研究問題：台灣主動 ETF 強制每日揭露持股，AP / HFT / 對沖看得到當日 PCF 後，
是否會在揭露日（T）/ 隔日（T+1）對主動 ETF 大量加碼的成分股出現「同向異常成交量」？

方法：
  1. 從 raw/cmoney/shares/<ETF>.json 找「加碼事件」(date, code, Δshares > 0)
     - 顯著條件：delta_pct >= --min-pct OR is_new_position
     - 絕對下限：delta_shares >= --min-shares（過濾雜訊）
  2. 對每個 event 對應的股票，從 FinMind 抓 daily Trading_Volume
  3. 算 abnormal ratio：
        r(T)   = vol(T)   / median(vol[T-21:T-1])
        r(T+1) = vol(T+1) / median(vol[T-21:T-1])
     Null hypothesis: mean ratio ≈ 1.0；H1: > 1.0
  4. 聚合：overall pooled / per-ETF / ETF AUM 排序

注意：
  - 「Δshares > 0」是 noisy events—混了主動加碼與 AP creation 的兩個 channel
  - 這版不分離 channel，只看 aggregate signal；如果 aggregate 都看不到 abnormal
    vol，那 H1 不成立或 noise 太大
  - 對照組（passive ETF 加碼相同股票）留 v2

輸出：site/preview/frontrunning.json + 終端摘要

Usage:
  uv run tools/frontrunning.py                     # 跑全 pipeline（events → fetch → analyze）
  uv run tools/frontrunning.py --etfs 00981A,00995A  # 限定 ETF
  uv run tools/frontrunning.py --min-pct 10        # 提高顯著條件
  uv run tools/frontrunning.py --no-fetch          # 不抓 FinMind（用 cache 內現有的）
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SHARES_DIR = REPO_ROOT / "raw" / "cmoney" / "shares"
META_DIR = REPO_ROOT / "raw" / "cmoney" / "meta"
VOL_CACHE = REPO_ROOT / ".cache" / "volumes"
OUT_PATH = REPO_ROOT / "site" / "preview" / "frontrunning.json"

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TOKEN_FILE = Path("/home/node/.finmind-token")
UA = {"User-Agent": "Mozilla/5.0 (tw-active frontrunning)"}

_CASH_MARKERS = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD", "DA_NTD"}
_TW_CODE_RE = re.compile(r"^\d{4,6}[A-Z]?$")
BASELINE_WINDOW = 20  # trading days before event for median baseline


def _load_token() -> str | None:
    if TOKEN_FILE.exists():
        try:
            t = TOKEN_FILE.read_text().strip()
            return t or None
        except Exception:
            return None
    return None


def _is_tw_stock(code: str) -> bool:
    if code in _CASH_MARKERS:
        return False
    return bool(_TW_CODE_RE.fullmatch(code))


def load_shares(etf: str) -> dict[str, dict[str, dict]]:
    """Read raw/cmoney/shares/<etf>.json → {date: {code: {name, shares, weight}}}."""
    p = SHARES_DIR / f"{etf}.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {}
    by_date: dict[str, dict[str, dict]] = {}
    for r in d.get("Data") or []:
        if not r or len(r) < 5:
            continue
        date_, code, name, w, sh = r[0], r[1], r[2], r[3], r[4]
        if not _is_tw_stock(code):
            continue
        try:
            shares = float(sh) if sh not in (None, "") else 0.0
            weight = float(w) if w not in (None, "") else 0.0
        except Exception:
            continue
        by_date.setdefault(date_, {})[code] = {"name": name, "shares": shares, "weight": weight}
    return by_date


def load_aum() -> dict[str, float]:
    """ETF code → 資產規模（億）."""
    out: dict[str, float] = {}
    for f in META_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            for r in d.get("Data") or []:
                if len(r) >= 8:
                    code, aum = r[1], r[7]
                    try:
                        out[code] = float(aum)
                    except Exception:
                        pass
        except Exception:
            pass
    return out


def build_events(
    shares_by_etf: dict[str, dict[str, dict[str, dict]]],
    min_pct: float,
    min_shares: float,
) -> list[dict]:
    """
    Per ETF：對每檔股票按時序排比 prev → cur 兩個揭露日，若 Δshares > 0 且
    (delta_pct >= min_pct OR is_new) 且 abs delta >= min_shares → 一筆 event。
    第一個揭露日不算（沒有 prev 可比）。
    """
    events: list[dict] = []
    for etf, by_date in shares_by_etf.items():
        sorted_dates = sorted(by_date.keys())
        if len(sorted_dates) < 2:
            continue
        # all codes ever held
        all_codes: set[str] = set()
        for d_ in by_date.values():
            all_codes |= set(d_)
        for code in all_codes:
            prev_shares = None
            for date_ in sorted_dates:
                cur = by_date[date_].get(code)
                cur_shares = cur["shares"] if cur else 0.0
                if prev_shares is not None:
                    delta = cur_shares - prev_shares
                    if delta >= min_shares:
                        is_new = prev_shares == 0
                        delta_pct = (delta / prev_shares * 100.0) if prev_shares > 0 else float("inf")
                        if is_new or delta_pct >= min_pct:
                            events.append({
                                "etf": etf,
                                "date": date_,
                                "code": code,
                                "name": cur["name"] if cur else "",
                                "delta_shares": delta,
                                "prev_shares": prev_shares,
                                "cur_shares": cur_shares,
                                "delta_pct": delta_pct if delta_pct != float("inf") else None,
                                "is_new": is_new,
                                "weight": cur["weight"] if cur else 0.0,
                            })
                prev_shares = cur_shares
    return events


def _vol_cache_path(code: str) -> Path:
    return VOL_CACHE / f"{code}.json"


def load_volume_cache(code: str) -> dict[str, int]:
    """{YYYYMMDD: volume_shares}."""
    p = _vol_cache_path(code)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_volume_cache(code: str, vols: dict[str, int]) -> None:
    VOL_CACHE.mkdir(parents=True, exist_ok=True)
    _vol_cache_path(code).write_text(json.dumps(vols, separators=(",", ":")))


def fetch_volumes_finmind(code: str, start: str, end: str, token: str | None) -> dict[str, int]:
    """
    Fetch TaiwanStockPrice for [start, end] (YYYYMMDD), return {YYYYMMDD: Trading_Volume}.
    """
    qs = urllib.parse.urlencode({
        "dataset": "TaiwanStockPrice",
        "data_id": code,
        "start_date": f"{start[:4]}-{start[4:6]}-{start[6:]}",
        "end_date": f"{end[:4]}-{end[4:6]}-{end[6:]}",
    })
    url = f"{FINMIND_URL}?{qs}"
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"  ! {code} HTTP {e.code}\n")
        return {}
    except Exception as e:
        sys.stderr.write(f"  ! {code} {e}\n")
        return {}
    try:
        d = json.loads(raw)
    except Exception:
        return {}
    out: dict[str, int] = {}
    for r in d.get("data") or []:
        date_iso = r.get("date")
        vol = r.get("Trading_Volume")
        if not date_iso or vol is None:
            continue
        ymd = date_iso.replace("-", "")
        try:
            out[ymd] = int(vol)
        except Exception:
            pass
    return out


def ensure_volumes(codes: set[str], earliest: str, latest: str, sleep: float = 0.2) -> dict[str, dict[str, int]]:
    """For each code, ensure cache covers [earliest, latest]. Refresh if missing tail."""
    token = _load_token()
    out: dict[str, dict[str, int]] = {}
    n_fetch = 0
    n_cache = 0
    for code in sorted(codes):
        cached = load_volume_cache(code)
        cached_max = max(cached) if cached else "00000000"
        cached_min = min(cached) if cached else "99999999"
        need_fetch = (not cached) or cached_min > earliest or cached_max < latest
        if need_fetch:
            sys.stderr.write(f"  → fetch {code} {earliest}..{latest}\n")
            new = fetch_volumes_finmind(code, earliest, latest, token)
            if new:
                cached.update(new)
                save_volume_cache(code, cached)
            n_fetch += 1
            time.sleep(sleep)
        else:
            n_cache += 1
        out[code] = cached
    sys.stderr.write(f"  volumes: {n_fetch} fetched, {n_cache} from cache\n")
    return out


def abnormal_ratio(vols: dict[str, int], event_date: str, lookahead_days: int = 0) -> float | None:
    """
    For volume time series vols (YYYYMMDD: vol)，找 event_date 在排序中位置，
    取 [pos-BASELINE_WINDOW : pos] 當 baseline，回 vol[pos+lookahead] / median(baseline)。
    回 None if insufficient data.
    """
    if not vols:
        return None
    sorted_dates = sorted(vols.keys())
    # find the trading day at or after event_date
    pos = None
    for i, d in enumerate(sorted_dates):
        if d >= event_date:
            pos = i
            break
    if pos is None:
        return None
    target = pos + lookahead_days
    if target >= len(sorted_dates):
        return None
    if pos < BASELINE_WINDOW:
        return None
    baseline = [vols[sorted_dates[j]] for j in range(pos - BASELINE_WINDOW, pos)]
    baseline = [v for v in baseline if v > 0]
    if len(baseline) < BASELINE_WINDOW // 2:
        return None
    base_med = statistics.median(baseline)
    if base_med <= 0:
        return None
    target_vol = vols[sorted_dates[target]]
    return target_vol / base_med


def analyze(events: list[dict], vols: dict[str, dict[str, int]], aum: dict[str, float]) -> dict:
    """Pool / per-ETF / new-vs-add abnormal vol summary at T, T+1."""
    enriched = []
    for e in events:
        v = vols.get(e["code"], {})
        r0 = abnormal_ratio(v, e["date"], 0)
        r1 = abnormal_ratio(v, e["date"], 1)
        r2 = abnormal_ratio(v, e["date"], 2)
        if r0 is None and r1 is None:
            continue
        e2 = dict(e)
        e2["r_t0"] = r0
        e2["r_t1"] = r1
        e2["r_t2"] = r2
        enriched.append(e2)

    def _stats(vals: list[float]) -> dict | None:
        vals = [v for v in vals if v is not None and v > 0]
        if len(vals) < 5:
            return None
        return {
            "n": len(vals),
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "p25": round(statistics.quantiles(vals, n=4)[0], 2),
            "p75": round(statistics.quantiles(vals, n=4)[2], 2),
        }

    pooled = {
        "T": _stats([e["r_t0"] for e in enriched]),
        "T+1": _stats([e["r_t1"] for e in enriched]),
        "T+2": _stats([e["r_t2"] for e in enriched]),
    }

    # per ETF
    by_etf: dict[str, dict] = {}
    for etf in sorted({e["etf"] for e in enriched}):
        es = [e for e in enriched if e["etf"] == etf]
        by_etf[etf] = {
            "aum_yi": aum.get(etf),
            "n_events": len(es),
            "T": _stats([e["r_t0"] for e in es]),
            "T+1": _stats([e["r_t1"] for e in es]),
        }

    # new-position vs add
    new_events = [e for e in enriched if e["is_new"]]
    add_events = [e for e in enriched if not e["is_new"]]
    by_kind = {
        "new_position": {
            "T": _stats([e["r_t0"] for e in new_events]),
            "T+1": _stats([e["r_t1"] for e in new_events]),
        },
        "add_existing": {
            "T": _stats([e["r_t0"] for e in add_events]),
            "T+1": _stats([e["r_t1"] for e in add_events]),
        },
    }

    return {
        "n_events_total": len(events),
        "n_events_with_volume": len(enriched),
        "pooled": pooled,
        "by_etf": by_etf,
        "by_kind": by_kind,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--etfs", default="", help="逗號分隔的 ETF code（預設 raw/cmoney/shares/ 所有）")
    p.add_argument("--min-pct", type=float, default=5.0, help="顯著加碼 % 門檻（預設 5%）")
    p.add_argument("--min-shares", type=float, default=100_000, help="絕對股數下限（預設 10 萬股）")
    p.add_argument("--no-fetch", action="store_true", help="不抓 FinMind，用現有 cache")
    p.add_argument("--sleep", type=float, default=0.2, help="FinMind 請求間隔（秒）")
    p.add_argument("--json", action="store_true", help="JSON 輸出")
    args = p.parse_args()

    # 1) load shares
    if args.etfs:
        etfs = [e.strip().upper() for e in args.etfs.split(",") if e.strip()]
    else:
        etfs = sorted(f.stem for f in SHARES_DIR.glob("*.json"))
    shares_by_etf = {etf: load_shares(etf) for etf in etfs}
    shares_by_etf = {k: v for k, v in shares_by_etf.items() if v}

    # 2) build events
    events = build_events(shares_by_etf, args.min_pct, args.min_shares)
    sys.stderr.write(f"events: {len(events)} from {len(shares_by_etf)} ETFs\n")

    # 3) date range to fetch
    if not events:
        print(json.dumps({"status": "no_events"}))
        return 1
    dates = sorted({e["date"] for e in events})
    earliest_event = dates[0]
    latest_event = dates[-1]
    # need 30 trading days before earliest event for baseline
    earliest_dt = datetime.strptime(earliest_event, "%Y%m%d") - timedelta(days=45)
    earliest = earliest_dt.strftime("%Y%m%d")
    latest_dt = datetime.strptime(latest_event, "%Y%m%d") + timedelta(days=10)
    latest = latest_dt.strftime("%Y%m%d")

    # 4) fetch volumes
    codes = {e["code"] for e in events}
    if args.no_fetch:
        vols = {c: load_volume_cache(c) for c in codes}
    else:
        vols = ensure_volumes(codes, earliest, latest, args.sleep)

    # 5) AUM for sort
    aum = load_aum()

    # 6) analyze
    summary = analyze(events, vols, aum)

    if args.json:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    # human format
    print(f"\n# H1 Front-running Effect — 主動 ETF 揭露日異常成交量")
    print(f"\nevents: {summary['n_events_total']} total, {summary['n_events_with_volume']} with valid volume data")
    print(f"事件條件: Δshares ≥ {args.min_shares:,.0f} 且 (Δ% ≥ {args.min_pct}% 或 新建倉)")
    print(f"baseline: median(vol[T-{BASELINE_WINDOW} : T-1]); H1 預期 ratio > 1.0\n")

    print("## Pooled (全部 events 平均 abnormal volume ratio)\n")
    print(f"{'window':<6} {'n':>5} {'mean':>7} {'median':>7} {'p25':>6} {'p75':>6}")
    for window, s in summary["pooled"].items():
        if s:
            print(f"{window:<6} {s['n']:>5} {s['mean']:>7} {s['median']:>7} {s['p25']:>6} {s['p75']:>6}")
    print()

    print("## By kind\n")
    print(f"{'kind':<14} {'window':<6} {'n':>5} {'mean':>7} {'median':>7}")
    for kind, w_stats in summary["by_kind"].items():
        for window, s in w_stats.items():
            if s:
                print(f"{kind:<14} {window:<6} {s['n']:>5} {s['mean']:>7} {s['median']:>7}")
    print()

    print("## By ETF (排序：AUM 大 → 小)\n")
    sorted_etfs = sorted(summary["by_etf"].items(), key=lambda kv: -(kv[1]["aum_yi"] or 0))
    print(f"{'ETF':<8} {'AUM(億)':>10} {'n_evt':>6} {'T_mean':>8} {'T_med':>7} {'T+1_mean':>9} {'T+1_med':>9}")
    for etf, d in sorted_etfs:
        aum_str = f"{d['aum_yi']:.1f}" if d['aum_yi'] is not None else "-"
        t = d['T'] or {}
        t1 = d['T+1'] or {}
        print(f"{etf:<8} {aum_str:>10} {d['n_events']:>6} "
              f"{t.get('mean','-'):>8} {t.get('median','-'):>7} "
              f"{t1.get('mean','-'):>9} {t1.get('median','-'):>9}")
    print()
    print(f"saved → {OUT_PATH.relative_to(REPO_ROOT)}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
