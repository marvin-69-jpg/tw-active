#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf"]
# ///
"""
fundclear — CLI for Taiwan FundClear ETF prospectus pipeline.

資料來源：集保結算所「基金資訊觀測站」https://www.fundclear.com.tw/
**不是** MOPS — Round 1-43 盲點。公開說明書實際託管在 FundClear。

Subcommands:
  list                  列出所有 ETF（預設主動，可 --all）
  list --raw            輸出原始 FundClear JSON（debug 用）
  fetch <code>          下載公開說明書 PDF 到 raw/prospectus/
  fetch --all           下載所有主動 ETF 公開說明書（跳過已存在）
  extract <code>        抽出 PDF 純文字 → stdout 或 raw/prospectus/
  info <code>           顯示單一 ETF 的 FundClear 欄位（含 fileName / 官網 / 規模）

Usage:
  ./fundclear.py list
  ./fundclear.py list --all
  ./fundclear.py fetch 00981A
  ./fundclear.py fetch --all
  ./fundclear.py extract 00996A > /tmp/00996a.txt
  ./fundclear.py info 00985D

Global options:
  --out DIR       PDF 輸出目錄（預設 raw/prospectus/）
  --json          輸出 JSON（list / info 適用）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://www.fundclear.com.tw"
QUERY_URL = f"{API_BASE}/api/etf/product/query"
DOWNLOAD_URL = f"{API_BASE}/api/etf/product/download-file"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "raw" / "prospectus"

ETF_CATES = [
    "國內成分股ETF",
    "國外成分股ETF",
    "債券及固定收益ETF",
    "原型期貨ETF",
    "槓桿型及反向型ETF",
    "槓桿型及反向型期貨ETF",
    "多資產ETF",
]


def _post(url: str, payload: dict, expect_json: bool = True) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json" if expect_json else "*/*",
            "Origin": API_BASE,
            "Referer": f"{API_BASE}/etf/product",
            "User-Agent": "Mozilla/5.0 (fundclear-cli)",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read()


def query_all(page_size: int = 500) -> list[dict]:
    payload = {
        "_pageSize": page_size,
        "_pageNum": 1,
        "column": "",
        "asc": True,
        "searchName": "",
        "etfType": "",
        "etfStatus": "",
        "etfCate": ETF_CATES,
        "minAmount": "0",
        "maxAmount": "99999",
        "minClosingPrice": "0",
        "maxClosingPrice": "9999",
        "listingDateStart": "",
        "listingDateEnd": "",
        "minBeneficiary": "",
        "maxBeneficiary": "",
    }
    status, raw = _post(QUERY_URL, payload)
    if status != 200:
        raise RuntimeError(f"query failed: HTTP {status}")
    data = json.loads(raw.decode("utf-8"))
    return data.get("list", [])


def find_etf(code: str, rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else query_all()
    code_u = code.upper()
    for r in rows:
        if r.get("stockNo", "").upper() == code_u:
            return r
    raise LookupError(f"ETF {code} not found in FundClear")


def download_pdf(file_name: str) -> bytes:
    status, raw = _post(DOWNLOAD_URL, {"fileName": file_name}, expect_json=False)
    if status != 200 or not raw.startswith(b"%PDF-"):
        raise RuntimeError(
            f"download failed: HTTP {status}, head={raw[:40]!r}"
        )
    return raw


def _active_only(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("name", "").startswith("主動")]


# ── Commands ──────────────────────────────────────────────


def cmd_list(args) -> int:
    rows = query_all()
    rows = rows if args.all else _active_only(rows)
    rows.sort(key=lambda r: r.get("stockNo", ""))
    if args.raw:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if args.json:
        out = [
            {
                "code": r["stockNo"],
                "name": r["name"],
                "listing_date": r.get("listingDate"),
                "issuer": r.get("issuer"),
                "total_av_yi": r.get("totalAv"),
                "prospectus_file": r.get("detail3"),
            }
            for r in rows
        ]
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    print(f"{'代號':<8} {'名稱':<22} {'上市':<10} {'規模(億)':>10}  說明書")
    print("-" * 88)
    for r in rows:
        code = r.get("stockNo", "")
        name = r.get("name", "")
        ld = r.get("listingDate", "")
        ld_fmt = f"{ld[:4]}-{ld[4:6]}-{ld[6:]}" if len(ld) == 8 else ld
        size = r.get("totalAv", "")
        pdf = r.get("detail3") or "(無)"
        # 中文等寬近似
        pad_name = name + " " * max(0, 22 - sum(2 if ord(c) > 127 else 1 for c in name))
        print(f"{code:<8} {pad_name}{ld_fmt:<11} {size!s:>10}  {pdf}")
    print(f"\n合計 {len(rows)} 檔" + (" (全部)" if args.all else " (主動)"))
    return 0


def cmd_info(args) -> int:
    row = find_etf(args.code)
    if args.json:
        json.dump(row, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    for k in (
        "stockNo", "name", "listingDate", "issuer", "underlyingIndex",
        "etfCate", "totalAv", "closingPrice", "benefit",
        "detail1", "detail2", "detail3", "detail5",
    ):
        v = row.get(k, "")
        if v == "" or v is None:
            continue
        print(f"{k:<18} {v}")
    return 0


def cmd_fetch(args) -> int:
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = query_all()
    if args.all:
        targets = _active_only(rows)
    else:
        if not args.code:
            print("error: either --all or <code> required", file=sys.stderr)
            return 2
        targets = [find_etf(args.code, rows)]

    total = len(targets)
    for i, r in enumerate(targets, 1):
        code = r.get("stockNo", "?")
        fn = r.get("detail3")
        dest = out_dir / f"{code}_{fn}" if fn else None
        if not fn:
            print(f"[{i}/{total}] {code}: 無 prospectus_file，跳過", file=sys.stderr)
            continue
        if dest.exists() and not args.force:
            print(f"[{i}/{total}] {code}: 已存在 {dest.name}", file=sys.stderr)
            continue
        try:
            data = download_pdf(fn)
        except Exception as exc:
            print(f"[{i}/{total}] {code}: 失敗 {exc}", file=sys.stderr)
            continue
        dest.write_bytes(data)
        print(f"[{i}/{total}] {code}: {dest.name} ({len(data):,} bytes)")
    return 0


def cmd_extract(args) -> int:
    try:
        from pypdf import PdfReader
    except ImportError:
        print(
            "error: pypdf 未安裝。用 `uv run --with pypdf fundclear.py extract` 或先 `uv pip install pypdf`",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out).resolve()
    row = find_etf(args.code)
    fn = row.get("detail3")
    if not fn:
        print(f"error: {args.code} 無 prospectus_file", file=sys.stderr)
        return 1

    pdf_path = out_dir / f"{args.code}_{fn}"
    if not pdf_path.exists():
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        data = download_pdf(fn)
        pdf_path.write_bytes(data)
        print(f"(下載 {pdf_path.name} {len(data):,} bytes)", file=sys.stderr)

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    print(f"=== {args.code} / {fn} / {total} 頁 ===", file=sys.stderr)
    parts = []
    for i, page in enumerate(reader.pages, 1):
        txt = page.extract_text() or ""
        parts.append(f"\n\n--- page {i} ---\n\n{txt}")
    full = "".join(parts)
    if args.save:
        txt_path = out_dir / f"{args.code}_{fn.replace('.pdf', '.txt')}"
        txt_path.write_text(full, encoding="utf-8")
        print(f"寫入 {txt_path}", file=sys.stderr)
    else:
        sys.stdout.write(full)
    return 0


# ── Main ──────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        prog="fundclear",
        description="Taiwan FundClear ETF prospectus CLI",
    )
    p.add_argument("--out", default=str(DEFAULT_OUT), help=f"輸出目錄 (預設 {DEFAULT_OUT})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="列出 ETF")
    sp.add_argument("--all", action="store_true", help="列全部 ETF（預設只列主動）")
    sp.add_argument("--json", action="store_true", help="JSON 輸出")
    sp.add_argument("--raw", action="store_true", help="FundClear 原始 JSON")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("info", help="顯示單一 ETF 欄位")
    sp.add_argument("code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("fetch", help="下載公開說明書 PDF")
    sp.add_argument("code", nargs="?")
    sp.add_argument("--all", action="store_true", help="下載所有主動 ETF")
    sp.add_argument("--force", action="store_true", help="覆寫已存在檔案")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("extract", help="下載+抽文")
    sp.add_argument("code")
    sp.add_argument("--save", action="store_true", help="存成 .txt（而非印到 stdout）")
    sp.set_defaults(func=cmd_extract)

    args = p.parse_args()
    try:
        return args.func(args)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
