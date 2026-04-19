#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
datastore — SQLite 時序儲存 for managerwatch + etfdaily（Phase 4）。

問題：Phase 1 (managerwatch) 抓 SITCA 月/季報，Phase 2 (etfdaily) 抓 6 投信
官網日揭露。每次都 re-fetch + re-parse 太慢，且無法做時序 diff（同 ETF 跨日、
同基金跨月、同經理人跨產品）。

設計：四張 holdings 表 + 一張 meta + 一張 log，subprocess 呼叫兩個 primary
CLI 的 `--json` 輸出做 ingest。SQLite 單檔放 `raw/store.db`（gitignored，
可重現）。

Schema：
  holdings_fund_monthly     (ym, fund_name, rank)       ← SITCA IN2629
  holdings_fund_quarterly   (yq, fund_name, code)       ← SITCA IN2630（≥1%）
  holdings_etf_daily        (data_date, etf, code, kind)← etfdaily
  etf_meta_daily            (data_date, etf)            ← aum/units/nav
  ingest_log                auto-increment              ← trace every run

Subcommands:
  init                              建表（idempotent）
  ingest sitca-monthly --month YYYYMM [--class AL11] [--comid A0009]
  ingest sitca-quarterly --quarter YYYYMM [--class AL11] [--comid A0009]
  ingest etf-daily [--date YYYYMMDD] [--code 00981A|--all]
  ingest all [--date YYYYMMDD]      便利：6 ETF daily + optional month
  query holdings --etf <code> [--date YYYYMMDD]
  query fund --name <pattern> [--ym YYYYMM]
  query consensus --code <stock> [--date YYYYMMDD]
                                    某股票被多少 ETF/基金持有 + 合計權重
  query diff --etf <code> --from YYYYMMDD --to YYYYMMDD
  stats                             coverage / 列數 / 日期範圍

Usage:
  ./datastore.py init
  ./datastore.py ingest sitca-monthly --month 202603 --class AL11
  ./datastore.py ingest etf-daily --all --date 20260417
  ./datastore.py query consensus --code 2330 --date 20260417
  ./datastore.py stats
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
DB_PATH = REPO_ROOT / "raw" / "store.db"

MANAGERWATCH = TOOLS_DIR / "managerwatch.py"
ETFDAILY = TOOLS_DIR / "etfdaily.py"
MOPSETF = TOOLS_DIR / "mopsetf.py"

# 6 檔主動 ETF（對應 etfdaily CATALOG）
ETF_CODES = [
    "00981A", "00988A",                    # 統一
    "00991A",                              # 復華
    "00980A", "00985A",                    # 野村
    "00993A", "00984A",                    # 安聯
    "00982A", "00992A", "00997A",          # 群益
]

# kind 欄位正規化（issuer parser 回傳中/英混用，統一成英文）
# 野村 00980A 同一天同時有 'stock' 和 '股票'（不同 section）
# 安聯 00993A 純中文 '股票' / '期貨'
# 其他投信純英文 'stock'
KIND_MAP: dict[str, str] = {
    # stock
    "股票": "stock",
    "stock": "stock",
    "Stock": "stock",
    "現股": "stock",
    "equity": "stock",
    # future
    "期貨": "future",
    "future": "future",
    "futures": "future",
    "Future": "future",
    # cash
    "現金": "cash",
    "cash": "cash",
    "Cash": "cash",
    # bond
    "債券": "bond",
    "bond": "bond",
    "Bond": "bond",
}


def _normalize_kind(k: str | None) -> str:
    """中/英 kind 標籤統一成英文。未知值原樣 pass through 以便 debug。"""
    if not k:
        return "stock"
    k = k.strip()
    return KIND_MAP.get(k, k)


# ── Schema ────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings_fund_monthly (
  ym          TEXT NOT NULL,       -- '202603'
  fund_name   TEXT NOT NULL,       -- 含括號備註
  comid       TEXT,                -- 'A0009'（optional，ingest 帶入）
  fund_class  TEXT,                -- 'AL11'
  rank        INTEGER NOT NULL,    -- 1..10（Top 10 排名）
  code        TEXT,                -- '2330'
  kind        TEXT,                -- '國內上市' / '國內上櫃' / '國外'…
  name        TEXT,                -- '台積電'
  amount      REAL,                -- 持股市值（元）
  pct         REAL,                -- 占基金淨資產比例 %
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (ym, fund_name, rank)
);
CREATE INDEX IF NOT EXISTS idx_fm_code ON holdings_fund_monthly(code, ym);
CREATE INDEX IF NOT EXISTS idx_fm_comid ON holdings_fund_monthly(comid, ym);

CREATE TABLE IF NOT EXISTS holdings_fund_quarterly (
  yq          TEXT NOT NULL,       -- '202603'（季報周期）
  fund_name   TEXT NOT NULL,
  comid       TEXT,
  fund_class  TEXT,
  rank        INTEGER,             -- 季報 ≥1% 可能無 rank
  code        TEXT NOT NULL,
  kind        TEXT,
  name        TEXT,
  amount      REAL,
  pct         REAL,
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (yq, fund_name, code)
);
CREATE INDEX IF NOT EXISTS idx_fq_code ON holdings_fund_quarterly(code, yq);
CREATE INDEX IF NOT EXISTS idx_fq_comid ON holdings_fund_quarterly(comid, yq);

CREATE TABLE IF NOT EXISTS holdings_etf_daily (
  data_date   TEXT NOT NULL,       -- '2026-04-17'
  etf         TEXT NOT NULL,       -- '00981A'
  code        TEXT NOT NULL,       -- '2330' / 'LITE US' / '6787 JP'
  kind        TEXT NOT NULL,       -- 'stock' / 'future' / 'bond' / 'cash'
  name        TEXT,
  shares      REAL,
  weight_pct  REAL,
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (data_date, etf, code, kind)
);
CREATE INDEX IF NOT EXISTS idx_ed_code ON holdings_etf_daily(code, data_date);
CREATE INDEX IF NOT EXISTS idx_ed_etf ON holdings_etf_daily(etf, data_date);

CREATE TABLE IF NOT EXISTS etf_meta_daily (
  data_date   TEXT NOT NULL,
  etf         TEXT NOT NULL,
  issuer      TEXT,
  source      TEXT,
  format      TEXT,
  aum         REAL,
  units       REAL,
  nav         REAL,
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (data_date, etf)
);

