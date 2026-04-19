#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl"]
# ///
"""
etfdaily — CLI for Taiwan 主動 ETF 每日持股揭露 pipeline (6 發行投信).

主動 ETF 法規強制每日揭露完整持股（vs 基金只需月報 Top 10），是 tw-active
制度漏洞研究的核心 primary source。每家投信在自家官網各自揭露，格式/認證不一。

**Round 45 破解（2026-04-19）** — 一次 crack 六家：

| 投信 | ETF | 內部 ID | API 類型 | 歷史日期 |
|------|-----|---------|----------|----------|
| 統一 ezmoney | 00981A/00988A | 49YTW/61YTW | GET XLSX (cookie jar) | ❌ |
| 野村 nomurafunds | 00980A | 00980A | POST JSON | ✅ |
| 復華 fhtrust | 00991A | ETF23 | GET XLSX | ✅ |
| 安聯 etf.allianzgi | 00993A | E0002 | POST JSON (ASP.NET antiforgery) | ✅ |
| 群益 capitalfund | 00982A/00992A/00997A | 399/500/502 | POST JSON | ✅ |

Subcommands:
  catalog                         列 6 檔主動 ETF + 對應 endpoint
  holdings <code> [--date YYYYMMDD]
                                  抓單檔 ETF 當日（或指定日）完整持股，normalize JSON
  fetch <code> [--date YYYYMMDD]  下載原始檔案到 raw/etfdaily/<code>/<date>.{xlsx|json}
  fetch --all [--date YYYYMMDD]   批次下載所有 6 檔
  list <issuer>                   列某投信全產品 ID mapping
                                  （capital/fhtrust/nomura/allianz/uni）

Usage:
  ./etfdaily.py catalog
  ./etfdaily.py holdings 00981A
  ./etfdaily.py holdings 00993A --date 20260415
  ./etfdaily.py fetch 00991A --date 20260417
  ./etfdaily.py fetch --all
  ./etfdaily.py list capital     # 群益全產品 fundId

Global:
  --json    輸出 JSON（holdings / catalog 適用）
  --out DIR fetch 輸出目錄（預設 raw/etfdaily/）
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "raw" / "etfdaily"
UA = "Mozilla/5.0 (etfdaily-cli; +tw-active)"


# ── Catalog：6 檔主動 ETF 的 issuer + 內部 id ─────────────────────────

CATALOG: dict[str, dict[str, str]] = {
    "00981A": {"issuer": "uni",    "name": "統一台股增長",        "fund_code": "49YTW"},
    "00988A": {"issuer": "uni",    "name": "統一全球創新",        "fund_code": "61YTW"},
    "00991A": {"issuer": "fhtrust", "name": "復華台灣未來 50",    "fund_code": "ETF23"},
    "00980A": {"issuer": "nomura",  "name": "野村臺灣智慧優選",    "fund_code": "00980A"},
    "00985A": {"issuer": "nomura",  "name": "野村臺灣增強50",      "fund_code": "00985A"},
    "00993A": {"issuer": "allianz", "name": "安聯台灣主動式",      "fund_code": "E0002"},
    "00984A": {"issuer": "allianz", "name": "安聯台灣高息成長",    "fund_code": "E0001"},
    "00982A": {"issuer": "capital", "name": "群益台灣精選強棒",    "fund_code": "399"},
    "00992A": {"issuer": "capital", "name": "群益台灣科技創新",    "fund_code": "500"},
    "00997A": {"issuer": "capital", "name": "群益美國增長",        "fund_code": "502"},
    # 復華全系列（20+ slug）可以擴充，以 AL11 台股主動 13 檔 + 群益海外補位為主要觀測點；
    # 其餘 issuer 的 fetcher 仍待破解（中信 00995A、兆豐 00996A、台新 00987A、
    # 國泰 00400A、第一金 00994A）
}


# ── HTTP helpers ─────────────────────────────────────────────────────

def _open(req: urllib.request.Request, timeout: int = 30) -> tuple[bytes, dict[str, str]]:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers.items())


def _get(url: str, headers: dict[str, str] | None = None, cookie_jar: CookieJar | None = None) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={**{"User-Agent": UA}, **(headers or {})})
    if cookie_jar is not None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        with opener.open(req, timeout=30) as resp:
            return resp.read(), dict(resp.headers.items())
    return _open(req)


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None,
               cookie_jar: CookieJar | None = None) -> tuple[bytes, dict[str, str]]:
    data = json.dumps(payload).encode("utf-8")
    hdr = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
    if cookie_jar is not None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        with opener.open(req, timeout=30) as resp:
            return resp.read(), dict(resp.headers.items())
    return _open(req)


# ── 統一 ezmoney（GET XLSX + cookie jar）────────────────────────────

def fetch_uni_xlsx(fund_code: str) -> bytes:
    """
    統一 ezmoney：GET /ETF/Fund/AssetExcelNPOI?fundCode=XX
    需 cookie jar 跟 302 拿 __nxquid anti-bot cookie。
    XLSX 內嵌當日（最新）資料日期，不支援 date 參數。
    """
    jar = CookieJar()
    url = f"https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI?fundCode={fund_code}"
    raw, headers = _get(url, cookie_jar=jar)
    if not raw.startswith(b"PK"):
        # 偶而第一次還沒拿到 cookie，重試一次
        raw, headers = _get(url, cookie_jar=jar)
    return raw


# ── 復華 fhtrust（GET XLSX 純 URL）──────────────────────────────────

def fetch_fhtrust_xlsx(etf_slug: str, date_ymd: str) -> bytes:
    """
    復華：GET /api/assetsExcel/{slug}/{YYYYMMDD}
    無 session / cookie。非交易日 body = "查無資料"（200/12bytes）。
    """
    url = f"https://www.fhtrust.com.tw/api/assetsExcel/{etf_slug}/{date_ymd}"
    raw, _ = _get(url)
    if raw.startswith(b"\xef\xbb\xbf") or raw.startswith(b"\xe6\x9f\xa5"):  # BOM 或「查」
        raise RuntimeError(f"復華 {date_ymd}：查無資料（非交易日或未發布）")
    if not raw.startswith(b"PK"):
        raise RuntimeError(f"復華回應非 XLSX：{raw[:120]!r}")
    return raw


# ── 野村 nomurafunds（POST JSON）────────────────────────────────────

def fetch_nomura_json(fund_id: str, date_ymd: str | None) -> dict[str, Any]:
    """
    野村：POST /API/ETFAPI/api/Fund/GetFundAssets
    純 JSON，無 session。SearchDate 格式 YYYY-MM-DD。
    """
    search_date = _ymd_to_dash(date_ymd) if date_ymd else _last_weekday_dash()
    payload = {"FundID": fund_id, "SearchDate": search_date}
    url = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
    raw, _ = _post_json(url, payload)
    return json.loads(raw.decode("utf-8"))


# ── 安聯 etf.allianzgi（ASP.NET Antiforgery + POST JSON）─────────────

def fetch_allianz_json(fund_no: str, date_ymd: str | None) -> dict[str, Any]:
    """
    安聯：先 GET /webapi/api/AntiForgery/GetAntiForgeryToken 拿 cookie
    再 POST /webapi/api/Fund/GetFundTradeInfo 塞 X-XSRF-TOKEN header + cookie
    """
    jar = CookieJar()
    _get("https://etf.allianzgi.com.tw/webapi/api/AntiForgery/GetAntiForgeryToken", cookie_jar=jar)
    # 提 token
    token = ""
    for c in jar:
        if c.name == "X-XSRF-TOKEN":
            token = c.value
            break
    if not token:
        raise RuntimeError("安聯：未取得 X-XSRF-TOKEN cookie")
    date_iso = (_ymd_to_dash(date_ymd) + "T00:00:00") if date_ymd else None
    payload = {"FundNo": fund_no, "Date": date_iso}
    url = "https://etf.allianzgi.com.tw/webapi/api/Fund/GetFundTradeInfo"
    raw, _ = _post_json(url, payload, headers={"X-XSRF-TOKEN": token}, cookie_jar=jar)
    return json.loads(raw.decode("utf-8"))


# ── 群益 capitalfund（POST JSON 最乾淨）──────────────────────────────

def fetch_capital_json(fund_id: str, date_ymd: str | None) -> dict[str, Any]:
    """
    群益：POST /CFWeb/api/etf/buyback，無 session/cookie。
    date 格式 YYYY-MM-DD 或 null = 最新。
    """
    payload: dict[str, Any] = {"fundId": fund_id}
    if date_ymd:
        payload["date"] = _ymd_to_dash(date_ymd)
    raw, _ = _post_json("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", payload)
    return json.loads(raw.decode("utf-8"))


def fetch_capital_list() -> dict[str, Any]:
    raw, _ = _post_json("https://www.capitalfund.com.tw/CFWeb/api/etf/list", {})
    return json.loads(raw.decode("utf-8"))


# ── 日期 util ────────────────────────────────────────────────────────

def _ymd_to_dash(ymd: str) -> str:
    """20260417 → 2026-04-17"""
    if "-" in ymd:
        return ymd
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _today_dash() -> str:
    from datetime import date
    return date.today().isoformat()


def _today_ymd() -> str:
    from datetime import date
    return date.today().strftime("%Y%m%d")


def _last_weekday_ymd() -> str:
    """週末時退回週五。不處理國定假日 — 若拿不到資料使用者可 --date override。"""
    from datetime import date, timedelta
    d = date.today()
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _last_weekday_dash() -> str:
    from datetime import date, timedelta
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


# ── XLSX 解析（統一 / 復華）──────────────────────────────────────────

def parse_xlsx_holdings(raw: bytes, issuer: str) -> dict[str, Any]:
    """統一/復華 XLSX 持股明細，回 normalized dict。

    欄位變異：
    - 統一 4 cols：代號 / 名稱 / 股數 / 持股權重
    - 復華 5 cols：代號 / 名稱 / 股數 / 金額 / 權重(%)
    通則：第一欄 = 代號（非全數字，可能 'LITE US' / '6787 JP'），最後一欄 = 權重。
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    header_idx = -1
    for i, row in enumerate(rows):
        if not row:
            continue
        cells = [str(c).strip() if c is not None else "" for c in row]
        line = " ".join(cells)
        if ("代號" in line or "代碼" in line) and ("權重" in line or "比例" in line):
            header_idx = i
            break

    holdings: list[dict[str, Any]] = []
    if header_idx < 0:
        return {"issuer": issuer, "holdings": holdings}

    for row in rows[header_idx + 1 :]:
        if not row or row[0] is None:
            # 空白 row = 結尾（統一表格結構）
            if holdings:
                break
            continue
        code = str(row[0]).strip()
        if not code:
            continue
        name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        shares = _to_number(row[2]) if len(row) > 2 else None
        weight = _to_number(row[-1])
        holdings.append({
            "code": code,
            "name": name,
            "shares": shares,
            "weight_pct": weight,
            "kind": "stock",
        })
    return {"issuer": issuer, "holdings": holdings}


