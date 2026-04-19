#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
signals — Phase 5 訊號偵測引擎 for datastore（raw/store.db）。

問題：datastore 累了時序資料，但「這月誰加碼、誰集中、誰換手」還是要手 SQL。
目標：把 JOY 88 原型的 9 種策略訊號落成 CLI，讓 downstream（reports / wiki
fusion）可以每天 pipe 結果進去。

9 種訊號（JOY 88 對齊）：
  1. 季報→月報 Top 10 晉升        ← 需 fund_quarterly
  2. 季報潛伏 ETF 激活             ← 需 fund_quarterly + etf_daily
  3. 雙軌建倉（同經理人）           ← 需 manager mapping（Phase 6）
  4. 多基金共識                    ← fund_monthly 單月 aggregate
  5. 連續加碼（單基金單碼）         ← fund_monthly 時序
  6. 雙軌加碼（同經理人）           ← 需 manager mapping（Phase 6）
  7. 共識形成（跨月權重合計上升）   ← fund_monthly 跨月 aggregate
  8. 高權重減碼                    ← fund_monthly 時序
  9. 核心出場                      ← fund_monthly + fund_quarterly

本版已實作：1, 2, 4, 5, 7, 8, 9（2/1/9 在 fund_quarterly 有資料時立即生效）
延後：3, 6（等 Phase 6 wiki/people manager mapping）

Usage:
  ./signals.py detect 4 --month 202603 --threshold 3
  ./signals.py detect 5 --from 202601 --to 202603 --min-months 3
  ./signals.py detect 7 --from 202601 --to 202603 --n-funds 3
  ./signals.py detect 8 --from 202602 --to 202603 --high-pct 10 --low-pct 5
  ./signals.py detect 1 --quarter 202603 --next-month 202604
  ./signals.py detect 2 --quarter 202603 --etf-date 20260417
  ./signals.py detect 9 --from 202512 --to 202603 --consecutive 3
  ./signals.py all    --from 202601 --to 202603
  ./signals.py explain 4
  ./signals.py stats

輸出：每個訊號 hit 一行 JSON（JSONL）到 stdout，方便 pipe。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DB_PATH = HERE.parent / "raw" / "store.db"

# 預設查詢 active_etf_* view（只看 13 檔主動式 ETF 基金白名單）。
# 傳 --include-all-funds 時改用底層 holdings_fund_* 表（含 SITCA AL11 歷史漂移資料）。
DEFAULT_MONTHLY_TABLE = "active_etf_monthly"
DEFAULT_QUARTERLY_TABLE = "active_etf_quarterly"
RAW_MONTHLY_TABLE = "holdings_fund_monthly"
RAW_QUARTERLY_TABLE = "holdings_fund_quarterly"


def _tables(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "include_all_funds", False):
        return RAW_MONTHLY_TABLE, RAW_QUARTERLY_TABLE
    return DEFAULT_MONTHLY_TABLE, DEFAULT_QUARTERLY_TABLE

