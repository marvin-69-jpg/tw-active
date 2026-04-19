#!/usr/bin/env python3
"""
threads_setup — Interactive Threads API OAuth helper.

走完整個 Meta OAuth flow，把 long-lived token 和 user ID 寫到 PVC。
Token 不會 echo 到 stdout，不會留在 shell history。

Usage:
  python3 tools/threads_setup.py

需要先在 Meta App Dashboard 設好：
  - Threads use case 已啟用
  - Permissions: threads_basic + threads_content_publish
  - Redirect Callback URL: 已加入一個公開 https URL
"""

import getpass
import json
import os
import stat
import sys
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".threads-token"
USER_ID_FILE = Path.home() / ".threads-user-id"


def http_post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def http_get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def write_secret(path: Path, value: str) -> None:
    """Write atomically with 600 perms, never echoing the value."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value.strip() + "\n")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)


def prompt_secret(label: str) -> str:
    val = getpass.getpass(f"{label}: ").strip()
    if not val:
        sys.exit(f"✗ {label} 不能空白")
    return val


def prompt_visible(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or (default or "")


def main() -> int:
    print("=" * 60)
    print("Threads API OAuth Setup")
    print("=" * 60)
    print()
    print("這個工具會帶你走完 Meta OAuth flow，把 long-lived token")
    print(f"寫到 {TOKEN_FILE}（chmod 600）。Token 全程不會 echo 出來。")
    print()

    # --- Step 1: collect app credentials ---
    print("─── Step 1/4: App 資訊 ───")
    print("到 https://developers.facebook.com/apps/ 你的 app 找：")
    print("  - Use cases → Threads → Settings 的 'Threads app ID'")
    print("  - App settings → Basic 的 'App Secret'")
    print()
    app_id = prompt_visible("Threads App ID（公開值，可顯示）")
    if not app_id.isdigit():
        sys.exit("✗ App ID 應該是純數字")
    app_secret = prompt_secret("App Secret（輸入時不顯示）")
    redirect_uri = prompt_visible(
        "Redirect Callback URL",
        default="https://marvin-69-jpg.github.io/threads-callback",
    )

    # --- Step 2: print authorize URL ---
    print()
    print("─── Step 2/4: 在瀏覽器授權 ───")
    auth_params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "threads_basic,threads_content_publish",
        "response_type": "code",
    }
    auth_url = "https://threads.net/oauth/authorize?" + urllib.parse.urlencode(auth_params)
    print()
    print("把下面整段 URL 貼到瀏覽器：")
    print()
    print(auth_url)
    print()
    print("授權後瀏覽器會跳到（可能顯示 404，無所謂）：")
    print(f"  {redirect_uri}?code=AQB....#_")
    print()
    print("複製網址列裡 code= 後面、#_ 之前的字串。")
    print()
    code = prompt_secret("Authorization code（輸入時不顯示）")

    # --- Step 3: exchange code → short-lived token + user_id ---
    print()
    print("─── Step 3/4: 換 short-lived token ───")
    try:
        short = http_post(
            "https://graph.threads.net/oauth/access_token",
            {
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"✗ Step 3 失敗（HTTP {e.code}）：{body}")

    if "access_token" not in short:
        sys.exit(f"✗ Step 3 回傳缺 access_token：{short}")

    short_token = short["access_token"]
    user_id = str(short.get("user_id", ""))
    if not user_id:
        sys.exit("✗ Step 3 回傳缺 user_id")
    print(f"✓ 拿到 short-lived token + user_id ({user_id})")

    # --- Step 4: exchange short → long-lived token ---
    print()
    print("─── Step 4/4: 換 long-lived token ───")
    long_url = (
        "https://graph.threads.net/access_token"
        f"?grant_type=th_exchange_token"
        f"&client_secret={urllib.parse.quote(app_secret)}"
        f"&access_token={urllib.parse.quote(short_token)}"
    )
    try:
        long_resp = http_get(long_url)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"✗ Step 4 失敗（HTTP {e.code}）：{body}")

    if "access_token" not in long_resp:
        sys.exit(f"✗ Step 4 回傳缺 access_token：{long_resp}")

    long_token = long_resp["access_token"]
    expires_days = long_resp.get("expires_in", 0) // 86400
    print(f"✓ 拿到 long-lived token，{expires_days} 天後到期")

    # --- Write to PVC ---
    print()
    print("─── 寫入 PVC ───")
    write_secret(TOKEN_FILE, long_token)
    write_secret(USER_ID_FILE, user_id)
    print(f"✓ {TOKEN_FILE} (chmod 600)")
    print(f"✓ {USER_ID_FILE} (chmod 600)")
    print()
    print("完成。可以去 Discord 跟 bot 說「token 放好了」。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\n✗ 中斷")
