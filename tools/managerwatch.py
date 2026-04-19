#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
managerwatch — CLI for SITCA monthly/quarterly holdings + active-ETF cross-reference.

靈感：2026-04-18 Threads @winwin17888/DXQJOQokrEW 轉 JOY 88 的 dashboard。
研究目標：同經理人的基金（月揭露 Top 10）vs ETF（日揭露）策略分裂 —— 法規造成的制度漏洞。

**Phase 1（本階段）**：SITCA IN2629（月報 Top 10）+ IN2630（季報 ≥1%）primary source 破解。

Subcommands:
  companies                      列 SITCA 投信代碼 + 名稱
  classes                        列基金分類代碼（AA1 國內股票型、AL11 國內主動 ETF 股票型…）
  catalog                        本專案觀測清單（6 ETF + 13 基金 = 19 檔，JOY 88 spec）
  sitca monthly --month YYYYMM [--by class|comid] [--comid A0019] [--class AA1]
  sitca quarterly --quarter YYYYMM [--by class|comid] [--comid A0019] [--class AA1]

Phase 2+（未規劃實作）：
  ingest --all, manager, diff, consensus, signals, dna

Usage:
  ./managerwatch.py companies                                     # 投信代碼清單
  ./managerwatch.py sitca monthly --month 202603 --class AL11     # 國內主動 ETF 股票型全部
  ./managerwatch.py sitca monthly --month 202603 --comid A0019 --class AA1 --by comid
                                                                  # 統一投信台股基金全部
  ./managerwatch.py sitca quarterly --quarter 202603 --class AL11
  ./managerwatch.py catalog --json                                # 19 檔觀測清單
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SITCA_BASE = "https://www.sitca.org.tw/ROC/Industry"
UA = {"User-Agent": "Mozilla/5.0 (managerwatch-cli; +tw-active)"}

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".tmp" / "sitca"


# ── 19 檔觀測清單（JOY 88 原文 + Round 1-43 已知） ──────────────────────
# company code 是 SITCA 投信代碼（見 companies subcommand 取清單）
# 經理人欄會隨 Phase 2+ 持續補正
# SITCA 投信代碼（verified 2026-04-19 via `managerwatch companies`）：
#   A0005 元大 / A0009 統一 / A0016 群益 / A0022 復華 / A0031 貝萊德
#   A0032 野村 / A0036 安聯 / A0047 台新 / A0011 摩根 / A0037 國泰
CATALOG = [
    # 6 檔主動 ETF（JOY 88 spec）
    {"code": "00981A", "name": "統一台股增長", "company": "A0009", "manager": "陳釧瑤", "type": "etf"},
    {"code": "00988A", "name": "統一全球創新", "company": "A0009", "manager": "陳意婷", "type": "etf"},
    {"code": "00991A", "name": "復華台灣未來 50", "company": "A0022", "manager": "呂宏宇", "type": "etf"},
    {"code": "00980A", "name": "野村臺灣智慧優選", "company": "A0032", "manager": "謝文雄", "type": "etf"},
    {"code": "00993A", "name": "安聯台灣主動式", "company": "A0036", "manager": "蕭惠中", "type": "etf"},
    {"code": "00982A", "name": "群益台灣精選強棒", "company": "A0016", "manager": "<TODO>", "type": "etf"},
    # 13 檔主動基金（JOY 88 spec）
    {"code": "統一全天候", "company": "A0009", "manager": "陳意婷", "type": "fund"},
    {"code": "統一奔騰", "company": "A0009", "manager": "陳釧瑤", "type": "fund"},
    {"code": "統一黑馬", "company": "A0009", "manager": "尤文毅", "type": "fund"},
    {"code": "統一中小", "company": "A0009", "manager": "莊承憲", "type": "fund"},
    {"code": "統一大中華中小", "company": "A0009", "manager": "林叡廷", "type": "fund"},
    {"code": "復華高成長", "company": "A0022", "manager": "呂宏宇", "type": "fund"},
    {"code": "復華全方位", "company": "A0022", "manager": "呂宏宇", "type": "fund"},
    {"code": "野村優質", "company": "A0032", "manager": "陳茹婷", "type": "fund"},
    {"code": "野村高科技", "company": "A0032", "manager": "謝文雄", "type": "fund"},
    {"code": "安聯台灣大壩", "company": "A0036", "manager": "蕭惠中", "type": "fund"},
    {"code": "安聯台灣科技", "company": "A0036", "manager": "周敬烈", "type": "fund"},
    {"code": "台新主流", "company": "A0047", "manager": "黃千雲", "type": "fund"},
    {"code": "元大新主流", "company": "A0005", "manager": "葉信良", "type": "fund"},
]


