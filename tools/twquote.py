#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
twquote — CLI for TWSE + TPEx open data (ETF 盤後量化資料 pipeline).

三條資料線：
  1. TWSE OpenAPI（https://openapi.twse.com.tw/v1/...）— 官方開放、無 CAPTCHA
  2. TWSE legacy（/fund/T86）— 三大法人個股買賣超（OpenAPI 無此 endpoint）
  3. TPEx OpenAPI（https://www.tpex.org.tw/openapi/v1/...）— 上櫃同類資料

Subcommands:
  daily        個股日成交（TWSE STOCK_DAY_ALL + TPEx equivalent，合併後客端 filter）
  insti        三大法人買賣超（T86 + tpex_3insti_daily_trading，含主動 ETF）
  qfii         外資持股比率 Top 20（MI_QFIIS_sort_20）
  etfrank      定期定額交易戶數排行（ETFReport/ETFRank 月報）
  active       只列主動 ETF 的今日快照（daily + insti 合併呈現）
  paths        列 TWSE / TPEx OpenAPI 全部 path（debug / 發掘用）
  schema       顯示某 path 的回傳欄位定義（borrow jerryliutaipei swagger 自動發掘）

Usage:
  ./twquote.py daily 00981A                       # 某檔今日行情
  ./twquote.py insti 00981A --date 20260417       # 某檔某日三大法人
  ./twquote.py active                             # 28 檔主動 ETF 今日盤後總覽
  ./twquote.py active --date 20260417 --json      # JSON 輸出
  ./twquote.py qfii 2330
  ./twquote.py etfrank --active-only              # 只看主動
  ./twquote.py paths twse | grep 法人
  ./twquote.py schema twse /fund/T86              # 看 T86 全欄位定義
  ./twquote.py schema tpex /tpex_3insti_daily_trading --json

Global options:
  --date YYYYMMDD   指定日期（insti / active 預設昨日、daily 預設最新可得）
  --json            JSON 輸出
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

TWSE_API = "https://openapi.twse.com.tw/v1"
TWSE_LEGACY = "https://www.twse.com.tw"
TPEX_API = "https://www.tpex.org.tw/openapi/v1"
TWSE_SWAGGER = "https://openapi.twse.com.tw/v1/swagger.json"
TPEX_SWAGGER = "https://www.tpex.org.tw/openapi/swagger.json"
UA = {"User-Agent": "Mozilla/5.0 (twquote-cli)"}

REPO_ROOT = Path(__file__).resolve().parent.parent
SWAGGER_CACHE_DIR = REPO_ROOT / ".tmp" / "swagger"
SWAGGER_TTL_SEC = 24 * 3600


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url: str) -> object:
    return json.loads(_get(url).decode("utf-8"))


def _guess_last_trading_day(now: datetime | None = None) -> str:
    """回傳 YYYYMMDD（倒推至最近工作日；不看國定假日，使用者自行 --date 指定）"""
    d = now or datetime.now()
    # 14:30 後才當天，否則退一天
    if d.hour < 15:
        d = d - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d = d - timedelta(days=1)
    return d.strftime("%Y%m%d")


def _ymd_to_roc(ymd: str) -> str:
    """20260417 -> 1150417"""
    y = int(ymd[:4]) - 1911
    return f"{y}{ymd[4:]}"


# ── Data fetchers ─────────────────────────────────────────


def twse_stock_day_all() -> list[dict]:
    return _get_json(f"{TWSE_API}/exchangeReport/STOCK_DAY_ALL")  # type: ignore[return-value]


def tpex_stock_day_all() -> list[dict]:
    # TPEx 個股日成交 path 名稱不同，用 mainboard_daily_close_quotes
    return _get_json(f"{TPEX_API}/tpex_mainboard_daily_close_quotes")  # type: ignore[return-value]


def twse_t86(date: str) -> dict:
    qs = urllib.parse.urlencode({"response": "json", "date": date, "selectType": "ALL"})
    return _get_json(f"{TWSE_LEGACY}/fund/T86?{qs}")  # type: ignore[return-value]


def tpex_insti() -> list[dict]:
    return _get_json(f"{TPEX_API}/tpex_3insti_daily_trading")  # type: ignore[return-value]


def twse_qfii_top20() -> list[dict]:
    return _get_json(f"{TWSE_API}/fund/MI_QFIIS_sort_20")  # type: ignore[return-value]


def twse_etf_rank() -> list[dict]:
    return _get_json(f"{TWSE_API}/ETFReport/ETFRank")  # type: ignore[return-value]