def _to_number(v: Any) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").replace("%", "").strip()
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


# ── 統一 JSON output schema ──────────────────────────────────────────

def normalize_uni(code: str, raw_xlsx: bytes) -> dict[str, Any]:
    parsed = parse_xlsx_holdings(raw_xlsx, "uni")
    return {
        "etf": code,
        "issuer": "統一投信",
        "source": "ezmoney.com.tw",
        "format": "xlsx",
        "data_date": None,  # 統一 XLSX 內嵌 filename，這裡不剖
        "holdings": parsed["holdings"],
    }


def normalize_fhtrust(code: str, raw_xlsx: bytes, date_ymd: str) -> dict[str, Any]:
    parsed = parse_xlsx_holdings(raw_xlsx, "fhtrust")
    return {
        "etf": code,
        "issuer": "復華投信",
        "source": "fhtrust.com.tw",
        "format": "xlsx",
        "data_date": date_ymd,
        "holdings": parsed["holdings"],
    }


def normalize_nomura(code: str, js: dict[str, Any]) -> dict[str, Any]:
    data = (js or {}).get("Entries", {}).get("Data") or {}
    asset = data.get("FundAsset") or {}
    tables = data.get("Table") or []
    holdings: list[dict[str, Any]] = []
    for t in tables:
        title = (t.get("TableTitle") or "").strip()
        # 野村 API 回傳最後一張 table TableTitle="" 是各類資產 TWD 金額「小計」，
        # row 結構為 [類別名, "TWD$xxx", "TWD", 原始金額]，不是 holding。
        # 例：["股票","TWD$12,648,807,261","TWD","12648807261"] 會被誤當成權重 126 億%。
        if not title:
            continue
        for row in t.get("Rows") or []:
            if len(row) < 4:
                continue
            holdings.append({
                "code": str(row[0]).strip(),
                "name": str(row[1]).strip(),
                "shares": _to_number(row[2]),
                "weight_pct": _to_number(row[3]),
                "kind": title,
            })
    return {
        "etf": code,
        "issuer": "野村投信",
        "source": "nomurafunds.com.tw",
        "format": "json",
        "data_date": asset.get("NavDate"),
        "aum": _to_number(asset.get("Aum")),
        "units": _to_number(asset.get("Units")),
        "nav": _to_number(asset.get("Nav")),
        "holdings": holdings,
    }