# ── HTTP helpers ──────────────────────────────────────────

def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _post(url: str, data: dict[str, str], cookie_jar: dict | None = None, timeout: int = 60) -> tuple[bytes, dict]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {**UA, "Content-Type": "application/x-www-form-urlencoded"}
    if cookie_jar:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        # grab any Set-Cookie
        new_cookies = dict(cookie_jar or {})
        for sc in resp.headers.get_all("Set-Cookie") or []:
            kv = sc.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                new_cookies[k.strip()] = v.strip()
    return raw, new_cookies


# ── ASP.NET form helpers ──────────────────────────────────

HIDDEN_RE = re.compile(r'<input[^>]+type="hidden"[^>]*>', re.I)
NAME_VAL_RE = re.compile(r'name="([^"]+)"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="([^"]+)"', re.I)


def extract_aspnet_state(html: str) -> dict[str, str]:
    """抽 __VIEWSTATE / __EVENTVALIDATION / __VIEWSTATEGENERATOR 等 hidden field"""
    out: dict[str, str] = {}
    for m in HIDDEN_RE.finditer(html):
        tag = m.group(0)
        nm = re.search(r'name="([^"]+)"', tag)
        vm = re.search(r'value="([^"]*)"', tag)
        if nm:
            out[nm.group(1)] = html_mod.unescape(vm.group(1)) if vm else ""
    return out


