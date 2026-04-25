#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
papers — 學術論文 fetcher，薄 wrapper 包 paper-search-mcp + NBER 直抓。

設計：
- 多源搜尋 / 下載 / 讀取 → 委派 `/home/node/paper-search-mcp` 的 paper-search CLI
  （該 repo 已實作 arxiv/crossref/openalex/semantic/ssrn 等 20+ source）
- NBER WP → 自己 curl，因為 paper-search-mcp 沒有 NBER connector
- PDF 統一存到 raw/papers/，metadata 寫到 raw/papers/<id>.json

Usage:
  papers search "<query>" -s arxiv,crossref -n 5
  papers download <source> <paper_id>      # source ∈ arxiv/ssrn/biorxiv/...
  papers download nber <wp_number>         # e.g. nber 19891 → w19891.pdf
  papers read <source> <paper_id>          # extract text
  papers sources                            # list available sources
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PAPERS_DIR = REPO_ROOT / "raw" / "papers"
UPSTREAM = "/home/node/paper-search-mcp"


def _upstream(*args: str) -> int:
    """Pipe through to upstream paper-search CLI."""
    cmd = ["uv", "run", "--directory", UPSTREAM, "paper-search", *args]
    return subprocess.call(cmd)


def cmd_nber(wp_number: str, out_dir: Path) -> int:
    wp = wp_number.lstrip("w").lstrip("W")
    url = f"https://www.nber.org/system/files/working_papers/w{wp}/w{wp}.pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nber_w{wp}.pdf"
    print(f"GET {url}", file=sys.stderr)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 papers-cli"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out_path.write_bytes(r.read())
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 1
    print(json.dumps({"status": "ok", "path": str(out_path), "source": "nber"}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="multi-source 搜尋")
    sp.add_argument("query")
    sp.add_argument("-n", default="5")
    sp.add_argument("-s", default="arxiv,crossref,openalex")
    sp.add_argument("-y", default=None, help="year filter for semantic")

    dl = sub.add_parser("download", help="下載 PDF（source ∈ arxiv/ssrn/nber/...）")
    dl.add_argument("source")
    dl.add_argument("paper_id")
    dl.add_argument("-o", default=str(PAPERS_DIR))

    rd = sub.add_parser("read", help="extract 全文")
    rd.add_argument("source")
    rd.add_argument("paper_id")
    rd.add_argument("-o", default=str(PAPERS_DIR))

    sub.add_parser("sources", help="列出可用 source")

    args = p.parse_args()

    if args.cmd == "search":
        a = ["search", args.query, "-n", args.n, "-s", args.s]
        if args.y:
            a += ["-y", args.y]
        return _upstream(*a)

    if args.cmd == "download":
        if args.source.lower() == "nber":
            return cmd_nber(args.paper_id, Path(args.o))
        return _upstream("download", args.source, args.paper_id, "-o", args.o)

    if args.cmd == "read":
        return _upstream("read", args.source, args.paper_id, "-o", args.o)

    if args.cmd == "sources":
        rc = _upstream("sources")
        print("\n# 補充: nber（本地 curl 直抓 NBER WP PDF）", file=sys.stderr)
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