def normalize_allianz(code: str, js: dict[str, Any]) -> dict[str, Any]:
    """安聯 columns：序號 / 代號 / 名稱 / 股數(口數) / 權重(%) / [契約年月]"""
    entries = (js or {}).get("Entries") or {}
    tables = entries.get("DynamicTableData") or []
    holdings: list[dict[str, Any]] = []
    for t in tables:
        title = t.get("TableTitle") or ""
        # 去掉括號內百分比（「股票 (97.89%)」→「股票」）
        kind = title.split("(")[0].strip() or "stock"
        for row in t.get("Rows") or []:
            if not row or len(row) < 5:
                continue
            # row[0]=序號，skip
            holdings.append({
                "code": str(row[1]).strip(),
                "name": str(row[2]).strip(),
                "shares": _to_number(row[3]),
                "weight_pct": _to_number(row[4]),
                "kind": kind,
            })
    return {
        "etf": code,
        "issuer": "安聯投信",
        "source": "etf.allianzgi.com.tw",
        "format": "json",
        "data_date": entries.get("CNavDt"),
        "pcf_date": entries.get("CPcfdate"),
        "aum": _to_number(entries.get("CAnceTotalAv")),
        "units": _to_number(entries.get("CAnceTotalIssues")),
        "nav": _to_number(entries.get("CAnceNav")),
        "holdings": holdings,
    }