OPTION_RE = re.compile(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', re.I)


def extract_select_options(html: str, name: str) -> list[tuple[str, str]]:
    """回傳 select 下所有 option (value, text)"""
    # Find the select block
    m = re.search(rf'<select[^>]*name="[^"]*{re.escape(name)}[^"]*"[^>]*>(.*?)</select>', html, re.S | re.I)
    if not m:
        return []
    return [(v.strip(), t.strip()) for v, t in OPTION_RE.findall(m.group(1))]


# ── SITCA fetchers ────────────────────────────────────────

def _get_initial(aspx: str) -> tuple[str, dict]:
    """第一次 GET 拿 hidden tokens + cookie"""
    url = f"{SITCA_BASE}/{aspx}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        cookies: dict[str, str] = {}
        for sc in resp.headers.get_all("Set-Cookie") or []:
            kv = sc.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                cookies[k.strip()] = v.strip()
    return raw.decode("utf-8", errors="replace"), cookies


def sitca_fetch(aspx: str, ym: str, comid: str | None, fund_class: str | None, by: str) -> str:
    """
    aspx: IN2629.aspx (月) 或 IN2630.aspx (季)
    ym:   '202603' 等
    by:   'class' 用類型條件 / 'comid' 用公司條件
    """
    if by not in ("class", "comid"):
        raise ValueError("by 必須是 class 或 comid")
    html, cookies = _get_initial(aspx)
    state = extract_aspnet_state(html)
    # 必要欄位
    post = {
        "__VIEWSTATE": state.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": state.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": state.get("__EVENTVALIDATION", ""),
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "ctl00$ContentPlaceHolder1$rdo1": "rbClass" if by == "class" else "rbComid",
        "ctl00$ContentPlaceHolder1$ddlQ_YM": ym,
        "ctl00$ContentPlaceHolder1$ddlQ_Comid": comid or "A0001",
        "ctl00$ContentPlaceHolder1$ddlQ_Class": fund_class or "AA1",
        "ctl00$ContentPlaceHolder1$BtnQuery": "查詢",
    }
    raw, _ = _post(f"{SITCA_BASE}/{aspx}", post, cookies)
    return raw.decode("utf-8", errors="replace")


# ── Table parser ──────────────────────────────────────────

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*class='?DT(?:even|odd|subtotal|Header)'?[^>]*>(.*?)</td>", re.S | re.I)
ROWSPAN_RE = re.compile(r"rowspan=['\"]?(\d+)", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _strip(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = TAG_RE.sub("", s)
    return html_mod.unescape(s).strip()


def parse_holdings(html: str, has_rank: bool = True) -> list[dict]:
    """
    SITCA holdings table 結構：
      IN2629（月報 Top10）：10 欄 = [基金名稱, 名次, 標的種類, 標的代號, 標的名稱, 金額, 擔保機構, 次順位, 受益權單位數, 比例%]
      IN2630（季報 ≥1%）：9 欄 = 去掉「名次」欄（SITCA 註明名次乙欄係空白）
      每檔基金第一 row 有 rowspan=N 的基金名稱，後續 N-1 rows 少了基金名稱欄
      最後一列 DTsubtotal = 合計
    """
    rows: list[dict] = []
    current_fund: str | None = None
    remaining_rows = 0
    # data 欄數（不含基金名稱；月報 9、季報 8）
    data_col_count = 9 if has_rank else 8

    for rm in ROW_RE.finditer(html):
        trhtml = rm.group(1)
        if "DTHeader" in trhtml or "DTsubtotal" in trhtml:
            continue
        cells_raw = re.findall(r"<td[^>]*>(.*?)</td>", trhtml, re.S | re.I)
        if not cells_raw:
            continue
        rs_match = ROWSPAN_RE.search(trhtml)
        if rs_match and ("DTeven" in trhtml or "DTodd" in trhtml) and len(cells_raw) >= data_col_count + 1:
            remaining_rows = int(rs_match.group(1))
            current_fund = _strip(cells_raw[0])
            data_cells = cells_raw[1:1 + data_col_count]
        elif remaining_rows > 0 and len(cells_raw) >= data_col_count:
            data_cells = cells_raw[:data_col_count]
        else:
            continue

        try:
            if has_rank:
                rank_s = _strip(data_cells[0])
                rest = data_cells[1:]
            else:
                rank_s = ""
                rest = data_cells
            target_type = _strip(rest[0])
            code = _strip(rest[1])
            name = _strip(rest[2])
            amount = _strip(rest[3]).replace(",", "")
            guarantor = _strip(rest[4])
            subordinate = _strip(rest[5])
            units = _strip(rest[6]).replace(",", "")
            pct = _strip(rest[7])
        except IndexError:
            continue

        rows.append({
            "fund": current_fund,
            "rank": int(rank_s) if rank_s.isdigit() else (rank_s or None),
            "target_type": target_type,
            "target_code": code,
            "target_name": name,
            "amount": int(amount) if amount.isdigit() else amount,
            "guarantor": guarantor,
            "subordinate": subordinate,
            "units": int(units) if units.isdigit() else units,
            "pct": float(pct) if re.match(r"^-?\d+(?:\.\d+)?$", pct) else pct,
        })
        remaining_rows -= 1

    return rows


# ── Commands ──────────────────────────────────────────────

def cmd_companies(args) -> int:
    html, _ = _get_initial("IN2629.aspx")
    opts = extract_select_options(html, "ddlQ_Comid")
    # skip the second panel's dup (ddlQ_Comid1); use ddlQ_Comid which shows active companies
    if args.json:
        json.dump([{"code": v, "name": t} for v, t in opts], sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    for v, t in opts:
        print(f"{v}  {t}")
    print(f"\n合計 {len(opts)} 家（SITCA 現役投信）", file=sys.stderr)
    return 0


def cmd_classes(args) -> int:
    html, _ = _get_initial("IN2629.aspx")
    opts = extract_select_options(html, "ddlQ_Class")
    if args.json:
        json.dump([{"code": v, "name": t} for v, t in opts], sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    for v, t in opts:
        print(f"{v}  {t}")
    print(f"\n合計 {len(opts)} 類", file=sys.stderr)
    return 0


def cmd_catalog(args) -> int:
    if args.json:
        json.dump(CATALOG, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    print(f"{'代號/名稱':<20} {'投信':<8} {'類型':<6} {'經理人':<12}")
    print("-" * 60)
    for r in CATALOG:
        pad = r["code"] + " " * max(0, 20 - sum(2 if ord(c) > 127 else 1 for c in r["code"]))
        print(f"{pad}{r['company']:<8} {r['type']:<6} {r['manager']:<12}")
    print(f"\n合計 {len(CATALOG)} 檔（6 ETF + 13 fund，JOY 88 spec + Round 1-43）", file=sys.stderr)
    return 0


def _cmd_sitca(args, aspx: str, date_field: str) -> int:
    ym = getattr(args, date_field)
    html = sitca_fetch(aspx, ym, comid=args.comid, fund_class=getattr(args, "class"), by=args.by)
    # optional raw dump
    if args.raw_html:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = CACHE_DIR / f"{aspx.replace('.aspx', '')}-{ym}-{args.by}-{args.comid or ''}-{getattr(args, 'class') or ''}.html"
        p.write_text(html, encoding="utf-8")
        print(f"(raw HTML saved → {p})", file=sys.stderr)
    has_rank = aspx.startswith("IN2629")  # 月報有名次、季報無
    rows = parse_holdings(html, has_rank=has_rank)
    if args.json:
        json.dump({"aspx": aspx, "period": ym, "by": args.by,
                   "comid": args.comid, "class": getattr(args, "class"),
                   "rows": rows}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if not rows:
        print("(無持股資料；可確認 --class/--comid 條件、或用 --raw-html 存 HTML 檢查)", file=sys.stderr)
        return 1
    print(f"[{aspx}] 期間={ym} by={args.by} — {len(rows)} 條持股")
    cur = None
    for r in rows:
        if r["fund"] != cur:
            print(f"\n◆ {r['fund']}")
            cur = r["fund"]
        tcode = str(r["target_code"])
        tname = str(r["target_name"])
        pad = tname + " " * max(0, 16 - sum(2 if ord(c) > 127 else 1 for c in tname))
        rank_s = str(r["rank"]) if r["rank"] is not None else "-"
        print(f"  {rank_s:>3}  {tcode:<10} {pad} "
              f"{r['amount']!s:>15}  {r['pct']!s:>6}%")
    return 0


def cmd_sitca_monthly(args) -> int:
    return _cmd_sitca(args, "IN2629.aspx", "month")


def cmd_sitca_quarterly(args) -> int:
    return _cmd_sitca(args, "IN2630.aspx", "quarter")


# ── Main ──────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(prog="managerwatch", description="SITCA + active-ETF cross-reference CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("companies", help="SITCA 投信代碼清單")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_companies)

    sp = sub.add_parser("classes", help="SITCA 基金分類代碼清單")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_classes)

    sp = sub.add_parser("catalog", help="本專案 19 檔觀測清單")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_catalog)

    sitca = sub.add_parser("sitca", help="SITCA 月報/季報")
    sitca_sub = sitca.add_subparsers(dest="sitca_cmd", required=True)

    for cmd_name, handler, dateflag in (
        ("monthly", cmd_sitca_monthly, "month"),
        ("quarterly", cmd_sitca_quarterly, "quarter"),
    ):
        ssp = sitca_sub.add_parser(cmd_name, help=f"基金{'月' if cmd_name == 'monthly' else '季'}報")
        ssp.add_argument(f"--{dateflag}", required=True, help="YYYYMM（季用季末月，如 202603）")
        ssp.add_argument("--by", choices=["class", "comid"], default="class",
                         help="查詢方式：class 依類型、comid 依公司（預設 class）")
        ssp.add_argument("--comid", help="投信代碼 A0019 等（by=comid 必填）")
        ssp.add_argument("--class", dest="class", help="基金分類 AA1/AL11 等（by=class 必填，by=comid 可選）")
        ssp.add_argument("--json", action="store_true")
        ssp.add_argument("--raw-html", action="store_true", help="把原始 HTML dump 到 .tmp/sitca/")
        ssp.set_defaults(func=handler)

    args = p.parse_args()
    try:
        return args.func(args)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
