#!/usr/bin/env python3
"""
fetch_threads_archive — 把 opus_666999 帳號的 Threads 發文歷史撈下來存檔。

讀 ~/.threads-token 和 ~/.threads-user-id，呼叫 Threads Graph API
列出全部發文，寫到 reports/threads/archive.md（人類閱讀）+
reports/threads/archive.jsonl（grep / programmatic 用）。

Usage:
  fetch_threads_archive.py          # 重建 archive
  fetch_threads_archive.py --limit 200
"""

import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "threads"


def load_creds() -> tuple[str, str]:
    home = pathlib.Path.home()
    token = (home / ".threads-token").read_text().strip()
    uid = (home / ".threads-user-id").read_text().strip()
    return token, uid


def fetch_all(token: str, uid: str, hard_limit: int = 500) -> list[dict]:
    posts: list[dict] = []
    url = f"https://graph.threads.net/v1.0/{uid}/threads?" + urllib.parse.urlencode({
        "fields": "id,text,permalink,timestamp,media_type,media_url",
        "limit": "100",
        "access_token": token,
    })
    while url:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
            data = json.load(r)
        posts.extend(data.get("data", []))
        nxt = data.get("paging", {}).get("next")
        if not nxt or len(posts) >= hard_limit:
            break
        url = nxt
    posts.sort(key=lambda p: p.get("timestamp", ""))
    return posts


def write_markdown(posts: list[dict], path: pathlib.Path) -> None:
    lines = [
        "# Threads 發文歷史存檔",
        "",
        "> opus_666999 帳號發文歷史，由 Threads Graph API 撈出。",
        "> 重建：`tools/fetch_threads_archive.py`",
        "",
        f"共 {len(posts)} 篇（最舊→最新）。",
        "",
        "---",
        "",
    ]
    for p in posts:
        ts = p.get("timestamp", "")
        pid = p.get("id", "")
        mt = p.get("media_type", "")
        perma = p.get("permalink", "")
        text = (p.get("text") or "").strip()
        lines.append(f"## {ts}  ·  {mt}  ·  `{pid}`")
        lines.append("")
        if perma:
            lines.append(f"<{perma}>")
            lines.append("")
        lines.append(text if text else "_(no text)_")
        lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_jsonl(posts: list[dict], path: pathlib.Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps({
                "id": p.get("id"),
                "timestamp": p.get("timestamp"),
                "media_type": p.get("media_type"),
                "permalink": p.get("permalink"),
                "text": p.get("text") or "",
            }, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500, help="hard cap on posts fetched")
    args = ap.parse_args()

    token, uid = load_creds()
    posts = fetch_all(token, uid, hard_limit=args.limit)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_markdown(posts, OUT_DIR / "archive.md")
    write_jsonl(posts, OUT_DIR / "archive.jsonl")
    print(f"wrote {len(posts)} posts to {OUT_DIR}/archive.{{md,jsonl}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