def normalize_capital(code: str, js: dict[str, Any]) -> dict[str, Any]:
    data = (js or {}).get("data") or {}
    pcf = data.get("pcf") or {}
    holdings: list[dict[str, Any]] = []
    for s in data.get("stocks") or []:
        holdings.append({
            "code": str(s.get("stocNo", "")).strip(),
            "name": str(s.get("stocName", "")).strip(),
            "shares": _to_number(s.get("share")),
            "weight_pct": _to_number(s.get("weight")),
            "kind": "stock",
        })
    for b in data.get("bonds") or []:
        holdings.append({
            "code": str(b.get("bondNo", "")).strip(),
            "name": str(b.get("bondName", "")).strip(),
            "shares": _to_number(b.get("share")),
            "weight_pct": _to_number(b.get("weight")),
            "kind": "bond",
        })
    return {
        "etf": code,
        "issuer": "群益投信",
        "source": "capitalfund.com.tw",
        "format": "json",
        "data_date": pcf.get("date1"),
        "aum": _to_number(pcf.get("nav")),   # 此欄為淨資產
        "units": _to_number(pcf.get("totUnit")),
        "nav": _to_number(pcf.get("pUnit")),
        "holdings": holdings,
    }


# ── 統一 dispatcher ───────────────────────────────────────────────────

def fetch_holdings(code: str, date_ymd: str | None = None) -> dict[str, Any]:
    cat = CATALOG.get(code)
    if not cat:
        raise SystemExit(f"未知 ETF 代號：{code}（可用：{', '.join(CATALOG)}）")
    issuer = cat["issuer"]
    fund_code = cat["fund_code"]
    if issuer == "uni":
        if date_ymd:
            print(f"warn: 統一 ezmoney 不支援指定日期，回最新", file=sys.stderr)
        raw = fetch_uni_xlsx(fund_code)
        return normalize_uni(code, raw)
    if issuer == "fhtrust":
        d = date_ymd or _last_weekday_ymd()
        raw = fetch_fhtrust_xlsx(fund_code, d)
        return normalize_fhtrust(code, raw, d)
    if issuer == "nomura":
        js = fetch_nomura_json(fund_code, date_ymd)
        return normalize_nomura(code, js)
    if issuer == "allianz":
        js = fetch_allianz_json(fund_code, date_ymd)
        return normalize_allianz(code, js)
    if issuer == "capital":
        js = fetch_capital_json(fund_code, date_ymd)
        return normalize_capital(code, js)
    raise SystemExit(f"未知 issuer: {issuer}")


