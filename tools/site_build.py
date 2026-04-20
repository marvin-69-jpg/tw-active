#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
site_build — 從 raw/cmoney/ 的每日 JSON dump 產出 site/data/*.json 給 Pages 前端用。
（raw/cmoney/ 的內容由外部 CI workflow 每日推入本 repo；本檔只負責消費）

目前產出：

    site/data/consensus.json    共識股排行
    site/data/premium.json      21 檔折溢價時序（來自 raw/cmoney/premium/<etf>.json）
    site/data/winners.json      21 檔 P&L 排行（聚合 site/preview/<etf>.json 的 pnl 欄）
    site/data/new-positions.json 新建倉合集（跨 21 檔 × 7/30 天視窗）
    site/data/exits.json         出清合集（跨 21 檔 × 7/30 天視窗）

Schema:
{
  "as_of": "2026-04-17",
  "n_etfs": 21,
  "etfs": [{"code":"00981A","name":"主動統一台股增長","issuer":"uni-president"}],
  "kpi": {
    "n_etfs": 21,
    "all_in_count": <被全部 ETF 持有的股票數>,
    "majority_count": <被 >=50% ETF 持有的股票數>,
    "solo_count": <只被 1 檔持有>,
    "distinct_stocks": <全體去重標的數>,
    "top10_avg_weight_share": <前 10 共識股的平均權重加總>
  },
  "consensus": [
    {
      "code": "2330", "name": "台積電",
      "held_by": 21,
      "avg_weight": 8.54, "max_weight": 9.6, "min_weight": 6.1,
      "total_weight": 178.5,
      "etfs": [{"etf":"00981A","weight":9.57}, ...]   # desc by weight
    }
  ]
}

Usage:
  ./tools/site_build.py            # build site/data/consensus.json
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

# 現金 / 保證金 / 應收付 — 從 consensus 排除
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


def latest_holdings_per_etf() -> dict[str, tuple[str, list[tuple[str, str, float]]]]:
    """
    掃 raw/cmoney/<ETF>/batch_*.json，每檔取最新可得日期的持股明細。

    回傳 {etf_code: (data_date, [(code, name, weight), ...])}
    """
    out: dict[str, tuple[str, list[tuple[str, str, float]]]] = {}
    for etf_dir in sorted(RAW_CMONEY.iterdir()):
        if not etf_dir.is_dir():
            continue
        etf = etf_dir.name.upper()
        # 蒐集所有 (data_date, row) 再挑 max date
        rows_by_date: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for f in etf_dir.glob("batch_*.json"):
            if f.name.endswith(".meta.json"):
                continue
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[WARN] {f}: {e}", file=sys.stderr)
                continue
            for row in payload.get("Data", []):
                if len(row) < 4:
                    continue
                date, name, weight, code = row[0], row[1], row[2], row[3]
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    continue
                rows_by_date[str(date)].append((str(code), str(name), w))
        if not rows_by_date:
            continue
        latest = max(rows_by_date.keys())
        # 同日若有多個 batch 同股重複，取最後出現
        dedup: dict[str, tuple[str, str, float]] = {}
        for code, name, w in rows_by_date[latest]:
            dedup[code] = (code, name, w)
        out[etf] = (latest, sorted(dedup.values(), key=lambda r: -r[2]))
    return out


def build_consensus(
    holdings: dict[str, tuple[str, list[tuple[str, str, float]]]],
    etf_meta: dict[str, dict],
    top_n: int = 150,
) -> dict:
    n_etfs = len(holdings)
    # { code: {"name": ..., "etfs": [(etf, weight), ...]} }
    bucket: dict[str, dict] = {}
    for etf, (_, rows) in holdings.items():
        for code, name, w in rows:
            if code in NON_STOCK_CODES:
                continue
            if not STOCK_CODE.match(code):
                continue
            slot = bucket.setdefault(code, {"name": name, "etfs": []})
            slot["etfs"].append((etf, w))
            # 中文名可能跨投信略異：保留最長的（通常最完整）
            if len(name) > len(slot["name"]):
                slot["name"] = name

    consensus_rows = []
    for code, d in bucket.items():
        weights = [w for _, w in d["etfs"]]
        consensus_rows.append({
            "code": code,
            "name": d["name"],
            "held_by": len(weights),
            "avg_weight": round(sum(weights) / len(weights), 3),
            "max_weight": round(max(weights), 3),
            "min_weight": round(min(weights), 3),
            "total_weight": round(sum(weights), 3),
            "etfs": [
                {"etf": e, "weight": round(w, 3)}
                for e, w in sorted(d["etfs"], key=lambda x: -x[1])
            ],
        })
    # 排序：被持有檔數 desc，同 tie 用 total_weight desc
    consensus_rows.sort(key=lambda r: (-r["held_by"], -r["total_weight"]))
    trimmed = consensus_rows[:top_n]

    as_of = max(d for (d, _) in holdings.values())
    etfs_list = [
        etf_meta.get(e, {"code": e, "name": e, "issuer": "unknown"})
        for e in sorted(holdings.keys())
    ]

    all_in = sum(1 for r in consensus_rows if r["held_by"] == n_etfs)
    majority = sum(1 for r in consensus_rows if r["held_by"] >= (n_etfs + 1) // 2)
    solo = sum(1 for r in consensus_rows if r["held_by"] == 1)
    top10_avg_share = round(sum(r["avg_weight"] for r in consensus_rows[:10]), 2)

    return {
        "as_of": as_of,
        "n_etfs": n_etfs,
        "etfs": etfs_list,
        "kpi": {
            "n_etfs": n_etfs,
            "all_in_count": all_in,
            "majority_count": majority,
            "solo_count": solo,
            "distinct_stocks": len(consensus_rows),
            "top10_avg_weight_share": top10_avg_share,
        },
        "consensus": trimmed,
    }


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
    p.add_argument("--top", type=int, default=150,
                   help="consensus 前幾名（預設 150）")
    args = p.parse_args()

    if not RAW_CMONEY.exists():
        print(f"[ERROR] raw/cmoney/ 不存在：{RAW_CMONEY}", file=sys.stderr)
        return 2

    etf_meta = load_etf_meta()
    holdings = latest_holdings_per_etf()
    if not holdings:
        print("[ERROR] raw/cmoney 沒有可解析的 batch_*.json", file=sys.stderr)
        return 3

    data = build_consensus(holdings, etf_meta, top_n=args.top)

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / "consensus.json"
    out_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    kpi = data["kpi"]
    print(f"✓ wrote {out_file}")
    print(f"  as_of={data['as_of']}  n_etfs={kpi['n_etfs']}  "
          f"all_in={kpi['all_in_count']}  majority={kpi['majority_count']}  "
          f"solo={kpi['solo_count']}  distinct={kpi['distinct_stocks']}")

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