def _swagger_cache(which: str) -> dict:
    """讀 swagger.json（含 24h 檔案快取，避免每次打 network）"""
    import time
    SWAGGER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = SWAGGER_CACHE_DIR / f"{which}.json"
    url = TWSE_SWAGGER if which == "twse" else TPEX_SWAGGER
    if path.exists() and (time.time() - path.stat().st_mtime) < SWAGGER_TTL_SEC:
        return json.loads(path.read_text(encoding="utf-8"))
    raw = _get(url)
    path.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


def twse_paths() -> list[tuple[str, str]]:
    d = _swagger_cache("twse")
    return [
        (p, (v.get("get") or {}).get("summary", ""))
        for p, v in d.get("paths", {}).items()
    ]


def tpex_paths() -> list[tuple[str, str]]:
    d = _swagger_cache("tpex")
    return [
        (p, (v.get("get") or {}).get("summary", ""))
        for p, v in d.get("paths", {}).items()
    ]


def _resolve_ref(ref: str, doc: dict) -> dict:
    """#/components/schemas/NAME -> dict"""
    parts = ref.lstrip("#/").split("/")
    node: object = doc
    for p in parts:
        node = node.get(p, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def swagger_fields(which: str, path: str) -> list[dict]:
    """回傳 [{name, type, description}]；支援 swagger 2.0 (TWSE) 與 openapi 3.0 (TPEx)"""
    d = _swagger_cache(which)
    p = d.get("paths", {}).get(path)
    if not p:
        raise LookupError(f"{which}: path {path!r} not in swagger")
    op = p.get("get") or {}
    r200 = op.get("responses", {}).get("200", {})
    schema: dict = {}
    if "schema" in r200:  # swagger 2.0
        schema = r200["schema"] or {}
    elif "content" in r200:  # openapi 3.0
        content = r200["content"]
        any_ct = content.get("application/json") or next(iter(content.values()), {})
        schema = any_ct.get("schema", {}) or {}
    # 解 $ref
    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], d)
    if schema.get("type") == "array" and "items" in schema:
        items = schema["items"]
        if "$ref" in items:
            items = _resolve_ref(items["$ref"], d)
        schema = items
    props = schema.get("properties") or {}
    return [
        {"name": name, "type": spec.get("type", ""), "description": spec.get("description", "")}
        for name, spec in props.items()
    ]


# ── T86 row helpers ────────────────────────────────────────

T86_FIELDS_IDX = {
    "code": 0,
    "name": 1,
    "foreign_net": 4,     # 外陸資買賣超(不含外資自營商)
    "trust_net": 10,      # 投信買賣超
    "dealer_net": 11,     # 自營商買賣超合計
    "dealer_self_net": 14,   # 自營商(自行買賣)
    "dealer_hedge_net": 17,  # 自營商(避險)
    "total_net": 18,      # 三大法人買賣超合計
}


def _parse_num(s: str) -> int:
    if s is None:
        return 0
    s = str(s).replace(",", "").replace(" ", "").replace("--", "0")
    return int(s) if s and s != "-" else 0


def t86_row_to_dict(row: list[str]) -> dict:
    return {
        k: (row[i] if k in ("code", "name") else _parse_num(row[i]))
        for k, i in T86_FIELDS_IDX.items()
    }


# ── Commands ──────────────────────────────────────────────


def cmd_daily(args) -> int:
    code = args.code.upper()
    twse_rows = twse_stock_day_all()
    hit = next((r for r in twse_rows if r.get("Code") == code), None)
    market = "TWSE"
    if not hit:
        tpex_rows = tpex_stock_day_all()
        hit = next((r for r in tpex_rows if r.get("SecuritiesCompanyCode") == code), None)
        market = "TPEx"
    if not hit:
        print(f"error: {code} not found in TWSE/TPEx daily quotes", file=sys.stderr)
        return 1
    out = {"market": market, **hit}
    if args.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(f"[{market}] {code}")
        for k, v in hit.items():
            print(f"  {k}: {v}")
    return 0


def _t86_lookup(date: str, code: str) -> dict | None:
    resp = twse_t86(date)
    if resp.get("stat") != "OK":
        return None
    for row in resp.get("data", []):
        if row[0].strip() == code:
            return t86_row_to_dict(row)
    return None