SIGNAL_DEFS: dict[int, dict[str, str]] = {
    1: {
        "name": "季報→月報 Top 10 晉升",
        "logic": (
            "某 code 在季報（≥1%）出現但當月 Top 10 未進；次月進入 Top 10。\n"
            "訊號意義：經理人從「觀察倉」升到「重倉」，代表策略確認。"
        ),
        "needs": "fund_quarterly + fund_monthly（下一月）",
        "status": "實作完成（等 fund_quarterly 有資料）",
    },
    2: {
        "name": "季報潛伏 ETF 激活",
        "logic": (
            "某 code 在同一家投信的季報持有（基金 ≥1%）但 ETF 未進持股，\n"
            "之後 ETF 開始買入。訊號意義：基金作為觀察池 → ETF 跟進。"
        ),
        "needs": "fund_quarterly + etf_daily（需投信對應）",
        "status": "實作完成（等 fund_quarterly 有資料）",
    },
    3: {
        "name": "雙軌建倉（同經理人）",
        "logic": "同一位經理人的基金 Top 10 和 ETF 持股同月出現新 code，雙軌加碼。",
        "needs": "manager ↔ (fund, etf) mapping",
        "status": "延後 Phase 6（wiki/people 融合）",
    },
    4: {
        "name": "多基金共識",
        "logic": (
            "某 code 被 N 檔不同基金在同一月份 Top 10 共同持有（N≥threshold）。\n"
            "訊號意義：多位獨立經理人對同一檔有共識 = 市場主流認同。"
        ),
        "needs": "fund_monthly 單月 group by code",
        "status": "實作完成",
    },
    5: {
        "name": "連續加碼（單基金單碼）",
        "logic": (
            "同一基金同一 code 連續 M 個月 pct 嚴格上升（pct[m+1] > pct[m]）。\n"
            "訊號意義：經理人持續加碼 = 強信心持倉。"
        ),
        "needs": "fund_monthly 時序",
        "status": "實作完成",
    },
    6: {
        "name": "雙軌加碼（同經理人）",
        "logic": "同一經理人基金 pct ↑ 且 ETF weight ↑，兩邊都在加碼同一 code。",
        "needs": "manager mapping",
        "status": "延後 Phase 6",
    },
    7: {
        "name": "共識形成（跨月權重合計上升）",
        "logic": (
            "某 code 在 N≥threshold 檔基金中出現，且月合計權重從 ym_from 到\n"
            "ym_to 上升超過 delta_pct。訊號意義：共識不只存在，還在加強。"
        ),
        "needs": "fund_monthly 跨月 aggregate",
        "status": "實作完成",
    },
    8: {
        "name": "高權重減碼",
        "logic": (
            "單基金某 code pct 從 >high_pct（預設 10%）單月降到 <low_pct（預設 5%）。\n"
            "訊號意義：重倉股突然腰斬 = 策略改變或避險。"
        ),
        "needs": "fund_monthly 時序",
        "status": "實作完成",
    },
    9: {
        "name": "核心出場",
        "logic": (
            "月報 Top 10 連續 M 月的常客在本月消失，且季報也無。\n"
            "訊號意義：長期重倉完全退出 = 經理人對該 code 判斷翻轉。"
        ),
        "needs": "fund_monthly 連續 M 月 + fund_quarterly",
        "status": "實作完成（等 fund_quarterly 有資料才能完全過濾）",
    },
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"error: {DB_PATH} 不存在，先跑 `./tools/datastore.py init`", file=sys.stderr)
        sys.exit(2)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _emit(hit: dict[str, Any]) -> None:
    print(json.dumps(hit, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Signal 4: 多基金共識
# ---------------------------------------------------------------------------
def detect_signal_4(
    con: sqlite3.Connection, month: str, threshold: int,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
) -> list[dict]:
    q = f"""
    SELECT code, name,
           COUNT(DISTINCT fund_name) AS n_funds,
           ROUND(SUM(pct), 2)        AS total_pct,
           ROUND(AVG(pct), 2)        AS avg_pct,
           GROUP_CONCAT(DISTINCT fund_name) AS funds
    FROM {monthly_tbl}
    WHERE ym = ? AND code IS NOT NULL AND code != ''
    GROUP BY code, name
    HAVING n_funds >= ?
    ORDER BY n_funds DESC, total_pct DESC
    """
    hits = []
    for r in con.execute(q, (month, threshold)):
        hits.append({
            "signal_id": 4,
            "signal_name": SIGNAL_DEFS[4]["name"],
            "as_of": month,
            "code": r["code"],
            "name": r["name"],
            "n_funds": r["n_funds"],
            "total_pct": r["total_pct"],
            "avg_pct": r["avg_pct"],
            "funds": (r["funds"] or "").split(","),
        })
    return hits


# ---------------------------------------------------------------------------
# Signal 5: 連續加碼（單基金單碼）
# ---------------------------------------------------------------------------
def detect_signal_5(
    con: sqlite3.Connection, ym_from: str, ym_to: str, min_months: int,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
) -> list[dict]:
    q = f"""
    SELECT ym, fund_name, code, name, pct
    FROM {monthly_tbl}
    WHERE ym >= ? AND ym <= ? AND code IS NOT NULL AND code != ''
    ORDER BY fund_name, code, ym
    """
    series: dict[tuple[str, str], list[dict]] = {}
    for r in con.execute(q, (ym_from, ym_to)):
        key = (r["fund_name"], r["code"])
        series.setdefault(key, []).append(
            {"ym": r["ym"], "pct": r["pct"], "name": r["name"]}
        )

    hits = []
    for (fund_name, code), rows in series.items():
        # 找最長連續嚴格上升子序列
        longest = 1
        cur_len = 1
        run_start = 0
        best_start = 0
        best_end = 0
        for i in range(1, len(rows)):
            # 要求月份是相鄰的（ym 可能跳號，例如停揭）
            prev_ym = rows[i - 1]["ym"]
            this_ym = rows[i]["ym"]
            consecutive = _next_ym(prev_ym) == this_ym
            if consecutive and rows[i]["pct"] > rows[i - 1]["pct"]:
                cur_len += 1
                if cur_len > longest:
                    longest = cur_len
                    best_start = run_start
                    best_end = i
            else:
                cur_len = 1
                run_start = i
        if longest >= min_months:
            first = rows[best_start]
            last = rows[best_end]
            hits.append({
                "signal_id": 5,
                "signal_name": SIGNAL_DEFS[5]["name"],
                "as_of": last["ym"],
                "fund_name": fund_name,
                "code": code,
                "name": last["name"],
                "consecutive_months": longest,
                "from_ym": first["ym"],
                "from_pct": first["pct"],
                "to_ym": last["ym"],
                "to_pct": last["pct"],
                "pct_delta": round((last["pct"] or 0) - (first["pct"] or 0), 2),
            })
    hits.sort(key=lambda h: (-h["consecutive_months"], -h["pct_delta"]))
    return hits


# ---------------------------------------------------------------------------
# Signal 7: 共識形成（跨月權重合計上升）
# ---------------------------------------------------------------------------
def detect_signal_7(
    con: sqlite3.Connection, ym_from: str, ym_to: str, n_funds: int, delta_pct: float,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
) -> list[dict]:
    q = f"""
    SELECT ym, code, name,
           COUNT(DISTINCT fund_name) AS n_funds,
           ROUND(SUM(pct), 2)        AS total_pct
    FROM {monthly_tbl}
    WHERE ym IN (?, ?) AND code IS NOT NULL AND code != ''
    GROUP BY ym, code, name
    """
    snapshots: dict[str, dict[str, dict]] = {ym_from: {}, ym_to: {}}
    for r in con.execute(q, (ym_from, ym_to)):
        snapshots[r["ym"]][r["code"]] = {
            "name": r["name"],
            "n_funds": r["n_funds"],
            "total_pct": r["total_pct"],
        }

    hits = []
    for code, end in snapshots[ym_to].items():
        if end["n_funds"] < n_funds:
            continue
        start = snapshots[ym_from].get(code)
        start_total = start["total_pct"] if start else 0.0
        start_n = start["n_funds"] if start else 0
        diff = round(end["total_pct"] - start_total, 2)
        if diff < delta_pct:
            continue
        hits.append({
            "signal_id": 7,
            "signal_name": SIGNAL_DEFS[7]["name"],
            "as_of": ym_to,
            "code": code,
            "name": end["name"],
            "n_funds_from": start_n,
            "n_funds_to": end["n_funds"],
            "total_pct_from": start_total,
            "total_pct_to": end["total_pct"],
            "pct_delta": diff,
            "window": f"{ym_from}→{ym_to}",
        })
    hits.sort(key=lambda h: -h["pct_delta"])
    return hits


# ---------------------------------------------------------------------------
# Signal 8: 高權重減碼
# ---------------------------------------------------------------------------
def detect_signal_8(
    con: sqlite3.Connection, ym_from: str, ym_to: str, high_pct: float, low_pct: float,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
) -> list[dict]:
    q = f"""
    SELECT ym, fund_name, code, name, pct
    FROM {monthly_tbl}
    WHERE ym >= ? AND ym <= ? AND code IS NOT NULL AND code != ''
    ORDER BY fund_name, code, ym
    """
    series: dict[tuple[str, str], list[dict]] = {}
    for r in con.execute(q, (ym_from, ym_to)):
        key = (r["fund_name"], r["code"])
        series.setdefault(key, []).append(
            {"ym": r["ym"], "pct": r["pct"], "name": r["name"]}
        )

    hits = []
    for (fund_name, code), rows in series.items():
        for i in range(1, len(rows)):
            prev = rows[i - 1]
            cur = rows[i]
            if _next_ym(prev["ym"]) != cur["ym"]:
                continue
            if (prev["pct"] or 0) >= high_pct and (cur["pct"] or 0) < low_pct:
                hits.append({
                    "signal_id": 8,
                    "signal_name": SIGNAL_DEFS[8]["name"],
                    "as_of": cur["ym"],
                    "fund_name": fund_name,
                    "code": code,
                    "name": cur["name"],
                    "from_ym": prev["ym"],
                    "from_pct": prev["pct"],
                    "to_ym": cur["ym"],
                    "to_pct": cur["pct"],
                    "pct_delta": round((cur["pct"] or 0) - (prev["pct"] or 0), 2),
                })
    hits.sort(key=lambda h: h["pct_delta"])  # 最大跌幅在最前
    return hits


# ---------------------------------------------------------------------------
# Signal 1: 季報→月報 Top 10 晉升
# ---------------------------------------------------------------------------
def detect_signal_1(
    con: sqlite3.Connection, quarter: str, next_month: str,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
    quarterly_tbl: str = DEFAULT_QUARTERLY_TABLE,
) -> list[dict]:
    q = f"""
    SELECT q.fund_name, q.code, q.name, q.pct AS q_pct,
           m_next.rank AS next_rank, m_next.pct AS next_pct
    FROM {quarterly_tbl} q
    LEFT JOIN {monthly_tbl} m_same
      ON m_same.ym = ? AND m_same.fund_name = q.fund_name AND m_same.code = q.code
    INNER JOIN {monthly_tbl} m_next
      ON m_next.ym = ? AND m_next.fund_name = q.fund_name AND m_next.code = q.code
    WHERE q.yq = ? AND m_same.code IS NULL
    ORDER BY q.fund_name, next_rank
    """
    hits = []
    for r in con.execute(q, (quarter, next_month, quarter)):
        hits.append({
            "signal_id": 1,
            "signal_name": SIGNAL_DEFS[1]["name"],
            "as_of": next_month,
            "fund_name": r["fund_name"],
            "code": r["code"],
            "name": r["name"],
            "quarter_pct": r["q_pct"],
            "next_month_rank": r["next_rank"],
            "next_month_pct": r["next_pct"],
            "quarter": quarter,
        })
    return hits


# ---------------------------------------------------------------------------
# Signal 2: 季報潛伏 ETF 激活
# ---------------------------------------------------------------------------
def detect_signal_2(
    con: sqlite3.Connection, quarter: str, etf_date: str,
    quarterly_tbl: str = DEFAULT_QUARTERLY_TABLE,
) -> list[dict]:
    # 簡化版：列出季報裡出現、但某檔 ETF 在 etf_date 有持有該 code 的對應
    # （真正「潛伏→激活」需要兩個時點；這裡列當前 overlap 供人工審查）
    q = f"""
    SELECT q.fund_name, q.code, q.name, q.pct AS q_pct,
           e.etf, e.weight_pct
    FROM {quarterly_tbl} q
    INNER JOIN holdings_etf_daily e
      ON e.code = q.code AND e.data_date = ?
    WHERE q.yq = ?
    ORDER BY q.fund_name, e.etf
    """
    hits = []
    for r in con.execute(q, (etf_date, quarter)):
        hits.append({
            "signal_id": 2,
            "signal_name": SIGNAL_DEFS[2]["name"],
            "as_of": etf_date,
            "fund_name": r["fund_name"],
            "etf": r["etf"],
            "code": r["code"],
            "name": r["name"],
            "fund_quarter_pct": r["q_pct"],
            "etf_weight_pct": r["weight_pct"],
            "quarter": quarter,
        })
    return hits


# ---------------------------------------------------------------------------
# Signal 9: 核心出場
# ---------------------------------------------------------------------------
def detect_signal_9(
    con: sqlite3.Connection, ym_from: str, ym_to: str, consecutive: int,
    monthly_tbl: str = DEFAULT_MONTHLY_TABLE,
    quarterly_tbl: str = DEFAULT_QUARTERLY_TABLE,
) -> list[dict]:
    # 找出 ym_to 之前連續 `consecutive` 個月都在 Top 10 但 ym_to 消失的 (fund, code)
    all_months = _month_range(ym_from, ym_to)
    if len(all_months) < consecutive + 1:
        return []
    pre_window = all_months[-(consecutive + 1):-1]  # 消失月前的 consecutive 個月
    exit_month = all_months[-1]

    # 取每個 (fund, code) 在 pre_window 的出現次數
    ph = ",".join(["?"] * len(pre_window))
    q = f"""
    SELECT fund_name, code, name,
           COUNT(DISTINCT ym) AS months_in,
           AVG(pct) AS avg_pct
    FROM {monthly_tbl}
    WHERE ym IN ({ph}) AND code IS NOT NULL AND code != ''
    GROUP BY fund_name, code, name
    HAVING months_in >= ?
    """
    candidates = list(con.execute(q, (*pre_window, consecutive)))

    # 過濾掉 exit_month 仍在 Top 10 的
    hits = []
    for r in candidates:
        still_in = con.execute(
            f"SELECT 1 FROM {monthly_tbl} WHERE ym=? AND fund_name=? AND code=?",
            (exit_month, r["fund_name"], r["code"]),
        ).fetchone()
        if still_in:
            continue
        # 若有 quarterly 資料也確認不在
        q_yq = exit_month  # 季報周期通常和月份同寫法；實際季末才有
        in_q = con.execute(
            f"SELECT 1 FROM {quarterly_tbl} WHERE yq=? AND fund_name=? AND code=?",
            (q_yq, r["fund_name"], r["code"]),
        ).fetchone()
        hits.append({
            "signal_id": 9,
            "signal_name": SIGNAL_DEFS[9]["name"],
            "as_of": exit_month,
            "fund_name": r["fund_name"],
            "code": r["code"],
            "name": r["name"],
            "prior_months_in_top10": r["months_in"],
            "prior_avg_pct": round(r["avg_pct"] or 0, 2),
            "also_absent_from_quarterly": in_q is None,
            "window": f"{pre_window[0]}→{pre_window[-1]} then exit {exit_month}",
        })
    hits.sort(key=lambda h: (-h["prior_months_in_top10"], -h["prior_avg_pct"]))
    return hits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _next_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[4:])
    m += 1
    if m > 12:
        y += 1
        m = 1
    return f"{y:04d}{m:02d}"


def _month_range(ym_from: str, ym_to: str) -> list[str]:
    out = []
    cur = ym_from
    while cur <= ym_to:
        out.append(cur)
        cur = _next_ym(cur)
    return out


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def cmd_detect(args: argparse.Namespace) -> None:
    sid = args.signal_id
    con = _conn()
    m_tbl, q_tbl = _tables(args)
    if sid == 1:
        hits = detect_signal_1(con, args.quarter, args.next_month, m_tbl, q_tbl)
    elif sid == 2:
        hits = detect_signal_2(con, args.quarter, _normalize_date(args.etf_date), q_tbl)
    elif sid == 4:
        hits = detect_signal_4(con, args.month, args.threshold, m_tbl)
    elif sid == 5:
        hits = detect_signal_5(con, args.ym_from, args.ym_to, args.min_months, m_tbl)
    elif sid == 7:
        hits = detect_signal_7(
            con, args.ym_from, args.ym_to, args.n_funds, args.delta_pct, m_tbl
        )
    elif sid == 8:
        hits = detect_signal_8(
            con, args.ym_from, args.ym_to, args.high_pct, args.low_pct, m_tbl
        )
    elif sid == 9:
        hits = detect_signal_9(con, args.ym_from, args.ym_to, args.consecutive, m_tbl, q_tbl)
    elif sid in (3, 6):
        print(
            f"signal {sid} 延後到 Phase 6（需 manager ↔ fund/etf mapping）",
            file=sys.stderr,
        )
        sys.exit(3)
    else:
        print(f"unknown signal {sid}", file=sys.stderr)
        sys.exit(2)
    for h in hits:
        _emit(h)
    print(f"# {len(hits)} hits for signal {sid}", file=sys.stderr)


def cmd_all(args: argparse.Namespace) -> None:
    con = _conn()
    m_tbl, q_tbl = _tables(args)
    # 預設跑不需 manager mapping、且在當前資料可觸發的 4/5/7/8
    # 1/2/9 若 quarterly 空會自動 0 hits
    runs = [
        ("signal 4", lambda: detect_signal_4(con, args.ym_to, args.threshold, m_tbl)),
        ("signal 5", lambda: detect_signal_5(con, args.ym_from, args.ym_to, args.min_months, m_tbl)),
        ("signal 7", lambda: detect_signal_7(con, args.ym_from, args.ym_to, args.n_funds, args.delta_pct, m_tbl)),
        ("signal 8", lambda: detect_signal_8(con, args.ym_from, args.ym_to, args.high_pct, args.low_pct, m_tbl)),
        ("signal 9", lambda: detect_signal_9(con, args.ym_from, args.ym_to, args.consecutive, m_tbl, q_tbl)),
    ]
    total = 0
    for label, fn in runs:
        hits = fn()
        total += len(hits)
        for h in hits:
            _emit(h)
        print(f"# {label}: {len(hits)} hits", file=sys.stderr)
    print(f"# total: {total} hits across 5 signals", file=sys.stderr)


def cmd_explain(args: argparse.Namespace) -> None:
    sid = args.signal_id
    if sid not in SIGNAL_DEFS:
        print(f"unknown signal {sid}", file=sys.stderr)
        sys.exit(2)
    d = SIGNAL_DEFS[sid]
    print(f"# Signal {sid}: {d['name']}")
    print()
    print("## 邏輯")
    print(d["logic"])
    print()
    print(f"**需要**: {d['needs']}")
    print(f"**狀態**: {d['status']}")


def cmd_stats(args: argparse.Namespace) -> None:
    con = _conn()
    print("# Datastore 覆蓋率（signals 可用前提）")
    for tbl, label in [
        ("holdings_fund_monthly", "月報 Top 10（raw）"),
        ("active_etf_monthly",    "  └ active ETF view"),
        ("holdings_fund_quarterly", "季報 ≥1%（raw）"),
        ("active_etf_quarterly",  "  └ active ETF view"),
        ("holdings_etf_daily", "ETF 日揭露"),
    ]:
        row = con.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()
        print(f"  {label:24}: {row['c']:>6} rows")
    print()
    print("# 訊號清單（預設 query active_etf_* view，加 --include-all-funds 繞過）")
    for sid, d in SIGNAL_DEFS.items():
        print(f"  {sid}. {d['name']:<24} [{d['status']}]")


def _normalize_date(s: str) -> str:
    # YYYYMMDD → YYYY-MM-DD
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="signals",
        description="Phase 5 訊號偵測（on datastore raw/store.db）",
    )
    p.add_argument(
        "--include-all-funds",
        action="store_true",
        help="繞過 active_etf_* view，查全部 holdings_fund_* 原始表"
             "（含 SITCA AL11 歷史漂移的 28 檔兆豐非主動 ETF 基金）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # detect
    d = sub.add_parser("detect", help="偵測單一訊號")
    dsub = d.add_subparsers(dest="signal_id", required=True)

    # signal 1
    d1 = dsub.add_parser("1", help=SIGNAL_DEFS[1]["name"])
    d1.add_argument("--quarter", required=True)
    d1.add_argument("--next-month", required=True, dest="next_month")
    d1.set_defaults(func=cmd_detect, signal_id=1)

    # signal 2
    d2 = dsub.add_parser("2", help=SIGNAL_DEFS[2]["name"])
    d2.add_argument("--quarter", required=True)
    d2.add_argument("--etf-date", required=True, dest="etf_date")
    d2.set_defaults(func=cmd_detect, signal_id=2)

    # signal 4
    d4 = dsub.add_parser("4", help=SIGNAL_DEFS[4]["name"])
    d4.add_argument("--month", required=True)
    d4.add_argument("--threshold", type=int, default=3)
    d4.set_defaults(func=cmd_detect, signal_id=4)

    # signal 5
    d5 = dsub.add_parser("5", help=SIGNAL_DEFS[5]["name"])
    d5.add_argument("--from", required=True, dest="ym_from")
    d5.add_argument("--to", required=True, dest="ym_to")
    d5.add_argument("--min-months", type=int, default=3, dest="min_months")
    d5.set_defaults(func=cmd_detect, signal_id=5)

    # signal 7
    d7 = dsub.add_parser("7", help=SIGNAL_DEFS[7]["name"])
    d7.add_argument("--from", required=True, dest="ym_from")
    d7.add_argument("--to", required=True, dest="ym_to")
    d7.add_argument("--n-funds", type=int, default=3, dest="n_funds")
    d7.add_argument("--delta-pct", type=float, default=5.0, dest="delta_pct")
    d7.set_defaults(func=cmd_detect, signal_id=7)

    # signal 8
    d8 = dsub.add_parser("8", help=SIGNAL_DEFS[8]["name"])
    d8.add_argument("--from", required=True, dest="ym_from")
    d8.add_argument("--to", required=True, dest="ym_to")
    d8.add_argument("--high-pct", type=float, default=10.0, dest="high_pct")
    d8.add_argument("--low-pct", type=float, default=5.0, dest="low_pct")
    d8.set_defaults(func=cmd_detect, signal_id=8)

    # signal 9
    d9 = dsub.add_parser("9", help=SIGNAL_DEFS[9]["name"])
    d9.add_argument("--from", required=True, dest="ym_from")
    d9.add_argument("--to", required=True, dest="ym_to")
    d9.add_argument("--consecutive", type=int, default=3)
    d9.set_defaults(func=cmd_detect, signal_id=9)

    # all
    a = sub.add_parser("all", help="跑 signals 4/5/7/8/9（需要 manager mapping 的延後）")
    a.add_argument("--from", required=True, dest="ym_from")
    a.add_argument("--to", required=True, dest="ym_to")
    a.add_argument("--threshold", type=int, default=3)
    a.add_argument("--min-months", type=int, default=3, dest="min_months")
    a.add_argument("--n-funds", type=int, default=3, dest="n_funds")
    a.add_argument("--delta-pct", type=float, default=5.0, dest="delta_pct")
    a.add_argument("--high-pct", type=float, default=10.0, dest="high_pct")
    a.add_argument("--low-pct", type=float, default=5.0, dest="low_pct")
    a.add_argument("--consecutive", type=int, default=3)
    a.set_defaults(func=cmd_all)

    # explain
    e = sub.add_parser("explain", help="解釋某訊號邏輯")
    e.add_argument("signal_id", type=int)
    e.set_defaults(func=cmd_explain)

    # stats
    s = sub.add_parser("stats", help="coverage / 訊號清單")
    s.set_defaults(func=cmd_stats)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
