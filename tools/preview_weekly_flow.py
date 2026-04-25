#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_weekly_flow — 跨 ETF 聚合「上週」一整週的經理人累積資金流。

跟 preview_flow.py 同樣邏輯（Δshares × close 跨 21 檔聚合），差別在比較的兩個
snapshot 是「上週交易週的前後」，不是「最近兩個揭露日」：
  - 起點 snapshot = ≤ 上週一前一天 的最後揭露日（= 前週五）
  - 終點 snapshot = ≤ 上週五         的最後揭露日

收盤價統一取 end_date（最 reasonable baseline，跟 preview_flow 一致），不分日加權。

預設「上週」由 --end YYYYMMDD（預設今天）回推：找今天往回最近一個週日，週日前
一週的週一到週五就是「上週」。如果今天就是週六/週日，回推結果是這個週的週一到週五；
如果今天是平日，回推結果是上一個週一到週五。

輸出：site/preview/weekly_flow.json （schema 跟 flow.json 對齊，前端可共用 render）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_CASH_MARKERS = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"}
SHARES_PCT_THRESHOLD = 3.0
WEIGHT_FLOOR_PP = 0.3


def _resolve_week(end_arg: str | None) -> tuple[str, str]:
    """回傳目標週的 (週一 YYYYMMDD, 週五 YYYYMMDD)。

    錨點：end_arg（預設今天）。
    - 錨點是週六/週日 → 抓「剛結束的這一週」（含錨點所在週的週一~週五）
    - 錨點是週一~週五 → 抓「上一週」（不含錨點所在週）

    這樣週末跑會自然抓到剛收盤的那週，平日跑會抓到上一個完整週。
    """
    if end_arg:
        anchor = dt.date.fromisoformat(f"{end_arg[:4]}-{end_arg[4:6]}-{end_arg[6:8]}")
    else:
        anchor = dt.date.today()
    wd = anchor.weekday()  # Mon=0 .. Sun=6
    if wd >= 5:  # Sat / Sun
        friday = anchor - dt.timedelta(days=wd - 4)
    else:  # Mon-Fri
        friday = anchor - dt.timedelta(days=wd + 3)
    monday = friday - dt.timedelta(days=4)
    return monday.strftime("%Y%m%d"), friday.strftime("%Y%m%d")