def _tpex_insti_lookup(date: str, code: str) -> dict | None:
    rows = tpex_insti()
    roc = _ymd_to_roc(date)
    for r in rows:
        if r.get("SecuritiesCompanyCode") == code and r.get("Date") == roc:
            foreign = _parse_num(r.get(
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
                r.get("ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy", 0)
            ))
            return {
                "code": code,
                "name": r.get("CompanyName", ""),
                "foreign_net": _parse_num(r.get(
                    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference", 0)),
                "trust_net": _parse_num(r.get("SecuritiesInvestmentTrustCompanies-Difference", 0)),
                "dealer_net": _parse_num(r.get("Dealers-Difference", 0)),
                "total_net": _parse_num(r.get("TotalDifference", 0)),
            }
    return None


def cmd_insti(args) -> int:
    code = args.code.upper()
    date = args.date or _guess_last_trading_day()
    twse_hit = _t86_lookup(date, code)
    if twse_hit:
        twse_hit["market"] = "TWSE"
        if args.json:
            json.dump(twse_hit, sys.stdout, ensure_ascii=False, indent=2); print()
        else:
            print(f"[TWSE] {code} {twse_hit['name']} {date}")
            for k in ("foreign_net", "trust_net", "dealer_self_net", "dealer_hedge_net", "dealer_net", "total_net"):
                print(f"  {k:<20} {twse_hit[k]:>15,}")
        return 0
    tpex_hit = _tpex_insti_lookup(date, code)
    if tpex_hit:
        tpex_hit["market"] = "TPEx"
        if args.json:
            json.dump(tpex_hit, sys.stdout, ensure_ascii=False, indent=2); print()
        else:
            print(f"[TPEx] {code} {tpex_hit['name']} {date}")
            for k in ("foreign_net", "trust_net", "dealer_net", "total_net"):
                print(f"  {k:<20} {tpex_hit[k]:>15,}")
        return 0
    print(f"error: {code} not found in T86 ({date}) or TPEx insti ({_ymd_to_roc(date)})", file=sys.stderr)
    return 1


def cmd_qfii(args) -> int:
    rows = twse_qfii_top20()
    if args.code:
        hit = next((r for r in rows if r.get("Code") == args.code.upper()), None)
        if not hit:
            print(f"{args.code} 不在 Top 20 外資持股榜", file=sys.stderr)
            return 1
        rows = [hit]
    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2); print()
    else:
        print(f"{'Rank':<5} {'Code':<8} {'Name':<18} {'SharesHeld%':>12} {'AvailInvest%':>14}")
        for r in rows:
            name = r.get("Name", "")
            pad = name + " " * max(0, 18 - sum(2 if ord(c) > 127 else 1 for c in name))
            print(f"{r['Rank']:<5} {r['Code']:<8} {pad}{r['SharesHeldPer']:>12} {r['AvailableInvestPer']:>14}")
    return 0


def cmd_etfrank(args) -> int:
    rows = twse_etf_rank()
    if args.active_only:
        rows = [r for r in rows if str(r.get("ETFsName", "")).startswith("主動")]
    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2); print()
    else:
        print(f"{'排名':<6} {'ETF 代號':<10} {'名稱':<24} {'定期定額戶數':>12}")
        for r in rows[:50]:
            name = r.get("ETFsName", "")
            pad = name + " " * max(0, 24 - sum(2 if ord(c) > 127 else 1 for c in name))
            print(f"{r.get('No',''):<6} {r.get('ETFsSecurityCode',''):<10} {pad}{r.get('ETFsNumberofTradingAccounts',''):>12}")
        print(f"(顯示前 {min(len(rows),50)}/{len(rows)})")
    return 0