CREATE TABLE IF NOT EXISTS ingest_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source      TEXT NOT NULL,       -- 'managerwatch' / 'etfdaily'
  target      TEXT NOT NULL,       -- 'sitca-monthly:202603:AL11' / 'etfdaily:00981A:20260417'
  row_count   INTEGER,
  ok          INTEGER NOT NULL,    -- 0/1
  error       TEXT,
  ingested_at TEXT NOT NULL
);

-- 主動式 ETF 基金白名單（SITCA 歷史期 filter bug 的下游防禦）
-- fund_short = fund_name 前綴（不含括號備註），用 LIKE 'short%' match 完整版
CREATE TABLE IF NOT EXISTS active_etf_whitelist (
  fund_short  TEXT PRIMARY KEY,    -- e.g. '統一台股增長主動式ETF基金'
  etf_code    TEXT,                -- e.g. '00981A'（可選，對應 ETF）
  issuer      TEXT,                -- e.g. '統一投信' / comid 'A0009'
  added_at    TEXT NOT NULL,
  note        TEXT                 -- 備註（來源/為何加入）
);

-- 下游 view：只回乾淨的主動式 ETF 基金 rows，並把 fund_name 投射成 whitelist
-- 的 fund_short（去掉括號備註），讓 MOPS（無備註）與 SITCA（有「(基金之配息
-- 來源可能為收益平準金)」後綴）的同一檔基金在 downstream 被視為同一個 key。
-- 直接 query raw table 還是拿得到帶備註的原名；此 view 專給 signals / peoplefuse 等
-- cross-source 分析用。
CREATE VIEW IF NOT EXISTS active_etf_monthly AS
  SELECT h.ym,
         w.fund_short AS fund_name,
         h.comid, h.fund_class, h.rank, h.code, h.kind, h.name,
         h.amount, h.pct, h.ingested_at
  FROM holdings_fund_monthly h
  JOIN active_etf_whitelist w
    ON h.fund_name = w.fund_short
    OR h.fund_name LIKE w.fund_short || ' %'
    OR h.fund_name LIKE w.fund_short || '(%';

CREATE VIEW IF NOT EXISTS active_etf_quarterly AS
  SELECT h.yq,
         w.fund_short AS fund_name,
         h.comid, h.fund_class, h.rank, h.code, h.kind, h.name,
         h.amount, h.pct, h.ingested_at
  FROM holdings_fund_quarterly h
  JOIN active_etf_whitelist w
    ON h.fund_name = w.fund_short
    OR h.fund_name LIKE w.fund_short || ' %'
    OR h.fund_name LIKE w.fund_short || '(%';
