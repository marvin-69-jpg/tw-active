# topics — 想寫的題材素材區

使用者丟進來的「想寫」素材：新聞文章、推文、別人的觀察、資料連結、靈感片段。

每筆素材一個 markdown 檔，命名 `YYYY-MM-DD-<short-slug>.md`，頂部 frontmatter 帶基本 metadata（status / source / 抓取時間）。

## 為什麼放這裡

- 寫稿不一定當下發，先囤
- 多個素材間可以串連（跨篇敘事）
- 跟 `reports/threads/archive.{md,jsonl}` 互補：archive = 已發；topics = 待寫
- 跟 `wiki/` 互補：wiki = 結構化長期知識；topics = 短期可消化的素材池

## 流程

1. 使用者丟 URL / 想法 / 截圖
2. bot 用 `agent-browser` 抓內容（URL 類）
3. 存成 `topics/YYYY-MM-DD-<slug>.md`，frontmatter `status: idea`
4. 寫稿時挑一個，狀態改 `status: drafted`
5. 發完文，狀態改 `status: published`，附 archive 對應的 post id
6. 太久沒寫的（>30 天）狀態改 `status: stale`，定期清

## frontmatter 欄位

```yaml
---
title: <一句話標題>
date_added: YYYY-MM-DD
source: <URL 或來源描述>
source_type: news | tweet | observation | data | other
status: idea | drafted | published | stale
post_id: <archive post id，published 後填>
related: [<其他 topics 檔名>, <wiki 頁>]
---
```

## 索引

由 bot 維護 `topics/INDEX.md` 列出全部素材，每筆一行：
`- [YYYY-MM-DD slug](檔名.md) — 一句話 hook  ·  status`
