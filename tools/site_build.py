#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
site_build — 從 raw/cmoney/ 的每日 JSON dump 產出 site/data/*.json 給 Pages 前端用。
（raw/cmoney/ 的內容由外部 CI workflow 每日推入本 repo；本檔只負責消費）

目前只產 Q2 consensus 資料（共識股排行）：

    site/data/consensus.json

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
WIKI_ETFS = ROOT / "wiki" / "etfs"
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
