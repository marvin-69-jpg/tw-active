#!/usr/bin/env python3
"""
threads — CLI for posting to Threads.

讀 ~/.threads-token 和 ~/.threads-user-id，發文到認證的 Threads 帳號。

Subcommands:
  whoami                查 token 認證的帳號（驗證 token 還能用）
  post <file|->         發單篇文章（500 字元上限）
  thread <file|->       發 thread chain（每段用 "---" 分隔，自動接 reply chain）
  preview <file|->      只切段、不發，看分段結果

Usage:
  threads.py whoami
  threads.py post reports/threads/2026-04-17-daily.md
  threads.py thread reports/threads/2026-04-17-daily.md --dry-run
  cat post.txt | threads.py post -
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".threads-token"
USER_ID_FILE = Path.home() / ".threads-user-id"
API_BASE = "https://graph.threads.net/v1.0"

# Threads single post hard limit
MAX_CHARS = 500
# Recommended buffer: leave room for trailing thread index "(1/N)"
SAFE_CHARS = 480

# Recommended wait between container creation and publish (Meta docs)
PUBLISH_DELAY_SEC = 30


# ── credentials ──────────────────────────────────────────


def load_creds() -> tuple[str, str]:
    if not TOKEN_FILE.exists():
        sys.exit(f"✗ {TOKEN_FILE} 不存在。先跑 tools/threads_setup.py 或手動填好。")
    if not USER_ID_FILE.exists():
        sys.exit(f"✗ {USER_ID_FILE} 不存在。")
    token = TOKEN_FILE.read_text().strip()
    user_id = USER_ID_FILE.read_text().strip()
    if not token or not user_id:
        sys.exit("✗ token 或 user_id 檔案是空的")
    return token, user_id


# ── http helpers ─────────────────────────────────────────


def _request(method: str, url: str, params: dict | None = None) -> dict:
    body = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = {"error": str(e)}
        sys.exit(f"✗ {method} {url} → HTTP {e.code}: {json.dumps(err, ensure_ascii=False)}")


# ── markdown → plain text ────────────────────────────────


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter if present."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def md_to_plain(text: str) -> str:
    """Light markdown → plain text. Threads doesn't render markdown."""
    text = strip_frontmatter(text)
    # Strip H1/H2/etc heading markers but keep the text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # **bold** → bold (drop markers)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # *italic* / _italic_ → drop markers
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"\1", text)
    # `code` → drop backticks
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)
    # [text](url) → text (url) so link is visible
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── splitting for thread chains ──────────────────────────


def split_into_segments(text: str) -> list[str]:
    """
    Split text into Threads-postable segments.

    Rules:
    1. If author wrote explicit "---" separators, honor them.
    2. Otherwise, greedy-pack paragraphs (separated by blank lines)
       up to SAFE_CHARS per segment, never breaking a paragraph mid-way
       unless it alone exceeds SAFE_CHARS.
    3. A paragraph longer than SAFE_CHARS is split at sentence boundaries.
    """
    text = text.strip()

    if "\n---\n" in text or "\n--- \n" in text:
        explicit = re.split(r"\n---\s*\n", text)
        return [s.strip() for s in explicit if s.strip()]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    segments: list[str] = []
    cur = ""
    for p in paragraphs:
        # Paragraph itself too long → split by sentences
        if len(p) > SAFE_CHARS:
            if cur:
                segments.append(cur.strip())
                cur = ""
            segments.extend(_split_long_paragraph(p))
            continue

        candidate = (cur + "\n\n" + p) if cur else p
        if len(candidate) <= SAFE_CHARS:
            cur = candidate
        else:
            if cur:
                segments.append(cur.strip())
            cur = p
    if cur:
        segments.append(cur.strip())

    return segments


def _split_long_paragraph(p: str) -> list[str]:
    """Split an oversized paragraph at sentence boundaries (。！？.!?)."""
    sentences = re.split(r"(?<=[。！？.!?])\s*", p)
    sentences = [s for s in sentences if s.strip()]
    out: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > SAFE_CHARS:
            # Hard fallback: chunk by char count
            if cur:
                out.append(cur)
                cur = ""
            for i in range(0, len(s), SAFE_CHARS):
                out.append(s[i : i + SAFE_CHARS])
            continue
        candidate = (cur + s) if cur else s
        if len(candidate) <= SAFE_CHARS:
            cur = candidate
        else:
            if cur:
                out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return out


def add_thread_indices(segments: list[str]) -> list[str]:
    """If multiple segments, append (i/N) to each so readers can navigate."""
    n = len(segments)
    if n <= 1:
        return segments
    return [f"{seg}\n\n({i}/{n})" for i, seg in enumerate(segments, 1)]


# ── posting ──────────────────────────────────────────────


def create_text_container(
    user_id: str, token: str, text: str, reply_to_id: str | None = None
) -> str:
    params = {"media_type": "TEXT", "text": text, "access_token": token}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    resp = _request("POST", f"{API_BASE}/{user_id}/threads", params)
    if "id" not in resp:
        sys.exit(f"✗ create container 沒回 id: {resp}")
    return resp["id"]


