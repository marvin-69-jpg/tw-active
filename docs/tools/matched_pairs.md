# matched_pairs — 同股票 active vs passive 揭露日 abnormal vol 配對比較

> 對應 [`tools/matched_pairs.py`](../../tools/matched_pairs.py) + [skill](../../.claude/skills/matched_pairs/SKILL.md)
> 對應 mechanism：[[wiki/mechanisms/etf-transparency-frontrunning]] H4'
> 第一次跑：2026-04-25

## 研究問題

H1 v2 finding（active T median 1.31 < passive T median 2.12）有一個明顯 confound：
**主動 ETF 偏小型股，被動 ETF 偏權值股**。Active 看起來較弱，可能只是因為它常加碼的股票本來就 abnormal vol 容易低（比如低週轉小型股的 baseline 本來就被偶爾巨量主導）。

H4'：用 **same-stock matched pairs** 控制掉股票特性。對「**被 active 也被 passive 加過碼的同一支股票**」分別算 abnormal vol，做 paired comparison。如果 active < passive 在配對控制下仍然成立 → H1 v2 結論真的，與 stock mix 無關。

## 方法

### 事件
重用 frontrunning events（active + passive，window-aligned to active range）

### 配對
對每檔同時出現在 active 和 passive 兩組的股票，計算：
```
active_median  = median([r_T for e in active events on this stock])
passive_median = median([r_T for e in passive events on this stock])
diff_median    = active_median - passive_median
```

### 配對門檻
`--min-events-per-side N`（預設 2）：同一檔股票要 active 那組 ≥N events 且 passive 那組 ≥N events 才入配對，避免單一 outlier 主導某邊。

### 配對統計
- **sign test**：n_active_higher / n_total（active diff > 0 比例）
- **median of diffs**：所有 overlap 股票 (active_med - passive_med) 的中位數
- mean / p25 / p75 of diffs

## 第一次結果（2026-04-25）

時間窗口：2025-05-13 至 2026-04-24

### Paired summary

```
overlap codes (符合配對門檻):  28
active median > passive:      4 (14%)
passive median > active:     24 (86%)
equal:                        0

median of (active - passive):  -0.991
mean of (active - passive):    -1.411
p25 / p75:                     -1.910 / -0.402
```

→ **H1 v2 結論成立且強化**：配對控制下 86% 的股票仍然顯示 passive 較強，median diff = **-0.99**。

### Top passive-stronger pairs（diff 最負）

| code | name             | n_a | n_p | a_med | p_med | diff   |
|------|------------------|----:|----:|------:|------:|-------:|
| 2327 | 國巨             | 32  |  2  |  2.35 | 11.07 | -8.72  |
| 2891 | 中信金           | 37  |  2  |  1.06 |  6.31 | -5.25  |
| 3045 | 台灣大           |  3  |  5  |  1.26 |  5.12 | -3.86  |
| 3037 | 欣興             | 36  |  2  |  1.28 |  4.55 | -3.27  |
| 2360 | 致茂             |  5  |  2  |  1.02 |  3.66 | -2.64  |
| 1301 | 台塑             |  2  |  2  |  1.24 |  3.37 | -2.12  |
| 2890 | 永豐金控         |  8  |  5  |  0.95 |  2.94 | -1.99  |
| 2884 | 玉山金融控股     | 28  |  5  |  1.07 |  2.73 | -1.67  |
| 2368 | 金像電子         | 35  |  2  |  1.19 |  2.76 | -1.57  |
| 2883 | 凱基金融控股     | 11  |  6  |  1.16 |  2.65 | -1.48  |

權值股 + 金融股居多。國巨 11× 和台灣大 5× 顯著大於其他——很可能對應 specific index inclusion / 季度 reconstitution 事件。

### Top active-stronger pairs（diff 最正，僅 4 檔）

| code | name       | n_a | n_p | a_med | p_med | diff   |
|------|------------|----:|----:|------:|------:|-------:|
| 6789 | 采鈺科技   |  4  |  2  |  3.33 |  1.45 | +1.88  |
| 2454 | 聯發科     | 20  |  2  |  2.03 |  0.88 | +1.15  |
| 6257 | 矽格       |  5  |  2  |  1.39 |  0.99 | +0.40  |
| 3036 | 文曄       | 30  |  2  |  0.91 |  0.57 | +0.33  |