def cmd_active(args) -> int:
    """28 檔主動 ETF 今日快照（日成交 + 三大法人）"""
    date = args.date or _guess_last_trading_day()
    twse_rows = twse_stock_day_all()
    tpex_rows = tpex_stock_day_all()
    twse_t86_resp = twse_t86(date)
    tpex_insti_rows = tpex_insti()
    roc = _ymd_to_roc(date)

    active_twse = [r for r in twse_rows if str(r.get("Name", "")).startswith("主動")]
    active_tpex = [r for r in tpex_rows if str(r.get("CompanyName", "")).startswith("主動")]

    t86_by_code = {}
    if twse_t86_resp.get("stat") == "OK":
        for row in twse_t86_resp["data"]:
            if row[1].strip().startswith("主動"):
                d = t86_row_to_dict(row)
                t86_by_code[d["code"].strip()] = d

    tpex_insti_by_code = {}
    for r in tpex_insti_rows:
        if r.get("Date") == roc and str(r.get("CompanyName", "")).startswith("主動"):
            code = r["SecuritiesCompanyCode"]
            tpex_insti_by_code[code] = {
                "foreign_net": _parse_num(r.get("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference", 0)),
                "trust_net": _parse_num(r.get("SecuritiesInvestmentTrustCompanies-Difference", 0)),
                "dealer_net": _parse_num(r.get("Dealers-Difference", 0)),
                "total_net": _parse_num(r.get("TotalDifference", 0)),
            }

    snapshots = []
    for r in active_twse:
        code = r["Code"]
        insti = t86_by_code.get(code, {})
        snapshots.append({
            "market": "TWSE",
            "code": code,
            "name": r["Name"],
            "close": r.get("ClosingPrice"),
            "volume": r.get("TradeVolume"),
            "foreign_net": insti.get("foreign_net", 0),
            "trust_net": insti.get("trust_net", 0),
            "dealer_net": insti.get("dealer_net", 0),
            "total_net": insti.get("total_net", 0),
        })
    for r in active_tpex:
        code = r["SecuritiesCompanyCode"]
        insti = tpex_insti_by_code.get(code, {})
        snapshots.append({
            "market": "TPEx",
            "code": code,
            "name": r["CompanyName"],
            "close": r.get("Close"),
            "volume": r.get("TradingShares"),
            "foreign_net": insti.get("foreign_net", 0),
            "trust_net": insti.get("trust_net", 0),
            "dealer_net": insti.get("dealer_net", 0),
            "total_net": insti.get("total_net", 0),
        })
    snapshots.sort(key=lambda s: s["code"])

    if args.json:
        json.dump({"date": date, "snapshots": snapshots}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    print(f"主動 ETF 盤後快照（{date}） — {len(snapshots)} 檔")
    print(f"{'市場':<6} {'代號':<8} {'名稱':<22} {'收盤':>7} {'成交量':>14} {'外資淨':>14} {'投信淨':>10} {'自營淨':>14} {'三大淨':>14}")
    print("-" * 130)
    for s in snapshots:
        name = s["name"]
        pad = name + " " * max(0, 22 - sum(2 if ord(c) > 127 else 1 for c in name))
        print(f"{s['market']:<6} {s['code']:<8} {pad}{str(s['close']):>7} {s['volume']!s:>14} "
              f"{s['foreign_net']:>14,} {s['trust_net']:>10,} {s['dealer_net']:>14,} {s['total_net']:>14,}")
    return 0


def cmd_paths(args) -> int:
    which = args.which
    pairs = tpex_paths() if which == "tpex" else twse_paths()
    for p, s in sorted(pairs):
        print(f"{p}  |  {s}")
    print(f"\n合計 {len(pairs)} 條（{which.upper()}）", file=sys.stderr)
    return 0


def cmd_schema(args) -> int:
    """顯示 OpenAPI path 的回傳欄位（name / type / description）。"""
    try:
        fields = swagger_fields(args.which, args.path)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not fields:
        print(f"(無欄位定義；可能該 path 未定義 schema)", file=sys.stderr)
        return 0
    if args.json:
        json.dump({"api": args.which, "path": args.path, "fields": fields},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    print(f"[{args.which.upper()}] {args.path}  （{len(fields)} 欄）")
    print("-" * 90)
    for f in fields:
        name = f["name"]
        desc = f["description"]
        tp = f["type"]
        # 中英對齊近似
        pad = name + " " * max(0, 58 - sum(2 if ord(c) > 127 else 1 for c in name))
        print(f"{pad}{tp:<8} {desc}")
    return 0


# ── Main ──────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(prog="twquote", description="TWSE + TPEx quote CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("daily", help="個股日成交")
    sp.add_argument("code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_daily)

    sp = sub.add_parser("insti", help="三大法人個股買賣超")
    sp.add_argument("code")
    sp.add_argument("--date", help="YYYYMMDD，預設最近工作日")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_insti)

    sp = sub.add_parser("qfii", help="外資持股比率 Top 20")
    sp.add_argument("code", nargs="?")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_qfii)

    sp = sub.add_parser("etfrank", help="定期定額交易戶數排行")
    sp.add_argument("--active-only", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_etfrank)

    sp = sub.add_parser("active", help="主動 ETF 盤後快照（日成交 + 三大法人）")
    sp.add_argument("--date", help="YYYYMMDD，預設最近工作日")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_active)

    sp = sub.add_parser("paths", help="列 OpenAPI 路徑")
    sp.add_argument("which", choices=["twse", "tpex"])
    sp.set_defaults(func=cmd_paths)

    sp = sub.add_parser("schema", help="顯示 OpenAPI path 的欄位定義")
    sp.add_argument("which", choices=["twse", "tpex"])
    sp.add_argument("path", help="例如 /fund/T86 或 /tpex_3insti_daily_trading")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_schema)

    args = p.parse_args()
    try:
        return args.func(args)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
