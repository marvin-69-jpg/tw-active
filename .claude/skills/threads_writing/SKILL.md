# Threads 寫作 Skill

觸發：「寫 threads」「寫一篇」「寫文章」「Threads 文案」「寫貼文」「想寫」「來寫」（在 tw-active 或研究發文脈絡）

---

## 用前一定先做的兩件事

```bash
cd /home/node/tw-active
# 1. 重建發文歷史（確保 archive 是新的）
tools/fetch_threads_archive.py
# 2. grep 過去 7-14 天有沒有重複題材
grep -E "<關鍵字1>|<關鍵字2>" reports/threads/archive.jsonl
```

不要寫 7 天內已發過的相同主題。跨篇可串連，但題材要推進不要重複。

---

## 第一步：選 post 類型

從題材對應到結構，5 種類型擇一：

| 題材形狀 | 類型 | 模板 |
|---|---|---|
| 單一標的的倉位演化 / 操作紀律 | **單股 portrait** | [templates.md#單股-portrait](templates.md#單股-portrait) |
| 流行說法、想法被打臉 | **反問 hook** | [templates.md#反問-hook](templates.md#反問-hook) |
| 個股大漲/大跌，看跨 ETF 怎麼動 | **事件追蹤** | [templates.md#事件追蹤](templates.md#事件追蹤) |
| 拆解現象（規模、資金、結構） | **拆解** | [templates.md#拆解](templates.md#拆解) |
| 當前事件 + 過去類似案例對照 | **歷史回顧** | [templates.md#歷史回顧](templates.md#歷史回顧) |
| 每日 / 每週統計 | **brief（bullet）** | [templates.md#bullet-brief](templates.md#bullet-brief) |

不確定就先寫 200-300 字草稿，發現節奏卡住再回來換模板。

---

## 第二步：寫稿

照模板寫，**同時看** [voice.md](voice.md)（聲音指紋）。voice.md 包含：
- 第一人稱用法、開頭/結尾模式
- 「我本來以為...結果...」這類關鍵句式
- 數字鋪排規律（不四捨五入、配時點、配比照組）
- 思考分層（表層數字 → 機制 → 開放問題）

---

## 第三步：發文前自檢（硬規則）

逐項打勾，全過才發：

- [ ] **字數 300-500 字**（bullet brief 可短）
- [ ] **沒有任何 URL**（GitHub Pages / PR / raw 全禁，會被當內容行銷）
- [ ] **沒有任何資料源標註**（cmoney / 任何後端 API / 內部工具名一律不出現）
- [ ] **第一句是 hook**：場景 / 反問 / 數字 / 動作，不是「今天我來分享...」
- [ ] **數字具體**：「3,685 張」不是「約 3,700 張」；金額/張數/百分比都要原始精度
- [ ] **時間用 TPE +8**：「今天」「昨晚」「本週」要對台灣讀者成立，不要用 UTC
- [ ] **scope 標註**：講「主動 ETF 淨流入 X 億」要明標「21 檔主動 ETF」
- [ ] **沒有膠帶詞**：禁「事件本身：」「重點是」「值得注意的是」「先把骨架搭起來」
- [ ] **不譬喻不排比**：禁「口袋/天花板/深水區/腿/吞下/機器」這類擬物，禁前後對仗
- [ ] **沒有「等下次揭露才知道」這類廢話結尾**
- [ ] **挖到第二層**：列完數字至少有一條「→ 機制」「→ 對照」「→ 可測命題」
- [ ] **00981A 重疊類用正向 framing**（共識中心，不抓 closet indexer）
- [ ] **持股重疊 / Active Share 類**：發 wiki 不發 Threads（散戶討論度低）
- [ ] **basket buy footer 點到為止**：直接點名不要叫讀者「扣掉」

---

## 第四步：發文

```bash
# 草稿存暫存（可選）
echo "<draft>" > /tmp/post.md

# foreground 發文（不要 bg，會雙發）
cd /home/node/tw-active
uv run tools/threads.py post /tmp/post.md
# 或附圖
uv run tools/threads.py post /tmp/post.md --image https://<image-url>
```

發完**不問確認**，直接給使用者 Threads permalink。

---

## 第五步：補存檔

```bash
tools/fetch_threads_archive.py
# 查看新增是否進 archive
git diff reports/threads/archive.jsonl | tail
```

archive 需要跟著更新，不然下一篇 grep 會漏掉今天剛發的。

---

## 配圖規則

- **預設不配圖**（純文字 TEXT_POST 也行，看 4/16-4/18 系列）
- 有現成 site/preview 截圖就配（要先「做頁面再發文」memory）
- 配圖只用使用者提供的截圖，不要跑 CDP（feedback_use_user_screenshot）

---

## 失敗模式

| 症狀 | 原因 | 修法 |
|---|---|---|
| 發出來像新聞稿 | 沒 hook、沒第一人稱反應、純數字堆疊 | 改寫第一句加場景或反問，加「我本來以為...」 |
| 太像機器人 | 「引述→數據→結論」三段式 | 加轉折、留白、開放問題（voice.md） |
| 讀者沒共鳴 | 持股重疊類 / Active Share 類 | 改題材，留 wiki 不發 Threads |
| 太長 | 教科書式展開術語 | 一句話翻譯就好，不要展開 |
| 太散 | 一篇講多件事 | 一篇一件事，多件事拆多篇 thread |

---

## 參考

- [voice.md](voice.md) — 聲音指紋、句式、開頭/結尾模式
- [templates.md](templates.md) — 6 種模板配 archive 範例
- `reports/threads/archive.{md,jsonl}` — 38 篇歷史貼文，寫前必 grep
- `tools/fetch_threads_archive.py` — 重建 archive
- `tools/threads.py` — 發文 CLI