只 4 檔，且 passive 那側 n=2 居多——統計力薄弱。

## 主要 finding

### H4' 結論：H1 v2 結論強化

- **86% overlap 股票** passive median > active median
- median diff = **-0.99**（active 比 passive 低約 1 個 ratio 單位）
- 整個分布偏負：p75 still -0.40

stock-mix 不是 H1 v2 的 confound source。**主動 ETF 揭露日的 per-event abnormal vol 真的比被動弱**，即使對同一檔股票（baseline vol 控制掉、流動性控制掉、市值控制掉）也是如此。

### 為什麼 passive 更強（hypothesis）

- **集中 + 同步**：passive 跟同一指數的 ETF 多家在 reconstitution 日同向 trade，量自然大
- **事先公告**：index 編製方在 reconstitution 前公告權重變化，front-running 時間窗口長
- **per-event Δshares 大**：被動 ETF 通常 quarterly 一次大調整，每次調整的股數遠大於主動 ETF 的小幅日調

主動 ETF 反而：
- 高頻小幅多元，每次 vol impact 小
- 21 家投信揭露時點不一致、調倉方向不一致 → noise cancellation

### 對 mechanism page 整體敘事的修正

把 etf-transparency-frontrunning 的核心 narrative 從「強制揭露 → 主動 IP leak」三段式總結為：

1. **per-event level（H1 v2 + H4'）**：主動 ETF 揭露日 abnormal vol 顯著比被動低，且 stock-mix 不是 confound
2. **cumulative level（H4）**：年化 per-AUM drag active 高出被動 ~2×，driver 是 events/yr 高 20×
3. **真正大的 cost 在被動端**：揭露透明性的 implied cost 在台灣主要透過被動 ETF 機制（index reconstitution effect, AP arbitrage 集中性）放大；主動 ETF 反而是受「揭露 + 散戶跟單」雙向作用，per-event 較溫和

→ Haeberle「強制揭露 = 主動經理 IP leak 加重」框架在台灣 **不直接成立**。台灣主動 ETF 的真正結構性問題不在揭露，可能要轉去看 fee 結構 / 配息平準金 / 規模上限等其他 mechanism。

## 已知局限

1. **overlap 樣本小**（28 檔）：min-events-per-side=2 已是低門檻，再放寬會讓 passive 那組進更多單事件 outlier
2. **passive 那側 n 普遍很小**（多數 2-5）：每檔 stock 的 passive median 受 outlier 影響大（國巨、台灣大可能單次事件主導）
3. **沒考慮事件時間分佈**：同檔股票被 active 加碼日期 vs 被 passive 加碼日期可能落在不同市場狀態（多頭 vs 盤整），baseline window 雖然 rolling 但仍會被 regime shift 影響
4. **一檔重複大事件 pull median**：國巨 11.07、台灣大 5.12 等 passive 巨值疑似對應 specific corporate events（除權息、納入指數）；做 robust median (Hodges-Lehmann) 或 trimmed mean 可能更穩
5. **沒檢驗統計顯著性**：純 descriptive 配對；正式 Wilcoxon signed-rank test 需要 dependency（缺 scipy），暫以 sign ratio 86% + median -0.99 當合理 strong evidence

## 後續研究方向

### v2
- 加 outlier robust：trimmed mean、Hodges-Lehmann estimator
- 加事件時間分佈分析（同股票 active vs passive event date 是否 systematically 不同）
- 擴充 passive 樣本（00919 / 00713 / 00733）後重跑

### 跨 mechanism 連結
- 反向 framing：研究 **passive ETF rebalance 在台灣的 abnormal vol** 自成一個 mechanism page（index reconstitution effect 在台灣的實證）
- transparency 框架退場後，主動 ETF 的真正結構性 cost 在哪？→ 開新 mechanism page 探討 fee / 配息平準金 / 規模天花板

## Stability

- 100% cache hit（vol cache 由 frontrunning v2 已 populate）
- 跨重跑結果一致
