#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
mopsetf — MOPS 主動式 ETF 揭露 pipeline（歷史期可查）。

破解日期：2026-04-19（Round 47）
問題脈絡：SITCA IN2629/IN2630 對非最新期 server-side filter 全失效
         （見 wiki/mechanisms/sitca-history-filter-bug），歷史月報路斷。
破解方向：MOPS `t78sb39_q3`（國內成分主動式 ETF → 每月持股前五大個股）
         過 POST body 帶 year（民國紀年）+ month 實際 filter 得動。
差異：SITCA 月報 Top 10；MOPS Top 5（淺但能填歷史）。

Subcommands:
  monthly --month YYYYMM [--json]    每月持股前五大（全部主動 ETF 基金）
  navhistory --code <fund>           （待實作）基金每日淨資產價值
  industry --week YYYYMMDD           （待實作）基金每週投資產業類股比例
  quarterly --quarter YYYYMM         （待實作）基金每季持股明細

Output（JSON）：
  {
    "ym": "202602",
    "funds": [
      {
        "fund_name": "統一台股增長主動式ETF基金",         # 已 normalize（對齊 whitelist short）
        "fund_name_raw": "統一台股增長主動式ETF證券投資信託基金",
        "comid": "A0009",
        "company_name": "統一投信",
        "top5": [
          {"rank": 1, "code": "2330", "name": "台積電", "pct": 9.14},
          ...
        ]
      },
      ...
    ]
  }
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MOPS_BASE = "https://mopsov.twse.com.tw/mops/web"
UA = {"User-Agent": "Mozilla/5.0 (mopsetf-cli; +tw-active)"}

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".tmp" / "mops"


# ── HTTP ──────────────────────────────────────────────────

