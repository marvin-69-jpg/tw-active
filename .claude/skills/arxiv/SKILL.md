# AlphaXiv Paper Lookup Skill

觸發：使用者分享 arxiv URL、提到 paper ID、或要求讀學術論文

---

## 流程

### Step 1: 取得 paper ID

| Input | Paper ID |
|-------|----------|
| `https://arxiv.org/abs/2401.12345` | `2401.12345` |
| `https://arxiv.org/pdf/2401.12345` | `2401.12345` |
| `https://alphaxiv.org/overview/2401.12345` | `2401.12345` |
| `2401.12345v2` | `2401.12345v2` |

### Step 2: 抓結構化分析報告

```bash
curl -sL "https://www.alphaxiv.org/overview/{PAPER_ID}.md"
```

回傳 AI 生成的結構化論文分析（optimized for LLM consumption）。比讀 raw PDF 更快更完整。

### Step 3: 如果需要更多細節，抓全文

```bash
curl -sL "https://www.alphaxiv.org/abs/{PAPER_ID}.md"
```

回傳論文的完整 markdown 文字。只在 overview 不夠時用。

### Step 4: 404 的話

報告還沒生成。最後手段：引導使用者去 `https://arxiv.org/pdf/{PAPER_ID}`。

---

## 注意事項

- 不需要 auth — public endpoints
- 優先用 overview（結構化），只在需要特定 equation/table 時才抓 full text
- 存到 `raw/` 時加上 metadata header（Authors / Date / Source）