def publish_container(user_id: str, token: str, creation_id: str) -> str:
    params = {"creation_id": creation_id, "access_token": token}
    resp = _request("POST", f"{API_BASE}/{user_id}/threads_publish", params)
    if "id" not in resp:
        sys.exit(f"✗ publish 沒回 id: {resp}")
    return resp["id"]


def post_one(
    user_id: str,
    token: str,
    text: str,
    reply_to_id: str | None = None,
    delay_sec: int = PUBLISH_DELAY_SEC,
) -> str:
    container = create_text_container(user_id, token, text, reply_to_id)
    if delay_sec > 0:
        time.sleep(delay_sec)
    return publish_container(user_id, token, container)


# ── input loading ────────────────────────────────────────


def load_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    p = Path(source)
    if not p.exists():
        sys.exit(f"✗ 檔案不存在: {p}")
    return p.read_text()


# ── commands ─────────────────────────────────────────────


def cmd_whoami(_args) -> int:
    token, user_id = load_creds()
    resp = _request(
        "GET",
        f"{API_BASE}/me?fields=id,username&access_token={urllib.parse.quote(token)}",
    )
    print(f"username: {resp.get('username', '?')}")
    print(f"id:       {resp.get('id', '?')}")
    print(f"matches:  {resp.get('id') == user_id}")
    return 0


def cmd_preview(args) -> int:
    raw = load_text(args.source)
    text = md_to_plain(raw)
    segments = split_into_segments(text)
    if args.index:
        segments = add_thread_indices(segments)
    print(f"── {len(segments)} segment(s), max {MAX_CHARS} chars each ──\n")
    for i, seg in enumerate(segments, 1):
        print(f"─── segment {i}/{len(segments)}  ({len(seg)} chars) ───")
        print(seg)
        print()
    if any(len(s) > MAX_CHARS for s in segments):
        print(f"⚠ 有段落超過 {MAX_CHARS} 字元上限，發文會失敗")
        return 1
    return 0


def cmd_post(args) -> int:
    token, user_id = load_creds()
    raw = load_text(args.source)
    text = md_to_plain(raw)

    if len(text) > MAX_CHARS:
        sys.exit(
            f"✗ 文章 {len(text)} 字元，超過 Threads 單篇 {MAX_CHARS} 上限。"
            " 用 `threads.py thread` 自動切段，或縮短內容。"
        )

    if args.dry_run:
        print(f"[dry-run] 會發單篇 ({len(text)} chars):")
        print("─" * 40)
        print(text)
        return 0

    print(f"發文 ({len(text)} chars)...")
    post_id = post_one(user_id, token, text, delay_sec=args.delay)
    print(f"✓ posted: {post_id}")
    return 0


def cmd_thread(args) -> int:
    token, user_id = load_creds()
    raw = load_text(args.source)
    text = md_to_plain(raw)
    segments = split_into_segments(text)
    if args.index and len(segments) > 1:
        segments = add_thread_indices(segments)

    if any(len(s) > MAX_CHARS for s in segments):
        sys.exit(f"✗ 切完仍有段落 > {MAX_CHARS} 字元，無法發。先 preview 看哪段。")

    if args.dry_run:
        print(f"[dry-run] 會發 {len(segments)} 篇 thread:")
        for i, seg in enumerate(segments, 1):
            print(f"\n─── {i}/{len(segments)} ({len(seg)} chars) ───")
            print(seg)
        return 0

    print(f"發 thread chain，{len(segments)} 篇...")
    parent_id: str | None = None
    posted_ids: list[str] = []
    for i, seg in enumerate(segments, 1):
        print(f"  [{i}/{len(segments)}] 建 container...")
        post_id = post_one(
            user_id, token, seg, reply_to_id=parent_id, delay_sec=args.delay
        )
        print(f"  [{i}/{len(segments)}] ✓ posted: {post_id}")
        posted_ids.append(post_id)
        parent_id = post_id
    print(f"\n✓ thread complete, {len(posted_ids)} posts")
    print(f"  root: {posted_ids[0]}")
    return 0


# ── main ─────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(prog="threads", description="Post to Threads")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="show authenticated account")

    p_post = sub.add_parser("post", help="post a single thread (≤500 chars)")
    p_post.add_argument("source", help="path to .md file, or '-' for stdin")
    p_post.add_argument("--dry-run", action="store_true")
    p_post.add_argument(
        "--delay", type=int, default=PUBLISH_DELAY_SEC,
        help=f"seconds to wait between create+publish (default {PUBLISH_DELAY_SEC})",
    )

    p_thread = sub.add_parser("thread", help="post as thread chain, auto-split")
    p_thread.add_argument("source")
    p_thread.add_argument("--dry-run", action="store_true")
    p_thread.add_argument("--no-index", dest="index", action="store_false", default=True,
                          help="skip (i/N) trailers")
    p_thread.add_argument("--delay", type=int, default=PUBLISH_DELAY_SEC)

    p_prev = sub.add_parser("preview", help="show how text splits, don't post")
    p_prev.add_argument("source")
    p_prev.add_argument("--no-index", dest="index", action="store_false", default=True)

    args = parser.parse_args()

    cmds = {
        "whoami": cmd_whoami,
        "post": cmd_post,
        "thread": cmd_thread,
        "preview": cmd_preview,
    }
    return cmds[args.cmd](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\n✗ 中斷")
