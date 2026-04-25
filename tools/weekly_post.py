#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
weekly_post.py — 從 weekly_flow.json 產生上週主動 ETF 經理人動向 Threads 文字

跟 morning_post.py 同邏輯但時間粒度是「上週一~上週五」，閾值拉高（週累積數值
是日的 ~7x），文案用語從「昨日」改成「上週」。

Usage:
  uv run tools/weekly_post.py            # 輸出到 stdout
  uv run tools/weekly_post.py --preview  # 附字數資訊
"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WEEKLY_FLOW_JSON = REPO_ROOT / "site" / "preview" / "weekly_flow.json"
TOTAL_ETFS = 21

# 顯示門檻（週累積版，跟 site/observe/weekly-flow.html 對齊）
CONSENSUS_BUY_MIN_FAMILIES = 6   # 共識買進 ≥6 家
CONSENSUS_SELL_MIN_FAMILIES = 3  # 共識賣 ≥3 家
SINGLE_BET_MIN_NTD = 1_000_000_000  # 集中加碼最低門檻（10億）
SINGLE_BET_MAX_SHOW = 6          # 最多顯示幾檔
DOMINANT_ETF_PCT = 0.5           # 單一 ETF 占總流入 >50% → 提示 basket buy


def fmt_ntd(ntd: int) -> str:
    """Format NTD to +X億 / -X億 / +X萬"""
    sign = "+" if ntd >= 0 else "-"
    abs_v = abs(ntd)
    if abs_v >= 100_000_000:
        val = abs_v / 100_000_000
        return f"{sign}{val:.0f}億" if val == int(val) else f"{sign}{val:.1f}億"
    else:
        return f"{sign}{abs_v / 10_000:.0f}萬"


def fmt_date(d: str) -> str:
    """20260422 → 4/22"""
    dt = datetime.strptime(d, "%Y%m%d")
    return f"{dt.month}/{dt.day}"


def generate_text(flow: dict) -> str:
    week_monday = flow["week_monday"]
    week_friday = flow["week_friday"]
    covered = len(flow["etfs_covered"])
    inflow: list[dict] = flow["inflow"]
    outflow: list[dict] = flow["outflow"]
    totals: dict = flow["totals"]
    by_etf: list[dict] = flow["by_etf"]

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────
    lines.append(
        f"上週主動 ETF · {fmt_date(week_monday)}~{fmt_date(week_friday)} 經理人動向"
        f"（{covered}/{TOTAL_ETFS} 家已揭露）"
    )
    lines.append("")

    def etf_codes(stock: dict, kind: str) -> str:
        codes = [e["etf"] for e in stock.get("etfs", []) if e.get("kind") in ("add", "new")] \
            if kind == "buy" else \
            [e["etf"] for e in stock.get("etfs", []) if e.get("kind") in ("reduce", "exit")]
        return "、".join(codes) if codes else ""

    # ── 共識買進 ─────────────────────────────────────────────
    consensus = sorted(
        [s for s in inflow if s["etfs_buy"] >= CONSENSUS_BUY_MIN_FAMILIES],
        key=lambda x: x["ntd"],
        reverse=True,
    )
    consensus_codes = {s["code"] for s in consensus}
    if consensus:
        lines.append(f"{CONSENSUS_BUY_MIN_FAMILIES} 家以上共識買進：")
        for s in consensus:
            codes = etf_codes(s, "buy")
            codes_str = f"（{codes}）" if codes else f"（{s['etfs_buy']} 家）"
            lines.append(f"・{s['name']} {s['code']} {fmt_ntd(s['ntd'])} {codes_str}")
        lines.append("")

    # ── 集中加碼（< 共識門檻、金額達門檻）───────────────────
    single_bets = sorted(
        [
            s for s in inflow
            if s["code"] not in consensus_codes
            and s["ntd"] >= SINGLE_BET_MIN_NTD
        ],
        key=lambda x: x["ntd"],
        reverse=True,
    )[:SINGLE_BET_MAX_SHOW]

    if single_bets:
        lines.append("集中加碼：")
        for s in single_bets:
            codes = etf_codes(s, "buy")
            codes_str = f"（{codes}）" if codes else f"（{s['etfs_buy']} 家）"
            lines.append(f"・{s['name']} {s['code']} {fmt_ntd(s['ntd'])} {codes_str}")
        lines.append("")

    # ── 共識賣 ───────────────────────────────────────────────
    consensus_sell = sorted(
        [s for s in outflow if s["etfs_sell"] >= CONSENSUS_SELL_MIN_FAMILIES],
        key=lambda x: x["ntd"],
    )
    if consensus_sell:
        lines.append("共識賣：")
        for s in consensus_sell:
            codes = etf_codes(s, "sell")
            codes_str = f"（{codes}）" if codes else f"（{s['etfs_sell']} 家）"
            lines.append(f"・{s['name']} {s['code']} {fmt_ntd(s['ntd'])} {codes_str}")
    else:
        lines.append(
            f"共識賣：沒有，沒有任何一檔被 {CONSENSUS_SELL_MIN_FAMILIES} 家以上同時減碼。"
        )
    lines.append("")

    # ── 總結 + basket buy 提示 ───────────────────────────────
    net = totals["net"]
    ntd_in = totals["ntd_in"]

    by_etf_sorted = sorted(by_etf, key=lambda e: e["ntd_in"], reverse=True)
    dominant = by_etf_sorted[0] if by_etf_sorted else None
    dominant_pct = (
        dominant["ntd_in"] / ntd_in
        if dominant and ntd_in > 0
        else 0.0
    )

    net_str = fmt_ntd(net)
    if dominant and dominant_pct > DOMINANT_ETF_PCT and dominant["ntd_in"] > 0:
        pct_int = round(dominant_pct * 100)
        etf_code = dominant["etf"]
        lines.append(
            f"主動 ETF 上週淨流入 {net_str}，但 {pct_int}% 來自 {etf_code} 一家"
            f"因申購在做 basket buy，要把這部分扣掉才看得到真動作。"
        )
    elif net >= 0:
        lines.append(
            f"主動 ETF 上週淨流入 {net_str}（{covered}/{TOTAL_ETFS} 家已揭露）。"
        )
    else:
        lines.append(
            f"主動 ETF 上週淨流出 {fmt_ntd(abs(net))}（{covered}/{TOTAL_ETFS} 家已揭露）。"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    if not WEEKLY_FLOW_JSON.exists():
        sys.exit(f"✗ {WEEKLY_FLOW_JSON} not found（先跑 tools/preview_weekly_flow.py）")

    flow = json.loads(WEEKLY_FLOW_JSON.read_text())
    text = generate_text(flow)
    print(text)

    if "--preview" in sys.argv:
        print(f"\n── {len(text)} chars ──")
        if len(text) > 480:
            print("⚠ 超過 480 chars，threads.py thread 會自動切段")