def fetch_raw(code: str, date_ymd: str | None) -> tuple[bytes, str]:
    """回原始 bytes + 副檔名（'xlsx' 或 'json'）"""
    cat = CATALOG.get(code)
    if not cat:
        raise SystemExit(f"未知 ETF 代號：{code}")
    issuer = cat["issuer"]
    fund_code = cat["fund_code"]
    if issuer == "uni":
        return fetch_uni_xlsx(fund_code), "xlsx"
    if issuer == "fhtrust":
        d = date_ymd or _last_weekday_ymd()
        return fetch_fhtrust_xlsx(fund_code, d), "xlsx"
    if issuer == "nomura":
        js = fetch_nomura_json(fund_code, date_ymd)
        return json.dumps(js, ensure_ascii=False, indent=2).encode("utf-8"), "json"
    if issuer == "allianz":
        js = fetch_allianz_json(fund_code, date_ymd)
        return json.dumps(js, ensure_ascii=False, indent=2).encode("utf-8"), "json"
    if issuer == "capital":
        js = fetch_capital_json(fund_code, date_ymd)
        return json.dumps(js, ensure_ascii=False, indent=2).encode("utf-8"), "json"
    raise SystemExit("unreachable")


# ── commands ─────────────────────────────────────────────────────────

def cmd_catalog(args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
        return
    print(f"{'ETF':<8} {'發行投信':<12} {'內部 ID':<10} 名稱")
    print("-" * 60)
    for code, cat in CATALOG.items():
        print(f"{code:<8} {cat['issuer']:<12} {cat['fund_code']:<10} {cat['name']}")


def cmd_holdings(args: argparse.Namespace) -> None:
    result = fetch_holdings(args.code.upper(), args.date)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    h = result.get("holdings") or []
    print(f"=== {result['etf']} {result['issuer']} ({result['source']}) ===")
    if result.get("data_date"):
        print(f"資料日: {result['data_date']}")
    if result.get("nav"):
        print(f"淨值: {result['nav']}  AUM: {result.get('aum')}  Units: {result.get('units')}")
    print(f"持股 {len(h)} 檔")
    print("-" * 60)
    for i, row in enumerate(h, 1):
        w = row.get("weight_pct")
        w_s = f"{w:>6.2f}%" if isinstance(w, (int, float)) else f"{str(w):>7}"
        print(f"{i:>3}  {row['code']:<10} {row['name']:<20} {w_s}")


def cmd_fetch(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    codes = list(CATALOG) if args.all else [args.code.upper()]
    for code in codes:
        try:
            raw, ext = fetch_raw(code, args.date)
        except Exception as e:
            print(f"× {code}: {e}", file=sys.stderr)
            continue
        date_tag = args.date or _last_weekday_ymd()
        dst_dir = out_dir / code
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{date_tag}.{ext}"
        dst.write_bytes(raw)
        print(f"✓ {code:<8} {len(raw):>8} bytes → {dst}")


def cmd_list(args: argparse.Namespace) -> None:
    issuer = args.issuer.lower()
    if issuer in ("capital", "群益"):
        js = fetch_capital_list()
        funds = (js.get("data") or {}).get("funds") or []
        print(f"{'fundId':<8} {'stockNo':<8} 名稱")
        for f in funds:
            print(f"{str(f.get('fundNo','')):<8} {str(f.get('stockNo','')):<8} {f.get('shortName','')}")
        if args.json:
            print(json.dumps(funds, ensure_ascii=False, indent=2))
    else:
        raise SystemExit(f"list {issuer} 尚未實作；目前只支援 capital")


# ── argparse ─────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="etfdaily — 主動 ETF 每日持股揭露 CLI (6 發行投信)")
    p.add_argument("--json", action="store_true", help="輸出 JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="6 檔主動 ETF + endpoint 對照")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_catalog)

    h = sub.add_parser("holdings", help="抓單檔完整持股")
    h.add_argument("code", help="ETF 代號（00981A/00988A/00991A/00980A/00993A/00982A）")
    h.add_argument("--date", help="資料日 YYYYMMDD（統一不支援；其他可回溯）")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_holdings)

    f = sub.add_parser("fetch", help="下載原始檔案到 raw/etfdaily/")
    f.add_argument("code", nargs="?", help="ETF 代號（或用 --all）")
    f.add_argument("--all", action="store_true", help="批次下載全部 6 檔")
    f.add_argument("--date", help="資料日 YYYYMMDD")
    f.add_argument("--out", help=f"輸出目錄（預設 {DEFAULT_OUT}）")
    f.set_defaults(func=cmd_fetch)

    l = sub.add_parser("list", help="列某投信全產品 ID（capital 可用）")
    l.add_argument("issuer", help="capital | fhtrust | nomura | allianz | uni")
    l.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    if args.cmd == "fetch" and not args.all and not args.code:
        p.error("fetch 需 code 或 --all")
    try:
        args.func(args)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.reason} — {e.url}")


if __name__ == "__main__":
    main()
