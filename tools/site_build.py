#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
site_build — 從 raw/cmoney/ 的每日 JSON dump 產出 site/data/*.json 給 Pages 前端用。
（raw/cmoney/ 的內容由外部 CI workflow 每日推入本 repo；本檔只負責消費）

目前產出：

    site/data/flows.json        21 檔主動 ETF 每日資金流入/流出合計（逐股 ×日期）
    site/data/premium.json      21 檔折溢價時序（來自 raw/cmoney/premium/<etf>.json）
    site/data/winners.json      21 檔 P&L 排行（聚合 site/preview/<etf>.json 的 pnl 欄）
    site/data/new-positions.json 新建倉合集（跨 21 檔 × 7/30 天視窗）
    site/data/exits.json         出清合集（跨 21 檔 × 7/30 天視窗）

Usage:
  ./tools/site_build.py            # 產全部 data/*.json
  ./tools/site_build.py --out DIR  # 指定輸出目錄（預設 site/data/）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_CMONEY = ROOT / "raw" / "cmoney"
RAW_PREMIUM = RAW_CMONEY / "premium"
RAW_SHARES = RAW_CMONEY / "shares"
WIKI_ETFS = ROOT / "wiki" / "etfs"
SITE_PREVIEW = ROOT / "site" / "preview"
DEFAULT_OUT = ROOT / "site" / "data"

# 現金 / 保證金 / 應收付 — 從股票級聚合排除
NON_STOCK_CODES = {"C_NTD", "M_NTD", "PFUR_NTD", "RDI_NTD"}
# 股票代碼形狀：純數字 4–6 碼（含 TW/US suffix 的海外標的如 "LITE US" 也一併含入）
STOCK_CODE = re.compile(r"^[0-9A-Z]+( [A-Z]{2})?$")


def load_etf_meta() -> dict[str, dict]:
    """讀 wiki/etfs/*.md frontmatter 取 title + issuer tag。"""
    meta: dict[str, dict] = {}
    for md in sorted(WIKI_ETFS.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        fm = m.group(1)
        title = _fm_val(fm, "title") or md.stem.upper()
        tags = _fm_list(fm, "tags")
        issuer = next(
            (t for t in tags if t not in {
                "active-etf", "active-bond-etf", "taiwan-equity", "us-equity",
                "global-equity", "cross-border", "foreign-invested", "local-sitc",
                "d-suffix", "tpex", "flat-fee", "tiered-fee", "monthly-dividend",
                "quarterly-dividend", "annual-dividend", "semi-annual-dividend",
                "investment-grade-bond", "non-investment-grade", "high-yield-bond",
                "us-brand", "japanese", "first-listing", "first-batch",
                "warning-in-name", "disclosure-error", "first-from-issuer",
                "lowest-management-fee", "core-coadjunct-manager", "benchmark-taiwan-weighted",
                "minimalist-naming", "high-dividend", "capital-sitc", "nomura",
                "uni-president", "ctbc", "tsit", "allianz", "fuhwa", "yuanta",
                "cathay", "megabank-itim", "first-financial", "jpmorgan-taiwan",
                "fubon", "alliancebernstein", "blackrock", "taishin",
                # actually we DO want some of these — see below
            }),
            None,
        )
        # 上面排除太多；改用白名單挑 issuer tag
        issuer_whitelist = {
            "uni-president", "capital-sitc", "nomura", "allianz", "fuhwa",
            "ctbc", "tsit", "yuanta", "cathay", "megabank-itim",
            "first-financial", "first-financial-sitc", "jpmorgan-taiwan",
            "fubon", "alliancebernstein", "blackrock", "taishin",
        }
        issuer = next((t for t in tags if t in issuer_whitelist), "unknown")
        code = md.stem.upper()
        # 保留短名（title 裡「— ...」後段）
        short = title.split("—", 1)[-1].strip() if "—" in title else title
        meta[code] = {"code": code, "name": short, "issuer": issuer}
    return meta


def _fm_val(fm: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip() if m else None


def _fm_list(fm: str, key: str) -> list[str]:
    m = re.search(rf"^{re.escape(key)}:\s*\[(.*?)\]", fm, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    inner = m.group(1)
    return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]


def build_premium(etf_meta: dict[str, dict]) -> dict | None:
    """
    把 raw/cmoney/premium/<ETF>.json 合成 site/data/premium.json。

    來源 schema: {"Title": ["日期","收盤價","淨值","折溢價(%)"], "Data": [[ymd, close, nav, pm], ...]}
    （降冪；本函數改為升冪輸出好讓前端直接畫）
    """
    if not RAW_PREMIUM.exists():
        return None

    etfs_out: list[dict] = []
    for f in sorted(RAW_PREMIUM.glob("*.json")):
        code = f.stem.upper()
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] {f}: {e}", file=sys.stderr)
            continue
        raw_rows = payload.get("Data") or []
        rows: list[list] = []
        for r in raw_rows:
            if len(r) < 4:
                continue
            try:
                ymd = str(r[0])
                close = float(r[1])
                nav = float(r[2])
                pm = float(r[3])
            except (TypeError, ValueError):
                continue
            rows.append([ymd, round(close, 4), round(nav, 4), round(pm, 3)])
        if not rows:
            continue
        rows.sort(key=lambda x: x[0])  # ascending by date

        premiums = [r[3] for r in rows]
        n = len(premiums)
        pos = sum(1 for v in premiums if v > 0)
        neg = sum(1 for v in premiums if v < 0)
        flat = n - pos - neg
        sorted_pm = sorted(premiums)
        median_pm = (
            sorted_pm[n // 2] if n % 2
            else (sorted_pm[n // 2 - 1] + sorted_pm[n // 2]) / 2
        )

        meta = etf_meta.get(code, {"code": code, "name": code, "issuer": "unknown"})
        etfs_out.append({
            "code": code,
            "name": meta["name"],
            "issuer": meta["issuer"],
            "rows": rows,
            "stats": {
                "days": n,
                "avg_premium": round(sum(premiums) / n, 3),
                "median_premium": round(median_pm, 3),
                "max_premium": round(max(premiums), 3),
                "min_premium": round(min(premiums), 3),
                "days_positive": pos,
                "days_negative": neg,
                "days_flat": flat,
                "pct_positive": round(pos * 100 / n, 1),
                "recent_premium": premiums[-1],
                "date_start": rows[0][0],
                "date_end": rows[-1][0],
            },
        })

    if not etfs_out:
        return None
    as_of = max(e["stats"]["date_end"] for e in etfs_out)
    return {
        "as_of": as_of,
        "n_etfs": len(etfs_out),
        "etfs": etfs_out,
    }


def build_winners(etf_meta: dict[str, dict]) -> dict | None:
    """
    聚合 site/preview/<etf>.json 的 pnl 欄做 ETF 級 P&L 排行。

    pnl 欄（preview_build.py::_compute_stock_pnl 產）：
      {
        "has_prices": bool,  # FinMind 有無價格（海外股 = False）
        "pnl": float,        # 絕對 P&L（NTD）
        "cost_basis": float, # 僅買入累計（NTD）
        "mv_now": float,
        ...
      }

    ETF 級聚合：
      - 只加總 has_prices=True 的個股（海外股被 FinMind 無價跳過）
      - coverage_ratio = covered / total
      - pnl_pct = sum(pnl) / sum(cost_basis) ← 覆蓋子集內的報酬率
    """
    if not SITE_PREVIEW.exists():
        return None

    etfs_out: list[dict] = []
    for f in sorted(SITE_PREVIEW.glob("*.json")):
        if f.name.endswith("-prices.json"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] {f}: {e}", file=sys.stderr)
            continue

        etf_field = p.get("etf")
        if isinstance(etf_field, dict):
            code = str(etf_field.get("code", "")).upper()
            name_from_preview = etf_field.get("name")
            issuer_from_preview = etf_field.get("issuer")
        else:
            code = str(etf_field or "").upper()
            name_from_preview = None
            issuer_from_preview = None
        if not code:
            continue

        pnl_map = p.get("pnl") or {}
        total_stocks = len(pnl_map)
        covered = [v for v in pnl_map.values() if v.get("has_prices")]
        n_covered = len(covered)
        total_pnl = sum(v["pnl"] for v in covered)
        total_cost = sum(v["cost_basis"] for v in covered)
        total_mv = sum(v["mv_now"] for v in covered)
        pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost else 0.0
        coverage = round(n_covered / total_stocks * 100, 1) if total_stocks else 0.0

        # 贏/虧 top 3（只從 covered 取）
        sorted_cov = sorted(covered, key=lambda v: v["pnl"], reverse=True)
        def _brief(v, pnl_map_inv_code):
            return {
                "code": pnl_map_inv_code,
                "pnl": int(round(v["pnl"])),
                "pnl_pct": v.get("pnl_pct", 0),
            }
        # 把 code 綁回（pnl_map key 是 stock code）
        inv = {id(v): k for k, v in pnl_map.items()}
        top_winners = [
            _brief(v, inv.get(id(v), ""))
            for v in sorted_cov[:3]
        ]
        top_losers = [
            _brief(v, inv.get(id(v), ""))
            for v in sorted_cov[-3:][::-1] if v["pnl"] < 0
        ]

        meta = etf_meta.get(code, {})
        name = meta.get("name") or name_from_preview or code
        issuer = meta.get("issuer") or issuer_from_preview or "unknown"

        etfs_out.append({
            "code": code,
            "name": name,
            "issuer": issuer,
            "as_of": p.get("as_of"),
            "first_date": p.get("first_date"),
            "n_days": p.get("n_days", 0),
            "total_stocks": total_stocks,
            "covered_stocks": n_covered,
            "coverage_pct": coverage,
            "pnl": int(round(total_pnl)),
            "pnl_pct": pnl_pct,
            "cost_basis": int(round(total_cost)),
            "mv_now": int(round(total_mv)),
            "top_winners": top_winners,
            "top_losers": top_losers,
        })

    if not etfs_out:
        return None

    # Coverage ≥70% → comparable group；< 70% 或 n_days<5 → limited
    comparable = [e for e in etfs_out if e["coverage_pct"] >= 70 and e["n_days"] >= 5]
    limited = [e for e in etfs_out if e not in comparable]
    as_of = max((e["as_of"] for e in etfs_out if e.get("as_of")), default=None)
    return {
        "as_of": as_of,
        "n_etfs": len(etfs_out),
        "n_comparable": len(comparable),
        "n_limited": len(limited),
        "etfs": etfs_out,
    }


def _load_global_prices() -> dict[str, dict[str, float]]:
    """
    合併所有 site/preview/<etf>-prices.json 產出 {code: {date: close}}。
    同一支股票跨 ETF 的價格應一致（FinMind 為單一來源），若有衝突後者覆蓋。
    """
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for f in sorted(SITE_PREVIEW.glob("*-prices.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] {f}: {e}", file=sys.stderr)
            continue
        for code, rows in d.get("prices", {}).items():
            if code in NON_STOCK_CODES or not STOCK_CODE.match(code):
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                try:
                    out[code][str(row["date"])] = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
    return dict(out)


def build_flows(etf_meta: dict[str, dict], top_per_side: int = 20) -> dict | None:
    """
    每日資金流計算：

        net_cash_flow(stock, date) = Σ_ETF [ Δshares(ETF, stock, D) × close(stock, D) ]

    跨 21 檔主動 ETF 加總。正 = 該日集體買入、負 = 集體賣出。
    需要 FinMind 價格，無價的股票（海外）該日 skip。
    """
    if not RAW_SHARES.exists():
        return None

    prices = _load_global_prices()
    if not prices:
        print("[WARN] 沒有 preview prices 可載入，flows skipped", file=sys.stderr)
        return None

    # flows[date][code] = net_cash NTD; shares_delta[date][code] 同
    flows: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    shares_delta: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    stock_names: dict[str, str] = {}
    n_etfs_seen = set()

    for f in sorted(RAW_SHARES.glob("*.json")):
        etf = f.stem.upper()
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] {f}: {e}", file=sys.stderr)
            continue
        n_etfs_seen.add(etf)

        # index by date: date → code → shares
        by_date: dict[str, dict[str, float]] = defaultdict(dict)
        for row in payload.get("Data", []):
            if len(row) < 6:
                continue
            date, code, name, weight, shares, _unit = row[:6]
            if code in NON_STOCK_CODES or not STOCK_CODE.match(code):
                continue
            try:
                s = float(shares)
            except (TypeError, ValueError):
                continue
            by_date[str(date)][str(code)] = s
            if len(str(name)) > len(stock_names.get(code, "")):
                stock_names[code] = str(name)

        dates = sorted(by_date.keys())
        for i in range(1, len(dates)):
            d_prev, d_curr = dates[i - 1], dates[i]
            prev_s, curr_s = by_date[d_prev], by_date[d_curr]
            codes = set(prev_s) | set(curr_s)
            for code in codes:
                delta = curr_s.get(code, 0.0) - prev_s.get(code, 0.0)
                if delta == 0:
                    continue
                close = prices.get(code, {}).get(d_curr)
                if close is None:
                    continue
                flows[d_curr][code] += delta * close
                shares_delta[d_curr][code] += delta

    if not flows:
        return None

    # Build per-day summary
    daily: list[dict] = []
    for date in sorted(flows.keys()):
        day = flows[date]
        items = list(day.items())
        total_in = sum(v for _, v in items if v > 0)
        total_out = sum(v for _, v in items if v < 0)
        n_in = sum(1 for _, v in items if v > 0)
        n_out = sum(1 for _, v in items if v < 0)

        items_sorted = sorted(items, key=lambda x: -x[1])
        top_in = items_sorted[:top_per_side]
        top_out = sorted(items, key=lambda x: x[1])[:top_per_side]

        def _brief(code_flow):
            code, flow = code_flow
            return {
                "code": code,
                "name": stock_names.get(code, code),
                "flow": int(round(flow)),
                "shares_delta": int(round(shares_delta[date][code])),
            }

        daily.append({
            "date": date,
            "net": int(round(total_in + total_out)),
            "total_in": int(round(total_in)),
            "total_out": int(round(total_out)),
            "n_in": n_in,
            "n_out": n_out,
            "top_in": [_brief(x) for x in top_in if x[1] > 0],
            "top_out": [_brief(x) for x in top_out if x[1] < 0],
        })

    all_dates = [d["date"] for d in daily]
    return {
        "as_of": all_dates[-1],
        "first_date": all_dates[0],
        "n_etfs": len(n_etfs_seen),
        "n_stocks_with_price": len(prices),
        "top_per_side": top_per_side,
        "daily": daily,
    }


def _load_shares_events(etf_meta: dict[str, dict]) -> tuple[list[dict], list[dict], str] | None:
    """
    從 raw/cmoney/shares/<ETF>.json 推算每檔 ETF 的歷史 新建倉 / 出清 事件。

    回傳 (new_events, exit_events, latest_date)，每筆 event:
      {"etf": "00981A", "date": "20260417", "code": "2303", "name": "聯電"}

    邏輯：對每檔 ETF 按日期 set diff：
      new   = holdings[D] - holdings[D-1]
      exit  = holdings[D-1] - holdings[D]
    """
    if not RAW_SHARES.exists():
        return None

    all_new: list[dict] = []
    all_exit: list[dict] = []
    latest_overall = ""

    for f in sorted(RAW_SHARES.glob("*.json")):
        etf = f.stem.upper()
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] {f}: {e}", file=sys.stderr)
            continue

        by_date: dict[str, set[str]] = defaultdict(set)
        name_of: dict[str, str] = {}
        for row in payload.get("Data", []):
            if len(row) < 3:
                continue
            date, code, name = str(row[0]), str(row[1]), str(row[2])
            if code in NON_STOCK_CODES:
                continue
            if not STOCK_CODE.match(code):
                continue
            by_date[date].add(code)
            # 取最長的中文名（通常最完整）
            if len(name) > len(name_of.get(code, "")):
                name_of[code] = name

        if not by_date:
            continue

        dates = sorted(by_date.keys())
        if dates[-1] > latest_overall:
            latest_overall = dates[-1]

        for i in range(1, len(dates)):
            prev = by_date[dates[i - 1]]
            curr = by_date[dates[i]]
            for code in curr - prev:
                all_new.append({
                    "etf": etf, "date": dates[i],
                    "code": code, "name": name_of.get(code, code),
                })
            for code in prev - curr:
                all_exit.append({
                    "etf": etf, "date": dates[i],
                    "code": code, "name": name_of.get(code, code),
                })

    if not latest_overall:
        return None
    return all_new, all_exit, latest_overall


def _window_start(latest_ymd: str, days: int) -> str:
    """latest_ymd 往前推 days 天（含 latest 為 window 結尾）的 YYYYMMDD。"""
    from datetime import datetime, timedelta
    dt = datetime.strptime(latest_ymd, "%Y%m%d")
    return (dt - timedelta(days=days)).strftime("%Y%m%d")


def _aggregate_events(
    events: list[dict],
    start_ymd: str,
    end_ymd: str,
) -> list[dict]:
    """把 event list 聚合成 stock-level list（跨 ETF 的跟進順序）。"""
    in_window = [e for e in events if start_ymd <= e["date"] <= end_ymd]
    by_stock: dict[str, dict] = {}
    for e in in_window:
        slot = by_stock.setdefault(e["code"], {
            "code": e["code"],
            "name": e["name"],
            "events": [],
        })
        slot["events"].append({"etf": e["etf"], "date": e["date"]})
        if len(e["name"]) > len(slot["name"]):
            slot["name"] = e["name"]

    rows = []
    for code, d in by_stock.items():
        evs = sorted(d["events"], key=lambda x: (x["date"], x["etf"]))
        dates_only = [x["date"] for x in evs]
        etfs_set = sorted({x["etf"] for x in evs})
        rows.append({
            "code": code,
            "name": d["name"],
            "n_etfs": len(etfs_set),
            "n_events": len(evs),
            "first_date": dates_only[0],
            "last_date": dates_only[-1],
            "etfs": etfs_set,
            "events": evs,
        })
    # 排序：跟進家數 desc → 最近 last_date desc → first_date asc
    rows.sort(key=lambda r: (-r["n_etfs"], -int(r["last_date"]), int(r["first_date"])))
    return rows


def build_positions_flow(
    etf_meta: dict[str, dict],
) -> tuple[dict | None, dict | None]:
    """
    產出 new-positions.json + exits.json，兩者結構對稱。
    """
    loaded = _load_shares_events(etf_meta)
    if loaded is None:
        return None, None
    new_events, exit_events, latest = loaded

    n_etfs = len({e["etf"] for e in new_events + exit_events})
    etfs_list = sorted({e["etf"] for e in new_events + exit_events})
    etfs_meta_list = [
        etf_meta.get(c, {"code": c, "name": c, "issuer": "unknown"})
        for c in etfs_list
    ]

    def _build(events: list[dict]) -> dict:
        windows = {}
        for label, days in [("7d", 7), ("30d", 30)]:
            start = _window_start(latest, days)
            stocks = _aggregate_events(events, start, latest)
            windows[label] = {
                "days": days,
                "start": start,
                "end": latest,
                "n_events": sum(s["n_events"] for s in stocks),
                "n_stocks": len(stocks),
                "stocks": stocks,
            }
        return {
            "as_of": latest,
            "n_etfs": n_etfs,
            "etfs": etfs_meta_list,
            "windows": windows,
        }

    return _build(new_events), _build(exit_events)


def main() -> int:
    p = argparse.ArgumentParser(prog="site_build")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="輸出目錄（預設 site/data/）")
    args = p.parse_args()

    if not RAW_CMONEY.exists():
        print(f"[ERROR] raw/cmoney/ 不存在：{RAW_CMONEY}", file=sys.stderr)
        return 2

    etf_meta = load_etf_meta()
    args.out.mkdir(parents=True, exist_ok=True)

    flows = build_flows(etf_meta)
    if flows is not None:
        fl_file = args.out / "flows.json"
        fl_file.write_text(
            json.dumps(flows, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"✓ wrote {fl_file}")
        last = flows["daily"][-1]
        print(f"  as_of={flows['as_of']}  n_etfs={flows['n_etfs']}  "
              f"days={len(flows['daily'])}  "
              f"latest net={last['net']:+,}  in={last['n_in']} stocks  "
              f"out={last['n_out']} stocks")
    else:
        print(f"[SKIP] 未能產 flows.json（無 shares/ 或無價）", file=sys.stderr)

    premium = build_premium(etf_meta)
    if premium is not None:
        pm_file = args.out / "premium.json"
        pm_file.write_text(
            json.dumps(premium, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"✓ wrote {pm_file}")
        print(f"  as_of={premium['as_of']}  n_etfs={premium['n_etfs']}  "
              f"rows_per_etf≈{len(premium['etfs'][0]['rows'])}")
    else:
        print(f"[SKIP] {RAW_PREMIUM} 不存在或無資料，未產 premium.json")

    winners = build_winners(etf_meta)
    if winners is not None:
        w_file = args.out / "winners.json"
        w_file.write_text(
            json.dumps(winners, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"✓ wrote {w_file}")
        print(f"  as_of={winners['as_of']}  n_etfs={winners['n_etfs']}  "
              f"comparable={winners['n_comparable']}  limited={winners['n_limited']}")
    else:
        print(f"[SKIP] {SITE_PREVIEW} 不存在或無 preview JSON，未產 winners.json")

    new_pos, exits = build_positions_flow(etf_meta)
    if new_pos is not None:
        np_file = args.out / "new-positions.json"
        np_file.write_text(
            json.dumps(new_pos, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"✓ wrote {np_file}")
        print(f"  as_of={new_pos['as_of']}  "
              f"7d={new_pos['windows']['7d']['n_stocks']} stocks / "
              f"{new_pos['windows']['7d']['n_events']} events  "
              f"30d={new_pos['windows']['30d']['n_stocks']} stocks")
    if exits is not None:
        ex_file = args.out / "exits.json"
        ex_file.write_text(
            json.dumps(exits, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"✓ wrote {ex_file}")
        print(f"  as_of={exits['as_of']}  "
              f"7d={exits['windows']['7d']['n_stocks']} stocks / "
              f"{exits['windows']['7d']['n_events']} events  "
              f"30d={exits['windows']['30d']['n_stocks']} stocks")
    if new_pos is None:
        print(f"[SKIP] {RAW_SHARES} 不存在，未產 new-positions.json / exits.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
