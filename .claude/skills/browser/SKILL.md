# Agent Browser Skill

觸發：「開網頁」「截圖」「抓網頁」「scrape」「browser」「讀這個連結」「這篇文章寫什麼」「幫我看這個 URL」

---

## 環境

- **工具**：`agent-browser` v0.25.3（npm global）
- **瀏覽器**：Chromium 146 headless（`/usr/bin/chromium`）
- **必要 env**：`export CHROME_PATH=/usr/bin/chromium`
- **未登入**：X/Twitter 能讀 Article 全文 + 單篇推文，但不能瀏覽 timeline

---

## 基本用法

每個指令前都要確保 `CHROME_PATH` 已 export。所有指令用 `npx agent-browser`。

### 開網頁
```bash
CHROME_PATH=/usr/bin/chromium npx agent-browser open <url>
```

### 截圖
```bash
npx agent-browser screenshot /tmp/screenshot.png          # 可見區域
npx agent-browser screenshot --full /tmp/full.png          # 整頁
```

### 讀頁面文字（給 LLM 用，最省 token）
```bash
npx agent-browser snapshot -i          # accessibility tree + 互動元素 ref
npx agent-browser get text @e1         # 讀特定元素文字
```

### 執行 JS 抽資料
```bash
npx agent-browser eval 'document.title'
npx agent-browser eval 'JSON.stringify([...document.querySelectorAll("h2")].map(h=>h.textContent))'
```

### 互動
```bash
npx agent-browser click @e2
npx agent-browser fill @e3 "search query"
npx agent-browser press Enter
npx agent-browser scroll down 1000
```

### 關閉
```bash
npx agent-browser close
```

---

## 常用 Pattern

### Pattern 1：讀取網頁文章全文

```bash
CHROME_PATH=/usr/bin/chromium npx agent-browser open "<url>"
npx agent-browser eval '(() => {
  const h1 = (document.querySelector("h1")||{}).textContent||"";
  const ps = [...document.querySelectorAll("p")]
    .map(p => p.textContent.trim())
    .filter(t => t.length > 20);
  return JSON.stringify({ title: h1.trim(), body: ps.join("\n\n") });
})()'
```

### Pattern 2：抽取頁面所有連結

```bash
npx agent-browser eval 'JSON.stringify([...document.querySelectorAll("a")]
  .filter(a => a.textContent.trim().length > 10)
  .map(a => ({ text: a.textContent.trim(), url: a.href }))
  .slice(0, 30))'
```

### Pattern 3：截圖 + 存檔

```bash
CHROME_PATH=/usr/bin/chromium npx agent-browser open "<url>"
npx agent-browser screenshot /tmp/page.png
# 用 Read 工具讀 /tmp/page.png 即可看到圖片
```

### Pattern 4：模擬手機

```bash
npx agent-browser set device "iPhone 14"
npx agent-browser open "<url>"
npx agent-browser screenshot /tmp/mobile.png
```

---

## X/Twitter 讀取

未登入狀態下的能力：

| 內容類型 | 能讀 | 備註 |
|---------|------|------|
| Article（長文） | ✅ | 完整全文 |
| 單篇推文 | ✅ | 主文 + engagement 數字 |
| Thread | ⚠️ | 通常只有前幾則，需 scroll |
| Timeline | ❌ | 被登入牆擋 |

```bash
# 讀 X 文章/推文
CHROME_PATH=/usr/bin/chromium npx agent-browser open "https://x.com/<user>/status/<id>"
sleep 2  # X 載入較慢
npx agent-browser eval '(() => {
  const lines = document.body.innerText.split("\n").filter(l => l.trim().length > 0);
  return JSON.stringify(lines);
})()'
```

---

## 注意事項

- **每次用完要 `close`**，不然 Chromium process 會留在背景吃記憶體
- agent-browser 的 session 是跨指令保持的（open → eval → click 可以串）
- `eval` 回傳的 JSON 是 double-escaped string（外層有引號），用 node parse 時要 `JSON.parse()` 兩次
- 長 JS 避免用 bash 變數傳遞（特殊字元會爆），改用 `--stdin` 或寫成 `.js` 檔
- The Block 有 Cloudflare 擋，不能用
- 不要用 agent-browser 存取需要登入的服務（沒有 cookie/credential）