def _post(url: str, data: dict[str, str], timeout: int = 60) -> str:
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {**UA, "Content-Type": "application/x-www-form-urlencoded",
               "Referer": f"{MOPS_BASE}/t78sb39_new"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


# ── Date helpers ──────────────────────────────────────────

def ym_to_roc(ym: str) -> tuple[str, str]:
    """'202602' → ('115', '02')"""
    if not re.fullmatch(r"20\d{4}", ym):
        raise ValueError(f"month 格式必須是 YYYYMM，收到 {ym!r}")
    year = int(ym[:4]) - 1911
    month = ym[4:]
    return str(year), month


# ── Parser ────────────────────────────────────────────────

# MOPS 回的 HTML 是簡化版（非 ASP.NET PostBack），每檔基金一個 <table class='hasBorder'>
# 前面一行 <table class='noBorder'> 帶 "民國 YYY 年 MM 月 公司代號：XXXX 公司名稱：..."

COMPANY_HEADER_RE = re.compile(
    r"民國\s*(\d+)\s*年\s*(\d+)\s*月.*?公司代號：(\S+?)&nbsp;.*?公司名稱：\s*([^<]+)",
    re.S,
)

FUND_TABLE_RE = re.compile(
    r"<table\s+class='hasBorder'[^>]*>(.*?)</table>",
    re.S | re.I,
)

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
ROWSPAN_RE = re.compile(r"rowspan=['\"]?(\d+)", re.I)


def _strip(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = TAG_RE.sub("", s)
    return html_mod.unescape(s).strip()


def normalize_fund_name(raw: str) -> str:
    """
    MOPS 回傳帶 '證券投資信託基金' 完整名稱，whitelist 用 short name（'主動式ETF基金'）。
    normalize：去掉中間的 '證券投資信託' 連續字串，讓 active_etf_monthly view exact-match。
    e.g. '統一台股增長主動式ETF證券投資信託基金' → '統一台股增長主動式ETF基金'
    """
    return raw.replace("證券投資信託基金", "基金")


def parse_monthly_html(html: str) -> list[dict]:
    """
    解析 ajax_t78sb39_q3 step=1 的回應：
      一個 response 內有多組 [公司 header block] + <table class='hasBorder'>（各檔基金 Top 5）
    回傳 list of {fund_name, fund_name_raw, comid, company_name, top5:[{rank,code,name,pct}]}
    """
    # 先把 response 切成「公司 block」（每個 block 是 header + hasBorder table）
    # 比較魯棒的作法：直接配對 header 和其後的 table
    results: list[dict] = []

    # Split on each "hasBorder" table position, keep preceding header
    # 用 header 的 regex 從文字中抓所有 company headers + 其 offset
    header_iter = list(COMPANY_HEADER_RE.finditer(html))
    table_iter = list(FUND_TABLE_RE.finditer(html))

    # 每個 table 配最接近它的 header（offset 在 table 之前最近的）
    for tbl_m in table_iter:
        tbl_start = tbl_m.start()
        matched_header = None
        for h in header_iter:
            if h.end() <= tbl_start:
                matched_header = h
            else:
                break
        if not matched_header:
            continue
        comid = matched_header.group(3).strip()
        company_name = _strip(matched_header.group(4))

        # Parse rows of this fund table
        fund_name_raw = None
        top5: list[dict] = []
        for rm in ROW_RE.finditer(tbl_m.group(1)):
            trhtml = rm.group(1)
            if "tblHead" in trhtml or "合計" in trhtml:
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", trhtml, re.S | re.I)
            if not tds:
                continue
            rs_match = ROWSPAN_RE.search(trhtml)
            if rs_match and len(tds) == 5:
                # first row: [fund_name, rank, code, name, pct]
                fund_name_raw = _strip(tds[0])
                rank, code, name, pct = tds[1:5]
            elif len(tds) == 4:
                # subsequent row
                rank, code, name, pct = tds
            else:
                continue
            try:
                top5.append({
                    "rank": int(_strip(rank)),
                    "code": _strip(code),
                    "name": _strip(name),
                    "pct": float(_strip(pct)),
                })
            except ValueError:
                continue

        if fund_name_raw and top5:
            results.append({
                "fund_name": normalize_fund_name(fund_name_raw),
                "fund_name_raw": fund_name_raw,
                "comid": comid,
                "company_name": company_name,
                "top5": top5[:5],
            })

    return results


# ── Fetchers ─────────────────────────────────────────────

def fetch_monthly(ym: str) -> str:
    """Fetch raw MOPS HTML for a given month (YYYYMM).

    Two-step protocol confirmed 2026-04-19：
      1) POST /mops/web/ajax_t78sb39_new with type=03 → handshake
      2) POST /mops/web/ajax_t78sb39_q3 with year/month → actual data

    Step 1 not strictly required（step 2 直打也回資料），保留以避免未來 server 加驗證。
    """
    year, month = ym_to_roc(ym)
    _ = _post(
        f"{MOPS_BASE}/ajax_t78sb39_new",
        {"step": "1", "firstin": "1", "off": "1", "type": "03"},
    )
    return _post(
        f"{MOPS_BASE}/ajax_t78sb39_q3",
        {
            "firstin": "true", "run": "", "off": "1", "step": "1",
            "fund_no": "0", "TYPEK": "all",
            "year": year, "month": month,
        },
    )


# ── Subcommands ──────────────────────────────────────────

def cmd_monthly(args: argparse.Namespace) -> None:
    ym = args.month
    html = fetch_monthly(ym)
    if args.save_raw:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        year, month = ym_to_roc(ym)
        out = CACHE_DIR / f"t78sb39_q3_{year}{month}.html"
        out.write_text(html)
    funds = parse_monthly_html(html)
    result = {"ym": ym, "source": "MOPS t78sb39_q3", "funds": funds}
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(f"民國 {ym_to_roc(ym)[0]} 年 {ym_to_roc(ym)[1]} 月（{ym}） — {len(funds)} 檔主動 ETF 基金")
        for f in funds:
            print(f"\n  {f['company_name']} ({f['comid']})  {f['fund_name']}")
            for h in f["top5"]:
                print(f"    {h['rank']}. {h['code']} {h['name']} {h['pct']:.2f}%")


def cmd_parse(args: argparse.Namespace) -> None:
    """Parse a saved MOPS HTML file (for local testing / offline)."""
    html = Path(args.path).read_text()
    funds = parse_monthly_html(html)
    if args.json:
        json.dump({"funds": funds}, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        for f in funds:
            print(f"{f['company_name']} ({f['comid']}) {f['fund_name']}")
            for h in f["top5"]:
                print(f"  {h['rank']}. {h['code']} {h['name']} {h['pct']:.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser(prog="mopsetf", description="MOPS 主動式 ETF 揭露 CLI")
    sp = ap.add_subparsers(dest="cmd", required=True)

    m = sp.add_parser("monthly", help="基金每月持股前五大個股（MOPS t78sb39_q3）")
    m.add_argument("--month", required=True, help="YYYYMM，例如 202602")
    m.add_argument("--json", action="store_true")
    m.add_argument("--save-raw", action="store_true", help="存原始 HTML 到 .tmp/mops/")
    m.set_defaults(func=cmd_monthly)

    p = sp.add_parser("parse", help="解析本地 HTML（test only）")
    p.add_argument("path", help="HTML file path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_parse)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
