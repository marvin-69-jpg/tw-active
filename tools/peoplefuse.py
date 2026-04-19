#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
peoplefuse — Phase 6：把 datastore 的結構化資料渲染進 wiki/people/<slug>.md 的
AUTO 區塊，不動使用者手寫區塊。

設計：
  - 人物頁是 source of truth：frontmatter 定義 manager 的 etfs / funds（list）
  - peoplefuse render 讀 frontmatter → subprocess `datastore.py query` → 把結果
    塞入 <!-- AUTO:START --> ... <!-- AUTO:END --> 中間
  - 手寫區塊（marker 之外）絕不動

Subcommands:
  list                        列出 wiki/people/*.md 有 frontmatter 的人物
  render <slug>               渲染單一人物頁（覆寫 AUTO 區塊）
  render --all                全渲染
  diff <slug>                 印出雙軌差距表（不寫檔，stdout）
  init <slug>                 建立空 frontmatter 樣板（idempotent）

Frontmatter 格式（YAML-lite，手寫可維護）：
  ---
  name: 陳釧瑤
  slug: chen-chuan-yao
  company: A0009
  company_name: 統一投信
  etfs: [00981A]
  funds:
    - 統一台股增長主動式ETF基金
  aliases: [Chuan-Yao Chen]
  ---

AUTO 區塊格式（覆寫目標）：
  <!-- AUTO:START peoplefuse v1 | generated YYYY-MM-DDTHH:MM -->
  ...渲染內容...
  <!-- AUTO:END -->

Usage:
  ./tools/peoplefuse.py list
  ./tools/peoplefuse.py init chen-chuan-yao
  ./tools/peoplefuse.py render chen-chuan-yao
  ./tools/peoplefuse.py render --all
  ./tools/peoplefuse.py diff chen-chuan-yao
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PEOPLE_DIR = REPO / "wiki" / "people"
DATASTORE = HERE / "datastore.py"
SIGNALS = HERE / "signals.py"

AUTO_START_RE = re.compile(r"<!-- AUTO:START peoplefuse[^>]*-->")
AUTO_END = "<!-- AUTO:END -->"


# ---------------------------------------------------------------------------
# Frontmatter (minimal YAML subset)
# ---------------------------------------------------------------------------
def read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """回 (frontmatter_dict, body_str)。無 frontmatter 則 dict 空，body=全文。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    return _parse_yaml_lite(fm_text), body


def _parse_yaml_lite(s: str) -> dict[str, Any]:
    """支援：key: value、key: [a, b]、key: 後多行 `  - item` list。"""
    out: dict[str, Any] = {}
    cur_key: str | None = None
    for line in s.splitlines():
        if not line.strip():
            continue
        m_item = re.match(r"^\s+-\s+(.*)$", line)
        if m_item and cur_key:
            out.setdefault(cur_key, []).append(m_item.group(1).strip().strip('"').strip("'"))
            continue
        m_kv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not m_kv:
            continue
        key = m_kv.group(1)
        val = m_kv.group(2).strip()
        if val == "":
            # 接下來可能是 list
            out[key] = []
            cur_key = key
            continue
        # inline list?
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
            out[key] = items
        else:
            out[key] = val.strip('"').strip("'")
        cur_key = key
    return out


def dump_frontmatter(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            if all(len(str(x)) < 20 for x in v) and len(v) <= 4:
                lines.append(f"{k}: [{', '.join(v)}]")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Datastore / signals subprocess helpers
# ---------------------------------------------------------------------------
def _run_json(argv: list[str]) -> Any:
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=REPO, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess failed: {' '.join(argv)}\nstderr: {proc.stderr.strip()[:400]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON from {argv[0]}: {e}\nstdout head: {proc.stdout[:200]}")


def _run_jsonl(argv: list[str]) -> list[dict]:
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=REPO, check=False
    )
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def query_etf_holdings(etf: str) -> list[dict]:
    return _run_json([
        str(DATASTORE), "query", "holdings", "--etf", etf, "--json"
    ])


def query_fund_monthly(fund_name: str, ym: str | None = None) -> list[dict]:
    argv = [str(DATASTORE), "query", "fund", "--name", fund_name, "--json"]
    if ym:
        argv += ["--ym", ym]
    return _run_json(argv)


def query_signal_4(month: str, threshold: int = 3) -> list[dict]:
    return _run_jsonl([
        str(SIGNALS), "detect", "4", "--month", month, "--threshold", str(threshold),
    ])


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------
def _latest_ym_from_rows(rows: list[dict]) -> str | None:
    yms = sorted({r.get("ym") for r in rows if r.get("ym")})
    return yms[-1] if yms else None


def _latest_etf_date_from_rows(rows: list[dict]) -> str | None:
    ds = sorted({r.get("data_date") for r in rows if r.get("data_date")})
    return ds[-1] if ds else None


def render_etf_section(etf: str, rows: list[dict]) -> str:
    if not rows:
        return f"### ETF 持股：{etf}\n\n（datastore 查無資料）\n"
    latest = _latest_etf_date_from_rows(rows)
    latest_rows = [r for r in rows if r.get("data_date") == latest]
    # stock 部位 top 15 按權重
    stock = [r for r in latest_rows if r.get("kind") == "stock"]
    stock.sort(key=lambda r: -(r.get("weight_pct") or 0))
    top = stock[:15]
    lines = [f"### ETF 持股 {etf}（{latest}，top 15 股票）\n"]
    lines.append("| code | name | weight % | shares |")
    lines.append("|---|---|---:|---:|")
    for r in top:
        weight = r.get("weight_pct")
        shares = r.get("shares")
        lines.append(
            f"| {r.get('code','')} | {r.get('name','')} | "
            f"{weight if weight is not None else '—':.2f} | "
            f"{int(shares) if shares else '—':,} |"
            if isinstance(shares, (int, float)) and isinstance(weight, (int, float))
            else f"| {r.get('code','')} | {r.get('name','')} | {weight} | {shares} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_fund_section(fund_name: str, rows: list[dict]) -> str:
    if not rows:
        return f"### 基金月報：{fund_name}\n\n（datastore 查無資料）\n"
    # 找最近 3 個月 ym
    yms = sorted({r.get("ym") for r in rows if r.get("ym")})[-3:]
    recent = [r for r in rows if r.get("ym") in yms]
    # 取 top 10 按最新月 rank
    latest_ym = yms[-1]
    latest_top10 = sorted(
        [r for r in recent if r.get("ym") == latest_ym],
        key=lambda r: r.get("rank") or 99,
    )
    codes_in_order = [r.get("code") for r in latest_top10 if r.get("code")]
    # 建 time-series dict: code -> {ym: pct}
    by_code: dict[str, dict[str, float]] = {}
    code_name: dict[str, str] = {}
    for r in recent:
        code = r.get("code")
        if not code:
            continue
        by_code.setdefault(code, {})[r.get("ym")] = r.get("pct")
        if r.get("name"):
            code_name[code] = r["name"]
    lines = [f"### 基金月報 Top 10 時序：{fund_name}（最近 3 月）\n"]
    header = "| code | name | " + " | ".join(yms) + " |"
    lines.append(header)
    lines.append("|---|---|" + "---:|" * len(yms))
    for code in codes_in_order:
        row = [
            code,
            code_name.get(code, ""),
        ]
        for ym in yms:
            pct = by_code.get(code, {}).get(ym)
            row.append(f"{pct:.2f}" if isinstance(pct, (int, float)) else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def render_dual_track(
    etf_rows: list[dict],
    fund_rows: list[dict],
    etf: str,
    fund_name: str,
) -> str:
    """雙軌差距：同一 code 在 ETF 權重 vs 基金 Top 10 權重。"""
    etf_latest = _latest_etf_date_from_rows(etf_rows)
    fund_latest = _latest_ym_from_rows(fund_rows)
    if not etf_latest or not fund_latest:
        return ""
    etf_map: dict[str, dict] = {
        r["code"]: r for r in etf_rows if r.get("data_date") == etf_latest and r.get("kind") == "stock"
    }
    fund_map: dict[str, dict] = {
        r["code"]: r for r in fund_rows if r.get("ym") == fund_latest
    }
    common = sorted(set(etf_map) & set(fund_map))
    rows = []
    for code in common:
        e = etf_map[code]
        f = fund_map[code]
        ew = e.get("weight_pct") or 0
        fp = f.get("pct") or 0
        rows.append({
            "code": code,
            "name": e.get("name") or f.get("name") or "",
            "etf_weight": ew,
            "fund_pct": fp,
            "delta_pp": round(ew - fp, 2),
        })
    rows.sort(key=lambda r: -abs(r["delta_pp"]))
    lines = [
        f"### 雙軌差距（ETF {etf} @ {etf_latest} vs 基金 {fund_name} @ {fund_latest}）\n"
    ]
    lines.append(f"交集：{len(common)} 檔；差距按絕對值排序取 top 10\n")
    lines.append("| code | name | ETF % | 基金 % | Δpp |")
    lines.append("|---|---|---:|---:|---:|")
    for r in rows[:10]:
        lines.append(
            f"| {r['code']} | {r['name']} | "
            f"{r['etf_weight']:.2f} | {r['fund_pct']:.2f} | {r['delta_pp']:+.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_signal_section(fund_names: list[str], month: str) -> str:
    try:
        hits = query_signal_4(month, threshold=1)
    except Exception as e:
        return f"### 訊號命中\n\n（signals.py 查詢失敗：{e}）\n"
    if not hits:
        return "### 訊號命中\n\n（當月無命中）\n"
    # 找和 manager 的基金有交集的 code
    hit_lines = []
    for h in hits:
        funds_in_hit = h.get("funds", [])
        intersect = [f for f in fund_names if any(fn in f or f in fn for fn in funds_in_hit)]
        if not intersect:
            continue
        hit_lines.append(
            f"- **#4 多基金共識** {h['code']} {h['name']}：被 {h['n_funds']} 檔基金持有"
            f"（合計 {h['total_pct']:.2f}%），含本人管理的 {intersect[0]}"
        )
    if not hit_lines:
        return f"### 訊號命中（@ {month}）\n\n（當月本人基金未在共識 hit）\n"
    return f"### 訊號命中（signal 4 @ {month}）\n\n" + "\n".join(hit_lines) + "\n"


# ---------------------------------------------------------------------------
# Core render
# ---------------------------------------------------------------------------
def render_auto_block(fm: dict[str, Any]) -> str:
    etfs = fm.get("etfs") or []
    funds = fm.get("funds") or []
    parts: list[str] = []
    etf_rows_cache: dict[str, list[dict]] = {}
    fund_rows_cache: dict[str, list[dict]] = {}

    for etf in etfs:
        try:
            rows = query_etf_holdings(etf)
        except Exception as e:
            parts.append(f"### ETF 持股 {etf}\n\n（查詢失敗：{e}）\n")
            continue
        etf_rows_cache[etf] = rows
        parts.append(render_etf_section(etf, rows))

    for fund in funds:
        try:
            rows = query_fund_monthly(fund)
        except Exception as e:
            parts.append(f"### 基金月報：{fund}\n\n（查詢失敗：{e}）\n")
            continue
        fund_rows_cache[fund] = rows
        parts.append(render_fund_section(fund, rows))

    # 雙軌差距（只對第一組 etf + fund）
    if etfs and funds:
        etf = etfs[0]
        fund = funds[0]
        if etf in etf_rows_cache and fund in fund_rows_cache:
            dual = render_dual_track(etf_rows_cache[etf], fund_rows_cache[fund], etf, fund)
            if dual:
                parts.append(dual)

    # 訊號命中
    latest_ym = None
    for rows in fund_rows_cache.values():
        ym = _latest_ym_from_rows(rows)
        if ym and (latest_ym is None or ym > latest_ym):
            latest_ym = ym
    if latest_ym and funds:
        parts.append(render_signal_section(funds, latest_ym))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    header = f"<!-- AUTO:START peoplefuse v1 | generated {ts}Z -->"
    footer = AUTO_END
    body = "\n\n".join(p.strip() for p in parts if p.strip())
    return f"{header}\n\n{body}\n\n{footer}"


def splice_auto_block(body: str, new_block: str) -> str:
    """在 body 中找 AUTO 區塊並替換；若無則 append 到末尾。"""
    m_start = AUTO_START_RE.search(body)
    if not m_start:
        sep = "\n\n" if not body.endswith("\n\n") else ""
        return body.rstrip() + "\n\n" + new_block + "\n"
    start = m_start.start()
    end_idx = body.find(AUTO_END, m_start.end())
    if end_idx < 0:
        # 缺收尾，保守地 append 新區塊
        return body[:start].rstrip() + "\n\n" + new_block + "\n"
    end = end_idx + len(AUTO_END)
    return body[:start] + new_block + body[end:]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> None:
    if not PEOPLE_DIR.exists():
        print(f"error: {PEOPLE_DIR} 不存在", file=sys.stderr)
        sys.exit(2)
    rows = []
    for path in sorted(PEOPLE_DIR.glob("*.md")):
        if path.name == "index.md":
            continue
        fm, _ = read_frontmatter(path)
        if not fm.get("name"):
            rows.append((path.name, "—", "—", "—"))
            continue
        rows.append((
            path.name,
            fm.get("name", "—"),
            ",".join(fm.get("etfs", [])) or "—",
            f"{len(fm.get('funds') or [])} funds" if fm.get("funds") else "—",
        ))
    if not rows:
        print("（目前 wiki/people/ 沒有可渲染的人物頁，先用 `init <slug>` 建）")
        return
    print(f"{'file':<30} {'name':<16} {'etfs':<12} {'funds'}")
    for r in rows:
        print(f"{r[0]:<30} {r[1]:<16} {r[2]:<12} {r[3]}")


def cmd_init(args: argparse.Namespace) -> None:
    slug = args.slug
    path = PEOPLE_DIR / f"{slug}.md"
    if path.exists():
        fm, body = read_frontmatter(path)
        if fm:
            print(f"{path} 已有 frontmatter，略過", file=sys.stderr)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "company": "TBD",
        "company_name": "TBD",
        "etfs": [],
        "funds": [],
        "aliases": [],
    }
    body = (
        f"# {fm['name']}\n\n"
        "## 角色\n\n（手寫）\n\n"
        "## 研究備註\n\n（手寫，peoplefuse 不會動本區塊）\n\n"
        f"{AUTO_START_RE.pattern.replace(chr(92), '')}\n\n"
        "（尚未 render；跑 `./tools/peoplefuse.py render " + slug + "`）\n\n"
        f"{AUTO_END}\n"
    )
    # 修正：AUTO_START 用確定字串
    body = re.sub(
        r"<!-- AUTO:START peoplefuse\[\^>\]\*-->",
        "<!-- AUTO:START peoplefuse v1 -->",
        body,
    )
    content = dump_frontmatter(fm) + body
    path.write_text(content, encoding="utf-8")
    print(f"created {path}")


def cmd_render_one(slug: str) -> None:
    path = PEOPLE_DIR / f"{slug}.md"
    if not path.exists():
        print(f"error: {path} 不存在（用 `init {slug}`）", file=sys.stderr)
        sys.exit(2)
    fm, body = read_frontmatter(path)
    if not fm:
        print(f"error: {path} 無 frontmatter", file=sys.stderr)
        sys.exit(2)
    new_block = render_auto_block(fm)
    new_body = splice_auto_block(body, new_block)
    content = dump_frontmatter(fm) + new_body
    path.write_text(content, encoding="utf-8")
    print(f"rendered {path}")


def cmd_render(args: argparse.Namespace) -> None:
    if args.all:
        for p in sorted(PEOPLE_DIR.glob("*.md")):
            if p.name == "index.md":
                continue
            fm, _ = read_frontmatter(p)
            if fm.get("etfs") or fm.get("funds"):
                cmd_render_one(p.stem)
        return
    if not args.slug:
        print("error: slug 必填（或 --all）", file=sys.stderr)
        sys.exit(2)
    cmd_render_one(args.slug)


def cmd_diff(args: argparse.Namespace) -> None:
    path = PEOPLE_DIR / f"{args.slug}.md"
    if not path.exists():
        print(f"error: {path} 不存在", file=sys.stderr)
        sys.exit(2)
    fm, _ = read_frontmatter(path)
    etfs = fm.get("etfs") or []
    funds = fm.get("funds") or []
    if not etfs or not funds:
        print("error: frontmatter 缺 etfs 或 funds", file=sys.stderr)
        sys.exit(2)
    etf_rows = query_etf_holdings(etfs[0])
    fund_rows = query_fund_monthly(funds[0])
    print(render_dual_track(etf_rows, fund_rows, etfs[0], funds[0]))


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="peoplefuse",
        description="Phase 6：渲染 wiki/people/<slug>.md AUTO 區塊（datastore × signals）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="列出 people 頁 + frontmatter 概覽")
    ls.set_defaults(func=cmd_list)

    it = sub.add_parser("init", help="建立空 frontmatter 樣板")
    it.add_argument("slug")
    it.set_defaults(func=cmd_init)

    r = sub.add_parser("render", help="渲染 AUTO 區塊")
    r.add_argument("slug", nargs="?")
    r.add_argument("--all", action="store_true")
    r.set_defaults(func=cmd_render)

    d = sub.add_parser("diff", help="印雙軌差距表（stdout）")
    d.add_argument("slug")
    d.set_defaults(func=cmd_diff)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