def _load_shares_dates(etf: str) -> dict[str, dict[str, dict]] | None:
    """讀 raw/cmoney/shares/<etf>.json → {date: {code: {name, shares, weight}}}."""
    path = Path(f"raw/cmoney/shares/{etf}.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    by_date: dict[str, dict[str, dict]] = {}
    for r in data.get("Data") or []:
        if not r or len(r) < 5:
            continue
        d, ccode, name, w, sh = r[0], r[1], r[2], r[3], r[4]
        if ccode in _CASH_MARKERS:
            continue
        try:
            shares = float(sh) if sh not in (None, "") else 0.0
            weight = float(w) if w not in (None, "") else 0.0
        except Exception:
            continue
        by_date.setdefault(d, {})[ccode] = {"name": name, "shares": shares, "weight": weight}
    return by_date


def _close_on(prices_path: Path, date: str) -> dict[str, float]:
    """讀 <etf>-prices.json，回 {code: close ≤ date 的最後一筆}。跟 preview_flow 同函式。"""
    if not prices_path.exists():
        return {}
    try:
        data = json.loads(prices_path.read_text())
    except Exception:
        return {}
    out: dict[str, float] = {}
    for code, series in (data.get("prices") or {}).items():
        if not isinstance(series, list):
            continue
        last = None
        for p in series:
            pd = p.get("date")
            if pd and pd <= date:
                c = p.get("close")
                if c is not None:
                    last = float(c)
        if last is not None:
            out[code] = last
    return out


def _pick_snapshot_date(dates: list[str], target_max: str) -> str | None:
    """從 dates（升序）裡挑 ≤ target_max 的最後一個。"""
    candidates = [d for d in dates if d <= target_max]
    return candidates[-1] if candidates else None


def _etf_weekly_flow(etf: str, monday: str, friday: str) -> dict | None:
    """單 ETF 算「終點 snapshot vs 起點 snapshot」的每檔 Δshares × close（全量）。

    起點上限 = monday - 1 天；終點上限 = friday。
    """
    by_date = _load_shares_dates(etf)
    if not by_date:
        return None
    sorted_dates = sorted(by_date.keys())
    monday_dt = dt.date.fromisoformat(f"{monday[:4]}-{monday[4:6]}-{monday[6:8]}")
    start_max = (monday_dt - dt.timedelta(days=1)).strftime("%Y%m%d")
    start_date = _pick_snapshot_date(sorted_dates, start_max)
    end_date = _pick_snapshot_date(sorted_dates, friday)
    if not start_date or not end_date or start_date == end_date:
        return None

    start, end = by_date[start_date], by_date[end_date]
    closes = _close_on(Path(f"site/preview/{etf.lower()}-prices.json"), end_date)

    moves: list[dict] = []
    # 終點存在的持股（加碼/減碼/新建倉）
    for ccode, cur in end.items():
        pr = start.get(ccode)
        cur_w = cur["weight"]
        cur_sh = cur["shares"]
        name = cur["name"]
        if pr is None:
            if cur_w < WEIGHT_FLOOR_PP:
                continue
            close = closes.get(ccode)
            if close is None:
                continue
            moves.append({
                "code": ccode, "name": name,
                "delta_shares": cur_sh,
                "ntd": cur_sh * close,
                "kind": "new",
            })
            continue
        delta = cur_sh - pr["shares"]
        if delta == 0:
            continue
        max_w = max(cur_w, pr["weight"])
        if max_w < WEIGHT_FLOOR_PP:
            continue
        pct = (delta / pr["shares"] * 100.0) if pr["shares"] > 0 else None
        if pct is None or abs(pct) < SHARES_PCT_THRESHOLD:
            continue
        close = closes.get(ccode)
        if close is None:
            continue
        moves.append({
            "code": ccode, "name": name,
            "delta_shares": delta,
            "ntd": delta * close,
            "kind": "add" if delta > 0 else "reduce",
        })
    # 出清
    for ccode, pr in start.items():
        if ccode in end:
            continue
        if pr["weight"] < WEIGHT_FLOOR_PP:
            continue
        close = closes.get(ccode)
        if close is None:
            continue
        moves.append({
            "code": ccode, "name": pr["name"],
            "delta_shares": -pr["shares"],
            "ntd": -pr["shares"] * close,
            "kind": "exit",
        })

    return {
        "etf": etf,
        "start_date": start_date,
        "end_date": end_date,
        "moves": moves,
    }


def build(out_path: Path, monday: str, friday: str) -> dict:
    shares_dir = Path("raw/cmoney/shares")
    etfs = sorted(
        p.stem for p in shares_dir.glob("*.json")
        if p.stem.isalnum() and len(p.stem) == 6 and p.stem[-1].isalpha()
    )

    per_etf = []
    for etf in etfs:
        ef = _etf_weekly_flow(etf, monday, friday)
        if ef:
            per_etf.append(ef)

    if not per_etf:
        raise SystemExit("no ETF weekly flow data; check raw/cmoney/shares/ and prices coverage")

    # 週彙總的 covered/lagging 邏輯比 daily 寬鬆：只要 end_date 落在當週（>= monday）就
    # 算 covered。每 ETF 用自己 end_date 的 close 算 ntd，跨 ETF 加總時各自 baseline 略
    # 有不同（最多差 4 天），但比丟掉整檔好。as_of = covered 的 max end_date。
    as_of = max(e["end_date"] for e in per_etf)
    covered = [e for e in per_etf if e["end_date"] >= monday]
    lagging = [e["etf"] for e in per_etf if e["end_date"] < monday]

    agg: dict[str, dict] = {}
    name_votes: dict[str, dict[str, int]] = {}
    for ef in covered:
        etf = ef["etf"]
        for m in ef["moves"]:
            slot = agg.setdefault(m["code"], {
                "code": m["code"], "name": m["name"],
                "ntd": 0.0, "delta_shares": 0.0,
                "etfs_buy": 0, "etfs_sell": 0, "etfs": [],
            })
            votes = name_votes.setdefault(m["code"], {})
            votes[m["name"]] = votes.get(m["name"], 0) + 1
            slot["ntd"] += m["ntd"]
            slot["delta_shares"] += m["delta_shares"]
            if m["ntd"] > 0:
                slot["etfs_buy"] += 1
            elif m["ntd"] < 0:
                slot["etfs_sell"] += 1
            slot["etfs"].append({
                "etf": etf, "ntd": m["ntd"],
                "delta_shares": m["delta_shares"], "kind": m["kind"],
            })

    # 同一檔股票各 ETF 給的名字可能不一樣（中英不同、全英、有/無「投控」尾），
    # 挑「有中文字元 + 票數最高 + 較短」的當代表名。
    def _has_cjk(s: str) -> bool:
        return any("\u4e00" <= c <= "\u9fff" for c in s)
    for code, votes in name_votes.items():
        cjk = {n: c for n, c in votes.items() if _has_cjk(n)}
        pool = cjk if cjk else votes
        # 排序鍵：票數高優先，其次字串短優先（避免「日月光投資控股」勝「日月光投控」）
        best = sorted(pool.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]
        agg[code]["name"] = best

    for slot in agg.values():
        slot["ntd"] = round(slot["ntd"])
        slot["delta_shares"] = round(slot["delta_shares"])
        for e in slot["etfs"]:
            e["ntd"] = round(e["ntd"])
            e["delta_shares"] = round(e["delta_shares"])
        slot["etfs"].sort(key=lambda x: -abs(x["ntd"]))

    inflow = sorted((s for s in agg.values() if s["ntd"] > 0), key=lambda s: -s["ntd"])
    outflow = sorted((s for s in agg.values() if s["ntd"] < 0), key=lambda s: s["ntd"])

    by_etf = []
    for ef in covered:
        ntd_in = sum(m["ntd"] for m in ef["moves"] if m["ntd"] > 0)
        ntd_out = sum(m["ntd"] for m in ef["moves"] if m["ntd"] < 0)
        by_etf.append({
            "etf": ef["etf"],
            "ntd_in": round(ntd_in),
            "ntd_out": round(ntd_out),
            "net": round(ntd_in + ntd_out),
            "n_moves": len(ef["moves"]),
            "start_date": ef["start_date"],
            "end_date": ef["end_date"],
        })
    by_etf.sort(key=lambda e: -e["net"])

    total_in = sum(s["ntd"] for s in inflow)
    total_out = sum(s["ntd"] for s in outflow)

    out = {
        "as_of": as_of,
        "week_monday": monday,
        "week_friday": friday,
        "start_date": min(e["start_date"] for e in covered) if covered else None,
        "end_date": as_of,
        "etfs_covered": [e["etf"] for e in covered],
        "etfs_lagging": lagging,
        "inflow": inflow,
        "outflow": outflow,
        "by_etf": by_etf,
        "totals": {
            "ntd_in": total_in,
            "ntd_out": total_out,
            "net": total_in + total_out,
            "n_stocks_touched": len(agg),
        },
        "thresholds": {
            "shares_pct": SHARES_PCT_THRESHOLD,
            "weight_floor_pp": WEIGHT_FLOOR_PP,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else "")
    ap.add_argument("--end", help="錨點日期 YYYYMMDD（預設今天，回推上週一~上週五）")
    ap.add_argument("--out", default="site/preview/weekly_flow.json")
    args = ap.parse_args()
    monday, friday = _resolve_week(args.end)
    r = build(Path(args.out), monday, friday)
    print(f"week={monday}~{friday} as_of={r['as_of']} covered={len(r['etfs_covered'])} "
          f"lagging={len(r['etfs_lagging'])} stocks={r['totals']['n_stocks_touched']} "
          f"in=+{r['totals']['ntd_in']/1e8:.1f}億 out={r['totals']['ntd_out']/1e8:.1f}億")
    return 0


if __name__ == "__main__":
    sys.exit(main())
