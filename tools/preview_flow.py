#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_flow — 跨 ETF 聚合經理人昨日/最新一日的實際資金流。

研究動機：單檔 ETF 的 daily_shares 看得出「這家經理人今天買什麼」，但散戶/觀察者
真正關心的是「昨天全部主動 ETF 經理人共識買/賣哪幾檔、砸了多少台幣」。把所有 ETF
的 Δshares × close 加總，再按股票歸併（多少家買、多少家賣、總金額），就是最直覺的
cross-sectional 資金流。

輸出：site/preview/flow.json
    {
      "as_of": YYYYMMDD,             # 全市場最新一個揭露日（各 ETF 取 max）
      "etfs_covered": [...],         # 有參與（latest date == as_of）的 ETF 代號
      "etfs_lagging": [...],         # latest date != as_of 的 ETF（揭露延遲）
      "inflow":  [{code, name, ntd, shares, etfs_buy, etfs_sell, etfs}, ...],
      "outflow": [...],
      "by_etf":  [{etf, ntd_in, ntd_out, net}, ...],
      "totals":  {ntd_in, ntd_out, net, n_stocks_touched}
    }

使用 raw/cmoney/shares/<ETF>.json 取 Δshares（latest vs prev 揭露日），用
site/preview/<etf>-prices.json 取 latest_date 的 close 當成交價。門檻跟
preview_build 一致（SHARES_PCT_THRESHOLD=3%、WEIGHT_FLOOR_PP=0.3pp），濾掉
微調雜訊。

為什麼不直接吃 site/preview/<etf>.json 的 top_adds/top_reductions？那兩個
已經 slice 到 [:10]。跨 ETF 聚合要看完整長尾（尤其 00981A 有時 15+ 加碼），所以
重新從 raw 算一次。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_CASH_MARKERS = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"}
SHARES_PCT_THRESHOLD = 3.0
WEIGHT_FLOOR_PP = 0.3


def _load_shares(etf: str) -> dict[str, dict[str, dict]] | None:
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
    """讀 <etf>-prices.json，回 {code: close_at_date}（≤ date 的最後一筆）."""
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


def _etf_flow(etf: str) -> dict | None:
    """單 ETF 算 latest vs prev 日的每檔 Δshares × close（全量，不切 top N）."""
    by_date = _load_shares(etf)
    if not by_date or len(by_date) < 2:
        return None
    dates_desc = sorted(by_date.keys(), reverse=True)
    latest_date, prev_date = dates_desc[0], dates_desc[1]
    latest, prev = by_date[latest_date], by_date[prev_date]

    closes = _close_on(Path(f"site/preview/{etf.lower()}-prices.json"), latest_date)

    moves: list[dict] = []
    # 有在 latest 的持股（包含加碼、減碼、新建倉）
    for ccode, cur in latest.items():
        pr = prev.get(ccode)
        cur_w = cur["weight"]
        cur_sh = cur["shares"]
        name = cur["name"]
        if pr is None:
            # 新建倉（算全量 shares × close）
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
    # 出清（latest 沒有但 prev 有）
    for ccode, pr in prev.items():
        if ccode in latest:
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
        "latest_date": latest_date,
        "prev_date": prev_date,
        "moves": moves,
    }


def build(out_path: Path) -> dict:
    shares_dir = Path("raw/cmoney/shares")
    etfs = sorted(
        p.stem for p in shares_dir.glob("*.json")
        if p.stem.isalnum() and len(p.stem) == 6 and p.stem[-1].isalpha()
    )

    per_etf = []
    for etf in etfs:
        ef = _etf_flow(etf)
        if ef:
            per_etf.append(ef)

    if not per_etf:
        raise SystemExit("no ETF flow data; did raw/cmoney/shares/ and site/preview/*-prices.json get built?")

    # 以全市場最新日期作 as_of；lagging ETF 還留在 prev，不計入聚合
    as_of = max(e["latest_date"] for e in per_etf)
    covered = [e for e in per_etf if e["latest_date"] == as_of]
    lagging = [e["etf"] for e in per_etf if e["latest_date"] != as_of]

    # 按股票聚合
    agg: dict[str, dict] = {}
    for ef in covered:
        etf = ef["etf"]
        for m in ef["moves"]:
            slot = agg.setdefault(m["code"], {
                "code": m["code"], "name": m["name"],
                "ntd": 0.0, "delta_shares": 0.0,
                "etfs_buy": 0, "etfs_sell": 0, "etfs": [],
            })
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

    # 精簡
    for slot in agg.values():
        slot["ntd"] = round(slot["ntd"])
        slot["delta_shares"] = round(slot["delta_shares"])
        for e in slot["etfs"]:
            e["ntd"] = round(e["ntd"])
            e["delta_shares"] = round(e["delta_shares"])
        slot["etfs"].sort(key=lambda x: -abs(x["ntd"]))

    inflow = sorted((s for s in agg.values() if s["ntd"] > 0), key=lambda s: -s["ntd"])
    outflow = sorted((s for s in agg.values() if s["ntd"] < 0), key=lambda s: s["ntd"])

    # 每 ETF 小計（只含 covered）
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
        })
    by_etf.sort(key=lambda e: -e["net"])

    total_in = sum(s["ntd"] for s in inflow)
    total_out = sum(s["ntd"] for s in outflow)

    out = {
        "as_of": as_of,
        "prev_date": covered[0]["prev_date"] if covered else None,
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
    ap.add_argument("--out", default="site/preview/flow.json")
    args = ap.parse_args()
    r = build(Path(args.out))
    print(f"as_of={r['as_of']} covered={len(r['etfs_covered'])} lagging={len(r['etfs_lagging'])} "
          f"stocks={r['totals']['n_stocks_touched']} "
          f"in=+{r['totals']['ntd_in']/1e8:.1f}億 out={r['totals']['ntd_out']/1e8:.1f}億")
    return 0


if __name__ == "__main__":
    sys.exit(main())