"""


# 白名單種子（2026-04-19 從 SITCA IN2630 季報 202603 AL11 抽取的 13 檔）
# fund_short 是月報/季報 fund_name 去掉括號備註後的前綴
ACTIVE_ETF_SEED: list[tuple[str, str | None, str | None]] = [
    # (fund_short, etf_code, issuer)
    # etf_code 以 TWSE/TPEx 盤後官方（twquote active）為準（Round 49）
    ("中國信託台灣卓越成長主動式ETF基金",         "00995A",   "中國信託"),
    ("兆豐台灣豐收主動式 ETF基金",                 "00996A",   "兆豐投信"),
    ("台新臺灣優勢成長主動式ETF基金",              "00987A",   "台新投信"),
    ("國泰台股動能高息主動式ETF基金",              "00400A",   "國泰投信"),
    ("安聯台灣主動式ETF基金",                      "00993A",   "安聯投信"),
    ("安聯台灣高息成長主動式ETF基金",              "00984A",   "安聯投信"),
    ("復華台灣未來50主動式ETF基金",                "00991A",   "復華投信"),
    ("第一金台股趨勢優選主動式ETF基金",            "00994A",   "第一金投信"),
    ("統一台股增長主動式ETF基金",                  "00981A",   "統一投信"),
    ("群益台灣科技創新主動式ETF基金",              "00992A",   "群益投信"),
    ("群益台灣精選強棒主動式ETF基金",              "00982A",   "群益投信"),
    ("野村臺灣增強50主動式ETF基金",                "00985A",   "野村投信"),
    ("野村臺灣智慧優選主動式ETF基金",              "00980A",   "野村投信"),
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _log(conn: sqlite3.Connection, source: str, target: str,
         row_count: int, ok: bool, error: str | None = None) -> None:
    conn.execute(
        "INSERT INTO ingest_log(source,target,row_count,ok,error,ingested_at)"
        " VALUES (?,?,?,?,?,?)",
        (source, target, row_count, 1 if ok else 0, error, _now_iso()),
    )


def _run_json(cli: Path, args: list[str]) -> dict:
    """呼叫子 CLI 的 --json 輸出並 parse。"""
    cmd = [str(cli), *args, "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess fail: {' '.join(cmd)}\n"
            f"stderr:\n{proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON from {cli.name}: {e}\nstdout head: {proc.stdout[:300]}")


# ── init ──────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    conn = _connect()
    conn.executescript(SCHEMA)
    # seed whitelist if empty
    n_wl = conn.execute("SELECT COUNT(*) FROM active_etf_whitelist").fetchone()[0]
    if n_wl == 0:
        _seed_whitelist(conn)
        print(f"✔ seeded active_etf_whitelist with {len(ACTIVE_ETF_SEED)} funds",
              file=sys.stderr)
    conn.commit()
    print(f"✔ schema initialized at {DB_PATH}", file=sys.stderr)
    # sanity
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name"
    ).fetchall()
    for r in rows:
        print(f"  [{r['type']}] {r['name']}", file=sys.stderr)
    conn.close()
    return 0


def _seed_whitelist(conn: sqlite3.Connection) -> None:
    now = _now_iso()
    for fund_short, etf_code, issuer in ACTIVE_ETF_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO active_etf_whitelist"
            "(fund_short, etf_code, issuer, added_at, note) VALUES (?,?,?,?,?)",
            (fund_short, etf_code, issuer, now, "seeded from SITCA IN2630 202603")
        )


# ── whitelist subcommand ──────────────────────────────────────────────

def cmd_whitelist_list(args: argparse.Namespace) -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT fund_short, etf_code, issuer, added_at, note"
        " FROM active_etf_whitelist ORDER BY fund_short"
    ).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return 0
    print(f"主動式 ETF 基金白名單（{len(rows)} 檔）", file=sys.stderr)
    for r in rows:
        etf = r["etf_code"] or "-"
        iss = r["issuer"] or "-"
        print(f"  {etf:8}  {iss:8}  {r['fund_short']}")
    return 0


def cmd_whitelist_add(args: argparse.Namespace) -> int:
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO active_etf_whitelist"
        "(fund_short, etf_code, issuer, added_at, note) VALUES (?,?,?,?,?)",
        (args.fund_short, args.etf_code, args.issuer, _now_iso(), args.note or "manual add")
    )
    conn.commit()
    print(f"✔ whitelist add: {args.fund_short}", file=sys.stderr)
    return 0


def cmd_whitelist_remove(args: argparse.Namespace) -> int:
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM active_etf_whitelist WHERE fund_short = ?",
        (args.fund_short,)
    )
    conn.commit()
    if cur.rowcount:
        print(f"✔ whitelist remove: {args.fund_short}", file=sys.stderr)
    else:
        print(f"✘ not found: {args.fund_short}", file=sys.stderr)
        return 1
    return 0


def cmd_whitelist_reseed(args: argparse.Namespace) -> int:
    """重灌種子。預設 INSERT OR IGNORE（不覆蓋既有 row）；
    加 --force-codes 時用 INSERT OR REPLACE，會把 seed 裡的 etf_code/issuer
    覆蓋既有 row（手動 add 的 fund_short 不在 seed 裡仍保留）。"""
    conn = _connect()
    if args.force_codes:
        now = _now_iso()
        for fund_short, etf_code, issuer in ACTIVE_ETF_SEED:
            conn.execute(
                "INSERT OR REPLACE INTO active_etf_whitelist"
                "(fund_short, etf_code, issuer, added_at, note) VALUES (?,?,?,?,?)",
                (fund_short, etf_code, issuer, now,
                 "reseeded from twquote active (TWSE/TPEx 盤後) 2026-04-19")
            )
    else:
        _seed_whitelist(conn)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM active_etf_whitelist").fetchone()[0]
    print(f"✔ reseeded; whitelist now has {n} entries", file=sys.stderr)
    return 0


def cmd_whitelist_coverage(args: argparse.Namespace) -> int:
    """對比 active_etf_monthly view vs 底層 holdings_fund_monthly 的覆蓋差異"""
    conn = _connect()
    rows = conn.execute(
        "SELECT ym,"
        "       COUNT(DISTINCT fund_name) AS total_funds,"
        "       (SELECT COUNT(DISTINCT fund_name) FROM active_etf_monthly v WHERE v.ym = h.ym) AS active_funds"
        " FROM holdings_fund_monthly h"
        " WHERE fund_class='AL11' GROUP BY ym ORDER BY ym"
    ).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return 0
    print("AL11 monthly coverage（raw vs active_etf view）", file=sys.stderr)
    print(f"{'ym':<8}  {'raw':>5}  {'active':>6}  {'diff':>5}")
    for r in rows:
        diff = r["total_funds"] - r["active_funds"]
        print(f"{r['ym']:<8}  {r['total_funds']:>5}  {r['active_funds']:>6}  {diff:>5}")
    return 0


# ── ingest: sitca-monthly ─────────────────────────────────────────────

def _ingest_sitca_monthly(conn: sqlite3.Connection, month: str,
                          class_code: str | None, comid: str | None) -> int:
    cli_args = ["sitca", "monthly", "--month", month]
    if comid:
        cli_args += ["--by", "comid", "--comid", comid]
        if class_code:
            cli_args += ["--class", class_code]
    else:
        cli_args += ["--by", "class"]
        if class_code:
            cli_args += ["--class", class_code]

    payload = _run_json(MANAGERWATCH, cli_args)
    rows = payload.get("rows", [])
    now = _now_iso()
    n = 0
    for r in rows:
        fund = r["fund"]
        rank = r.get("rank") or 0
        conn.execute(
            "INSERT OR REPLACE INTO holdings_fund_monthly"
            "(ym,fund_name,comid,fund_class,rank,code,kind,name,amount,pct,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                month,
                fund,
                comid or payload.get("comid"),
                class_code or payload.get("class"),
                rank,
                r.get("target_code") or None,
                r.get("target_type") or None,
                r.get("target_name") or None,
                r.get("amount"),
                r.get("pct"),
                now,
            ),
        )
        n += 1
    return n


def cmd_ingest_sitca_monthly(args: argparse.Namespace) -> int:
    conn = _connect()
    target = f"sitca-monthly:{args.month}:{args.class_code or 'ALL'}:{args.comid or '-'}"
    try:
        n = _ingest_sitca_monthly(conn, args.month, args.class_code, args.comid)
        _log(conn, "managerwatch", target, n, True)
        conn.commit()
        print(f"✔ sitca-monthly {args.month} → {n} rows", file=sys.stderr)
        return 0
    except Exception as e:
        _log(conn, "managerwatch", target, 0, False, str(e))
        conn.commit()
        print(f"✘ sitca-monthly {args.month}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


# ── ingest: mops-monthly ──────────────────────────────────────────────
# 補 SITCA IN2629 歷史期 filter 失效的洞（見 wiki/mechanisms/sitca-history-filter-bug）
# MOPS t78sb39_q3 Top 5（比 SITCA 的 Top 10 淺，但歷史可查）
# 2026-04-19 破解，覆蓋 202511 起（主動 ETF 陸續上線）

def _ingest_mops_monthly(conn: sqlite3.Connection, month: str) -> int:
    payload = _run_json(MOPSETF, ["monthly", "--month", month, "--json"])
    funds = payload.get("funds", [])
    now = _now_iso()
    n = 0
    for f in funds:
        fund_name = f["fund_name"]  # 已 normalize（對齊 whitelist short）
        comid = f.get("comid") or "MOPS"
        for h in f.get("top5", []):
            conn.execute(
                "INSERT OR REPLACE INTO holdings_fund_monthly"
                "(ym,fund_name,comid,fund_class,rank,code,kind,name,amount,pct,ingested_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    month,
                    fund_name,
                    comid,
                    "AL11",
                    h.get("rank"),
                    h.get("code"),
                    "stock",
                    h.get("name"),
                    None,  # MOPS Top 5 只有 pct 沒金額
                    h.get("pct"),
                    now,
                ),
            )
            n += 1
    return n


def cmd_ingest_mops_monthly(args: argparse.Namespace) -> int:
    conn = _connect()
    target = f"mops-monthly:{args.month}"
    try:
        n = _ingest_mops_monthly(conn, args.month)
        _log(conn, "mopsetf", target, n, True)
        conn.commit()
        print(f"✔ mops-monthly {args.month} → {n} rows", file=sys.stderr)
        return 0
    except Exception as e:
        _log(conn, "mopsetf", target, 0, False, str(e))
        conn.commit()
        print(f"✘ mops-monthly {args.month}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def cmd_backfill_mops_monthly(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        months = _month_range(args.ym_from, args.ym_to)
        ok = fail = 0
        for m in months:
            target = f"mops-monthly:{m}"
            try:
                n = _ingest_mops_monthly(conn, m)
                _log(conn, "mopsetf", target, n, True)
                print(f"✔ {m} → {n} rows", file=sys.stderr)
                ok += 1
            except Exception as e:
                _log(conn, "mopsetf", target, 0, False, str(e))
                print(f"✘ {m}: {e}", file=sys.stderr)
                fail += 1
            conn.commit()
        print(f"Done: {ok} ok / {fail} fail / {len(months)} total", file=sys.stderr)
        return 0 if fail == 0 else 1
    finally:
        conn.close()


# ── ingest: sitca-quarterly ───────────────────────────────────────────

def _ingest_sitca_quarterly(conn: sqlite3.Connection, quarter: str,
                            class_code: str | None, comid: str | None) -> int:
    cli_args = ["sitca", "quarterly", "--quarter", quarter]
    if comid:
        cli_args += ["--by", "comid", "--comid", comid]
        if class_code:
            cli_args += ["--class", class_code]
    else:
        cli_args += ["--by", "class"]
        if class_code:
            cli_args += ["--class", class_code]

    payload = _run_json(MANAGERWATCH, cli_args)
    rows = payload.get("rows", [])
    now = _now_iso()
    n = 0
    for r in rows:
        fund = r["fund"]
        code = r.get("target_code") or ""
        if not code:
            continue  # 季報以 code 為 key，沒 code 跳過
        conn.execute(
            "INSERT OR REPLACE INTO holdings_fund_quarterly"
            "(yq,fund_name,comid,fund_class,rank,code,kind,name,amount,pct,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                quarter,
                fund,
                comid or payload.get("comid"),
                class_code or payload.get("class"),
                r.get("rank"),
                code,
                r.get("target_type") or None,
                r.get("target_name") or None,
                r.get("amount"),
                r.get("pct"),
                now,
            ),
        )
        n += 1
    return n


def cmd_ingest_sitca_quarterly(args: argparse.Namespace) -> int:
    conn = _connect()
    target = f"sitca-quarterly:{args.quarter}:{args.class_code or 'ALL'}:{args.comid or '-'}"
    try:
        n = _ingest_sitca_quarterly(conn, args.quarter, args.class_code, args.comid)
        _log(conn, "managerwatch", target, n, True)
        conn.commit()
        print(f"✔ sitca-quarterly {args.quarter} → {n} rows", file=sys.stderr)
        return 0
    except Exception as e:
        _log(conn, "managerwatch", target, 0, False, str(e))
        conn.commit()
        print(f"✘ sitca-quarterly {args.quarter}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


# ── ingest: etf-daily ─────────────────────────────────────────────────

def _ingest_etf_daily_one(conn: sqlite3.Connection, code: str,
                          date_ymd: str | None) -> int:
    cli_args = ["holdings", code]
    if date_ymd:
        cli_args += ["--date", date_ymd]
    payload = _run_json(ETFDAILY, cli_args)
    data_date = _normalize_date(payload.get("data_date"))
    if not data_date:
        # fallback：用 CLI --date 參數或最近交易日
        data_date = _normalize_date(date_ymd) if date_ymd else _last_weekday_dash()
    holdings = payload.get("holdings", [])
    now = _now_iso()

    conn.execute(
        "INSERT OR REPLACE INTO etf_meta_daily"
        "(data_date,etf,issuer,source,format,aum,units,nav,ingested_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            data_date,
            code,
            payload.get("issuer"),
            payload.get("source"),
            payload.get("format"),
            payload.get("aum"),
            payload.get("units"),
            payload.get("nav"),
            now,
        ),
    )

    n = 0
    for h in holdings:
        hcode = (h.get("code") or "").strip()
        if not hcode:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO holdings_etf_daily"
            "(data_date,etf,code,kind,name,shares,weight_pct,ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                data_date,
                code,
                hcode,
                _normalize_kind(h.get("kind")),
                h.get("name"),
                h.get("shares"),
                h.get("weight_pct"),
                now,
            ),
        )
        n += 1
    return n


def cmd_ingest_etf_daily(args: argparse.Namespace) -> int:
    conn = _connect()
    codes = ETF_CODES if args.all else [args.code]
    total = 0
    errors = 0
    for code in codes:
        target = f"etfdaily:{code}:{args.date or 'auto'}"
        try:
            n = _ingest_etf_daily_one(conn, code, args.date)
            _log(conn, "etfdaily", target, n, True)
            total += n
            print(f"  ✔ {code} → {n} holdings", file=sys.stderr)
        except Exception as e:
            _log(conn, "etfdaily", target, 0, False, str(e))
            errors += 1
            print(f"  ✘ {code}: {e}", file=sys.stderr)
    conn.commit()
    conn.close()
    print(f"✔ etf-daily done: {total} rows across {len(codes)} ETFs, {errors} errors",
          file=sys.stderr)
    return 0 if errors == 0 else 1


# ── ingest: all ───────────────────────────────────────────────────────

def cmd_ingest_all(args: argparse.Namespace) -> int:
    """便利：跑 6 ETF daily（所有主動 ETF 當日 snapshot）。"""
    ns = argparse.Namespace(all=True, code=None, date=args.date)
    rc = cmd_ingest_etf_daily(ns)
    return rc


# ── query: holdings ───────────────────────────────────────────────────

def cmd_query_holdings(args: argparse.Namespace) -> int:
    conn = _connect()
    if args.date:
        date_dash = _ymd_to_dash(args.date)
        rows = conn.execute(
            "SELECT data_date,etf,code,kind,name,shares,weight_pct"
            " FROM holdings_etf_daily WHERE etf=? AND data_date=?"
            " ORDER BY weight_pct DESC",
            (args.etf, date_dash),
        ).fetchall()
    else:
        latest = conn.execute(
            "SELECT MAX(data_date) AS d FROM holdings_etf_daily WHERE etf=?",
            (args.etf,),
        ).fetchone()
        if not latest or not latest["d"]:
            print(f"no data for {args.etf}", file=sys.stderr)
            return 1
        rows = conn.execute(
            "SELECT data_date,etf,code,kind,name,shares,weight_pct"
            " FROM holdings_etf_daily WHERE etf=? AND data_date=?"
            " ORDER BY weight_pct DESC",
            (args.etf, latest["d"]),
        ).fetchall()
    result = [dict(r) for r in rows]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not result:
            print(f"no holdings for {args.etf}")
            return 1
        print(f"{args.etf} @ {result[0]['data_date']} ({len(result)} holdings)")
        for r in result[:20]:
            print(f"  {r['code']:<10} {(r['name'] or ''):<16} {r['weight_pct']:>6.2f}%  {int(r['shares'] or 0):>12}")
        if len(result) > 20:
            print(f"  ... {len(result)-20} more")
    conn.close()
    return 0


# ── query: fund ───────────────────────────────────────────────────────

def cmd_query_fund(args: argparse.Namespace) -> int:
    conn = _connect()
    params: list = [f"%{args.name}%"]
    where = "fund_name LIKE ?"
    if args.ym:
        where += " AND ym=?"
        params.append(args.ym)
    rows = conn.execute(
        f"SELECT ym,fund_name,rank,code,name,amount,pct"
        f" FROM holdings_fund_monthly WHERE {where}"
        f" ORDER BY ym DESC, fund_name, rank",
        params,
    ).fetchall()
    result = [dict(r) for r in rows]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not result:
            print("no data")
            return 1
        last_key = None
        for r in result:
            key = (r["ym"], r["fund_name"])
            if key != last_key:
                print(f"\n[{r['ym']}] {r['fund_name']}")
                last_key = key
            print(f"  #{r['rank']:>2} {r['code'] or '-':<8} {r['name'] or '-':<16} {r['pct']:>6.2f}%")
    conn.close()
    return 0


# ── query: consensus ──────────────────────────────────────────────────

def cmd_query_consensus(args: argparse.Namespace) -> int:
    """某股票被多少 ETF/基金持有 + 合計權重 + 主要持有者列表。"""
    conn = _connect()
    date_dash = _ymd_to_dash(args.date) if args.date else None

    if date_dash:
        etf_date = date_dash
    else:
        r = conn.execute(
            "SELECT MAX(data_date) AS d FROM holdings_etf_daily WHERE code=?",
            (args.code,),
        ).fetchone()
        etf_date = r["d"] if r and r["d"] else None

    etf_rows = []
    if etf_date:
        etf_rows = [dict(r) for r in conn.execute(
            "SELECT etf,name,weight_pct,shares FROM holdings_etf_daily"
            " WHERE code=? AND data_date=? ORDER BY weight_pct DESC",
            (args.code, etf_date),
        ).fetchall()]

    latest_ym = conn.execute(
        "SELECT MAX(ym) AS m FROM holdings_fund_monthly WHERE code=?",
        (args.code,),
    ).fetchone()
    ym = latest_ym["m"] if latest_ym else None
    fund_rows = []
    if ym:
        fund_rows = [dict(r) for r in conn.execute(
            "SELECT fund_name,rank,pct FROM holdings_fund_monthly"
            " WHERE code=? AND ym=? ORDER BY pct DESC",
            (args.code, ym),
        ).fetchall()]

    payload = {
        "code": args.code,
        "etf_date": etf_date,
        "etf_holders": etf_rows,
        "etf_count": len(etf_rows),
        "fund_ym": ym,
        "fund_holders": fund_rows,
        "fund_count": len(fund_rows),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"=== consensus for {args.code} ===")
        if etf_rows:
            print(f"\nETF @ {etf_date} ({len(etf_rows)} holders)")
            for r in etf_rows:
                print(f"  {r['etf']:<8} {r['weight_pct']:>6.2f}%  {int(r['shares'] or 0):>12}")
        else:
            print("no ETF data")
        if fund_rows:
            print(f"\nFund @ {ym} ({len(fund_rows)} holders; Top 10 only)")
            for r in fund_rows:
                print(f"  #{r['rank']:>2} {r['pct']:>6.2f}%  {r['fund_name']}")
        else:
            print("no fund data")
    conn.close()
    return 0


# ── query: diff ───────────────────────────────────────────────────────

def cmd_query_diff(args: argparse.Namespace) -> int:
    """同 ETF 兩日持股差異（shares 變動、新增/移除）。"""
    conn = _connect()
    d1 = _ymd_to_dash(args.from_date)
    d2 = _ymd_to_dash(args.to_date)

    a = {(r["code"], r["kind"]): dict(r) for r in conn.execute(
        "SELECT code,kind,name,shares,weight_pct FROM holdings_etf_daily"
        " WHERE etf=? AND data_date=?", (args.etf, d1)).fetchall()}
    b = {(r["code"], r["kind"]): dict(r) for r in conn.execute(
        "SELECT code,kind,name,shares,weight_pct FROM holdings_etf_daily"
        " WHERE etf=? AND data_date=?", (args.etf, d2)).fetchall()}

    if not a or not b:
        print(f"missing snapshot: {d1}={len(a)} rows, {d2}={len(b)} rows", file=sys.stderr)
        return 1

    added = sorted(set(b) - set(a), key=lambda k: -(b[k]["weight_pct"] or 0))
    removed = sorted(set(a) - set(b), key=lambda k: -(a[k]["weight_pct"] or 0))
    changed = []
    for k in set(a) & set(b):
        da, db = (a[k]["shares"] or 0), (b[k]["shares"] or 0)
        if da != db:
            changed.append({
                "code": k[0], "kind": k[1], "name": a[k]["name"],
                "shares_from": da, "shares_to": db,
                "pct_from": a[k]["weight_pct"], "pct_to": b[k]["weight_pct"],
                "delta_shares": db - da,
            })
    changed.sort(key=lambda x: abs(x["delta_shares"] or 0), reverse=True)

    payload = {
        "etf": args.etf, "from": d1, "to": d2,
        "added": [b[k] | {"code": k[0], "kind": k[1]} for k in added],
        "removed": [a[k] | {"code": k[0], "kind": k[1]} for k in removed],
        "changed": changed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"=== {args.etf} diff {d1} → {d2} ===")
        print(f"\n+ Added ({len(added)})")
        for k in added[:20]:
            r = b[k]
            print(f"  {k[0]:<10} {(r['name'] or ''):<16} {r['weight_pct']:>6.2f}%")
        print(f"\n- Removed ({len(removed)})")
        for k in removed[:20]:
            r = a[k]
            print(f"  {k[0]:<10} {(r['name'] or ''):<16} {r['weight_pct']:>6.2f}%")
        print(f"\n~ Changed ({len(changed)})")
        for r in changed[:20]:
            arrow = "↑" if r["delta_shares"] > 0 else "↓"
            print(f"  {r['code']:<10} {(r['name'] or ''):<16} "
                  f"{arrow} {abs(r['delta_shares']):>12} shares  "
                  f"({r['pct_from'] or 0:.2f}% → {r['pct_to'] or 0:.2f}%)")
    conn.close()
    return 0


# ── stats ─────────────────────────────────────────────────────────────

def cmd_stats(args: argparse.Namespace) -> int:
    conn = _connect()
    out: dict = {"db_path": str(DB_PATH), "tables": {}}

    for tbl, dcol in [
        ("holdings_fund_monthly", "ym"),
        ("holdings_fund_quarterly", "yq"),
        ("holdings_etf_daily", "data_date"),
        ("etf_meta_daily", "data_date"),
    ]:
        r = conn.execute(
            f"SELECT COUNT(*) AS n, MIN({dcol}) AS mn, MAX({dcol}) AS mx FROM {tbl}"
        ).fetchone()
        out["tables"][tbl] = {
            "rows": r["n"], "min_period": r["mn"], "max_period": r["mx"],
        }

    # 每 ETF 的日期覆蓋
    etf_cov = conn.execute(
        "SELECT etf, COUNT(DISTINCT data_date) AS days,"
        " MIN(data_date) AS min_d, MAX(data_date) AS max_d"
        " FROM holdings_etf_daily GROUP BY etf ORDER BY etf"
    ).fetchall()
    out["etf_coverage"] = [dict(r) for r in etf_cov]

    # ingest 最近 10 筆
    recent = conn.execute(
        "SELECT source,target,row_count,ok,error,ingested_at FROM ingest_log"
        " ORDER BY id DESC LIMIT 10"
    ).fetchall()
    out["recent_ingest"] = [dict(r) for r in recent]

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"DB: {DB_PATH}")
        print("\n== tables ==")
        for t, v in out["tables"].items():
            print(f"  {t:<28} {v['rows']:>6} rows  [{v['min_period']} → {v['max_period']}]")
        print("\n== ETF daily coverage ==")
        for r in out["etf_coverage"]:
            print(f"  {r['etf']:<8} {r['days']:>3} days  [{r['min_d']} → {r['max_d']}]")
        print("\n== recent ingest ==")
        for r in out["recent_ingest"]:
            flag = "✔" if r["ok"] else "✘"
            print(f"  {flag} {r['ingested_at']} {r['source']:<13} {r['target']:<40} {r['row_count']:>4} rows"
                  + (f"  err={r['error'][:60]}" if r["error"] else ""))
    conn.close()
    return 0


# ── backfill ──────────────────────────────────────────────────────────

def _month_range(ym_from: str, ym_to: str) -> list[str]:
    """'202504' → '202603' inclusive。"""
    y, m = int(ym_from[:4]), int(ym_from[4:])
    y_end, m_end = int(ym_to[:4]), int(ym_to[4:])
    out = []
    while (y, m) <= (y_end, m_end):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _weekday_range(ymd_from: str, ymd_to: str) -> list[str]:
    """'20260301' → '20260417' 排除週末（國定假日交由 API 回 null 處理）。"""
    from datetime import date, timedelta
    d = date(int(ymd_from[:4]), int(ymd_from[4:6]), int(ymd_from[6:8]))
    d_end = date(int(ymd_to[:4]), int(ymd_to[4:6]), int(ymd_to[6:8]))
    out = []
    while d <= d_end:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def cmd_backfill_sitca_monthly(args: argparse.Namespace) -> int:
    months = _month_range(args.ym_from, args.ym_to)
    print(f"▶ backfill sitca-monthly: {len(months)} months "
          f"[{months[0]} → {months[-1]}] class={args.class_code or 'ALL'} "
          f"comid={args.comid or '-'}", file=sys.stderr)
    conn = _connect()
    ok_count = err_count = total_rows = 0
    for i, m in enumerate(months, 1):
        target = f"sitca-monthly:{m}:{args.class_code or 'ALL'}:{args.comid or '-'}"
        try:
            n = _ingest_sitca_monthly(conn, m, args.class_code, args.comid)
            _log(conn, "managerwatch", target, n, True)
            conn.commit()
            ok_count += 1
            total_rows += n
            print(f"  [{i:>2}/{len(months)}] ✔ {m} → {n} rows", file=sys.stderr)
        except Exception as e:
            _log(conn, "managerwatch", target, 0, False, str(e))
            conn.commit()
            err_count += 1
            print(f"  [{i:>2}/{len(months)}] ✘ {m}: {e}", file=sys.stderr)
    conn.close()
    print(f"✔ done: {ok_count}/{len(months)} ok, {err_count} errors, "
          f"{total_rows} rows total", file=sys.stderr)
    return 0 if err_count == 0 else 1


def cmd_backfill_etf_daily(args: argparse.Namespace) -> int:
    days = _weekday_range(args.ymd_from, args.ymd_to)
    codes = ETF_CODES if args.all else [args.code]
    total = len(days) * len(codes)
    print(f"▶ backfill etf-daily: {len(codes)} ETFs × {len(days)} weekdays "
          f"= {total} calls [{days[0]} → {days[-1]}]", file=sys.stderr)
    conn = _connect()
    ok_count = err_count = total_rows = 0
    i = 0
    for d in days:
        for code in codes:
            i += 1
            target = f"etfdaily:{code}:{d}"
            try:
                n = _ingest_etf_daily_one(conn, code, d)
                _log(conn, "etfdaily", target, n, True)
                conn.commit()
                ok_count += 1
                total_rows += n
                if n == 0:
                    # 非交易日 / ETF 尚未掛牌 / issuer 無資料 — 非致命
                    print(f"  [{i:>3}/{total}] ◌ {code} {d} → 0 rows", file=sys.stderr)
                else:
                    print(f"  [{i:>3}/{total}] ✔ {code} {d} → {n}", file=sys.stderr)
            except Exception as e:
                _log(conn, "etfdaily", target, 0, False, str(e))
                conn.commit()
                err_count += 1
                msg = str(e).splitlines()[0][:80]
                print(f"  [{i:>3}/{total}] ✘ {code} {d}: {msg}", file=sys.stderr)
    conn.close()
    print(f"✔ done: {ok_count}/{total} ok, {err_count} errors, "
          f"{total_rows} holdings rows", file=sys.stderr)
    return 0 if err_count == 0 else 1


def cmd_backfill_retry(args: argparse.Namespace) -> int:
    """從 ingest_log 抓 ok=0 的 target 重跑一次。"""
    conn = _connect()
    # 每個 target 取最新一筆（有可能先失敗後成功，要跳過已成功的）
    rows = conn.execute(
        "SELECT target, source FROM ingest_log l1"
        " WHERE ok=0 AND id=(SELECT MAX(id) FROM ingest_log l2 WHERE l2.target=l1.target)"
    ).fetchall()
    if not rows:
        print("✔ no failed ingests to retry", file=sys.stderr)
        conn.close()
        return 0
    print(f"▶ retry {len(rows)} failed ingests", file=sys.stderr)
    ok_count = err_count = 0
    for i, r in enumerate(rows, 1):
        target, source = r["target"], r["source"]
        parts = target.split(":")
        try:
            if source == "managerwatch" and parts[0] == "sitca-monthly":
                _, month, cls, comid = parts[0], parts[1], parts[2], parts[3]
                cls = None if cls == "ALL" else cls
                comid = None if comid == "-" else comid
                n = _ingest_sitca_monthly(conn, month, cls, comid)
            elif source == "managerwatch" and parts[0] == "sitca-quarterly":
                _, q, cls, comid = parts[0], parts[1], parts[2], parts[3]
                cls = None if cls == "ALL" else cls
                comid = None if comid == "-" else comid
                n = _ingest_sitca_quarterly(conn, q, cls, comid)
            elif source == "etfdaily":
                _, code, date_ymd = parts[0], parts[1], parts[2]
                date_ymd = None if date_ymd == "auto" else date_ymd
                n = _ingest_etf_daily_one(conn, code, date_ymd)
            else:
                raise RuntimeError(f"unknown target format: {target}")
            _log(conn, source, target, n, True)
            conn.commit()
            ok_count += 1
            print(f"  [{i:>2}/{len(rows)}] ✔ {target} → {n} rows", file=sys.stderr)
        except Exception as e:
            _log(conn, source, target, 0, False, str(e))
            conn.commit()
            err_count += 1
            msg = str(e).splitlines()[0][:80]
            print(f"  [{i:>2}/{len(rows)}] ✘ {target}: {msg}", file=sys.stderr)
    conn.close()
    print(f"✔ retry done: {ok_count} ok, {err_count} still failing",
          file=sys.stderr)
    return 0 if err_count == 0 else 1


# ── migrate ───────────────────────────────────────────────────────────

def cmd_migrate_kind(args: argparse.Namespace) -> int:
    """把 holdings_etf_daily 裡的中文 kind 標籤正規化成英文。
    野村 00980A / 安聯 00993A 歷史資料使用 '股票' / '期貨'，需要跟其他 issuer
    對齊到 'stock' / 'future'。"""
    conn = _connect()
    print("=== before migration ===", file=sys.stderr)
    for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM holdings_etf_daily GROUP BY kind ORDER BY n DESC"
    ).fetchall():
        print(f"  {r['kind']!r:12} {r['n']:>6}", file=sys.stderr)

    total = 0
    # 用 UPDATE OR REPLACE 避免 PK 衝突（實測 00980A 無 overlap，但保險起見）
    for src, dst in KIND_MAP.items():
        if src == dst:
            continue
        cur = conn.execute(
            "UPDATE OR REPLACE holdings_etf_daily SET kind=? WHERE kind=?",
            (dst, src),
        )
        if cur.rowcount:
            print(f"  {src!r} → {dst!r}: {cur.rowcount} rows", file=sys.stderr)
            total += cur.rowcount
    conn.commit()

    print(f"\n=== after migration ({total} rows updated) ===", file=sys.stderr)
    for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM holdings_etf_daily GROUP BY kind ORDER BY n DESC"
    ).fetchall():
        print(f"  {r['kind']!r:12} {r['n']:>6}", file=sys.stderr)
    conn.close()
    return 0


# ── util ──────────────────────────────────────────────────────────────

def _last_weekday_dash() -> str:
    from datetime import date, timedelta
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _ymd_to_dash(ymd: str) -> str:
    """'20260417' → '2026-04-17'；already-dashed passthrough。"""
    if "-" in ymd:
        return ymd
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _normalize_date(s: str | None) -> str:
    """各家 etfdaily data_date 格式不一（'2026/04/17' / '2026-04-17' /
    '20260417' / '2026-04-16T00:00:00' / ''），統一成 'YYYY-MM-DD'。"""
    if not s:
        return ""
    s = s.strip().split("T")[0]
    s = s.replace("/", "-")
    # '20260417' → '2026-04-17'
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # 'YYYY-M-D' → 'YYYY-MM-DD'
    parts = s.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    return s


# ── main ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SQLite datastore for managerwatch + etfdaily")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建表").set_defaults(func=cmd_init)

    # ingest
    ingest = sub.add_parser("ingest", help="ingest subcommands")
    ingest_sub = ingest.add_subparsers(dest="ingest_cmd", required=True)

    sm = ingest_sub.add_parser("sitca-monthly", help="SITCA 月報 Top 10")
    sm.add_argument("--month", required=True, help="YYYYMM e.g. 202603")
    sm.add_argument("--class", dest="class_code", help="e.g. AL11")
    sm.add_argument("--comid", help="e.g. A0009 (統一)")
    sm.set_defaults(func=cmd_ingest_sitca_monthly)

    sq = ingest_sub.add_parser("sitca-quarterly", help="SITCA 季報 ≥1%")
    sq.add_argument("--quarter", required=True, help="YYYYMM e.g. 202603")
    sq.add_argument("--class", dest="class_code")
    sq.add_argument("--comid")
    sq.set_defaults(func=cmd_ingest_sitca_quarterly)

    mm = ingest_sub.add_parser("mops-monthly", help="MOPS 主動 ETF 基金月報 Top 5（補 SITCA 歷史期洞）")
    mm.add_argument("--month", required=True, help="YYYYMM e.g. 202602")
    mm.set_defaults(func=cmd_ingest_mops_monthly)

    ed = ingest_sub.add_parser("etf-daily", help="主動 ETF 當日持股")
    ed.add_argument("--date", help="YYYYMMDD（預設最近交易日）")
    g = ed.add_mutually_exclusive_group(required=True)
    g.add_argument("--code", help="單檔 ETF code")
    g.add_argument("--all", action="store_true", help="6 檔一次跑")
    ed.set_defaults(func=cmd_ingest_etf_daily)

    ea = ingest_sub.add_parser("all", help="便利：6 ETF daily")
    ea.add_argument("--date")
    ea.set_defaults(func=cmd_ingest_all)

    # query
    q = sub.add_parser("query", help="query subcommands")
    qsub = q.add_subparsers(dest="query_cmd", required=True)

    qh = qsub.add_parser("holdings", help="某 ETF 當日持股")
    qh.add_argument("--etf", required=True)
    qh.add_argument("--date", help="YYYYMMDD（預設最新）")
    qh.add_argument("--json", action="store_true")
    qh.set_defaults(func=cmd_query_holdings)

    qf = qsub.add_parser("fund", help="基金月報 Top 10")
    qf.add_argument("--name", required=True, help="模糊 match fund_name")
    qf.add_argument("--ym", help="YYYYMM")
    qf.add_argument("--json", action="store_true")
    qf.set_defaults(func=cmd_query_fund)

    qc = qsub.add_parser("consensus", help="某股票被多少 ETF/基金持有")
    qc.add_argument("--code", required=True, help="e.g. 2330")
    qc.add_argument("--date", help="YYYYMMDD")
    qc.add_argument("--json", action="store_true")
    qc.set_defaults(func=cmd_query_consensus)

    qd = qsub.add_parser("diff", help="同 ETF 跨日持股差異")
    qd.add_argument("--etf", required=True)
    qd.add_argument("--from", dest="from_date", required=True, help="YYYYMMDD")
    qd.add_argument("--to", dest="to_date", required=True, help="YYYYMMDD")
    qd.add_argument("--json", action="store_true")
    qd.set_defaults(func=cmd_query_diff)

    st = sub.add_parser("stats", help="coverage / 列數 / 日期範圍")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    # backfill
    bf = sub.add_parser("backfill", help="批次 ingest（月範圍 / 日範圍 / retry）")
    bfsub = bf.add_subparsers(dest="backfill_cmd", required=True)

    bfm = bfsub.add_parser("sitca-monthly", help="批次月報")
    bfm.add_argument("--from", dest="ym_from", required=True, help="YYYYMM")
    bfm.add_argument("--to", dest="ym_to", required=True, help="YYYYMM")
    bfm.add_argument("--class", dest="class_code")
    bfm.add_argument("--comid")
    bfm.set_defaults(func=cmd_backfill_sitca_monthly)

    bfmm = bfsub.add_parser("mops-monthly", help="批次 MOPS 主動 ETF 月報 Top 5")
    bfmm.add_argument("--from", dest="ym_from", required=True, help="YYYYMM")
    bfmm.add_argument("--to", dest="ym_to", required=True, help="YYYYMM")
    bfmm.set_defaults(func=cmd_backfill_mops_monthly)

    bfe = bfsub.add_parser("etf-daily", help="批次 ETF daily")
    bfe.add_argument("--from", dest="ymd_from", required=True, help="YYYYMMDD")
    bfe.add_argument("--to", dest="ymd_to", required=True, help="YYYYMMDD")
    g2 = bfe.add_mutually_exclusive_group(required=True)
    g2.add_argument("--code")
    g2.add_argument("--all", action="store_true")
    bfe.set_defaults(func=cmd_backfill_etf_daily)

    bfr = bfsub.add_parser("retry", help="重跑 ingest_log 裡 ok=0 的 target")
    bfr.set_defaults(func=cmd_backfill_retry)

    # migrate（schema-level data clean-up）
    mg = sub.add_parser("migrate", help="歷史資料正規化（schema drift 修復）")
    mgsub = mg.add_subparsers(dest="migrate_cmd", required=True)
    mgk = mgsub.add_parser("kind", help="holdings_etf_daily.kind 中→英正規化")
    mgk.set_defaults(func=cmd_migrate_kind)

    # whitelist（active_etf_* view 過濾表）
    wl = sub.add_parser("whitelist", help="主動式 ETF 基金白名單（active_etf_* view 過濾）")
    wlsub = wl.add_subparsers(dest="whitelist_cmd", required=True)

    wll = wlsub.add_parser("list", help="列出白名單")
    wll.add_argument("--json", action="store_true")
    wll.set_defaults(func=cmd_whitelist_list)

    wla = wlsub.add_parser("add", help="手動新增")
    wla.add_argument("--fund-short", required=True, help="fund_name 前綴（不含備註）")
    wla.add_argument("--etf-code", help="e.g. 00981A")
    wla.add_argument("--issuer", help="投信中文名")
    wla.add_argument("--note")
    wla.set_defaults(func=cmd_whitelist_add)

    wlr = wlsub.add_parser("remove", help="移除一條")
    wlr.add_argument("--fund-short", required=True)
    wlr.set_defaults(func=cmd_whitelist_remove)

    wlrs = wlsub.add_parser("reseed", help="重灌預設 13 檔種子（預設 idempotent，加 --force-codes 覆蓋既有 etf_code）")
    wlrs.add_argument("--force-codes", action="store_true",
                      help="用 INSERT OR REPLACE 覆蓋既有 row 的 etf_code/issuer")
    wlrs.set_defaults(func=cmd_whitelist_reseed)

    wlc = wlsub.add_parser("coverage", help="raw vs active_etf view 覆蓋對比")
    wlc.add_argument("--json", action="store_true")
    wlc.set_defaults(func=cmd_whitelist_coverage)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
