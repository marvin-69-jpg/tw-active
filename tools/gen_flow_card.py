#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
gen_flow_card.py — 用 ImageMagick 從 flow.json 生成盤前指引卡片圖

Usage:
  uv run tools/gen_flow_card.py [output.png] [flow.json]

Deps: ImageMagick (convert), Noto Sans CJK TC, DejaVu Sans Mono
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
FLOW_JSON = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "site/preview/flow.json"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/flow_card.png")

# ── 字型 ──────────────────────────────────────────────────────────
FONT_SANS   = "Noto-Sans-CJK-TC"   # 中文 sans
FONT_MONO   = "DejaVu-Sans-Mono"   # 數字 monospace

# ── 顏色（對齊主頁 CSS vars）────────────────────────────────────
C_PAPER     = "#fafaf7"
C_PANEL     = "#ffffff"
C_INK       = "#1a1a1a"
C_INK_SOFT  = "#6b6b6b"
C_RULE      = "#e0ddd2"
C_RULE_DARK = "#1a1a1a"
C_UP        = "#b8860b"   # 買進：金色
C_DOWN      = "#4a7c4a"   # 賣出：綠色

# ── 尺寸 ─────────────────────────────────────────────────────────
W           = 1080         # 卡片寬（px）
PAD         = 36           # 外邊距
COL_NAME    = 220          # 股名欄
COL_CODE    = 88           # 代號欄
COL_NTD     = 120          # 金額欄
BAR_MAX_W   = 160          # 最大條形寬
COL_BAR     = BAR_MAX_W + 16
COL_ETF     = W - PAD*2 - COL_NAME - COL_CODE - COL_NTD - COL_BAR - 24
FS_HEAD     = 30           # 標題字號
FS_LABEL    = 18           # 小標字號
FS_ROW      = 22           # 資料列字號
FS_FOOT     = 19           # 底部字號
LINE_H      = 34           # 每列高
TOTAL_ETFS  = 21

# ── 資料 ─────────────────────────────────────────────────────────
def fmt_ntd(v: int) -> str:
    sign = "+" if v >= 0 else "-"
    abs_v = abs(v)
    if abs_v >= 1e8:
        n = abs_v / 1e8
        return f"{sign}{n:.0f}億" if n == int(n) else f"{sign}{n:.1f}億"
    return f"{sign}{abs_v/1e4:.0f}萬"

def etf_buy_codes(stock: dict) -> list[str]:
    return [e["etf"] for e in stock.get("etfs", []) if e.get("kind") in ("add", "new")]

def etf_sell_codes(stock: dict) -> list[str]:
    return [e["etf"] for e in stock.get("etfs", []) if e.get("kind") in ("reduce", "exit")]

flow    = json.loads(FLOW_JSON.read_text())
as_of   = flow.get("as_of", "")
covered = len(flow.get("etfs_covered", []))
inflow  = flow.get("inflow", [])
outflow = flow.get("outflow", [])
totals  = flow.get("totals", {})
by_etf  = flow.get("by_etf", [])

month = int(as_of[4:6]) if as_of else 0
day   = int(as_of[6:8]) if as_of else 0

consensus_buy  = sorted([s for s in inflow  if s["etfs_buy"]  >= 4], key=lambda x: -x["ntd"])
single_bets    = sorted([s for s in inflow  if s["etfs_buy"]  <  4 and s["ntd"] >= 3e8], key=lambda x: -x["ntd"])[:7]
consensus_sell = sorted([s for s in outflow if s["etfs_sell"] >= 3], key=lambda x:  x["ntd"])

ntd_in  = totals.get("ntd_in", 0)
by_etf_s = sorted(by_etf, key=lambda e: -e["ntd_in"])
dominant = by_etf_s[0] if by_etf_s else None
dominant_pct = round(dominant["ntd_in"] / ntd_in * 100) if dominant and ntd_in > 0 else 0

all_buy = consensus_buy + single_bets
max_ntd = max((s["ntd"] for s in all_buy), default=1)

# ── ImageMagick draw commands ────────────────────────────────────
# We build a list of -draw / -annotate commands to pass to `convert`.
# All coordinates are absolute (no canvas resize after initial creation).

class Canvas:
    def __init__(self, w: int):
        self.w = w
        self.cmds: list[str] = []
        self.y = PAD   # current cursor y

    def rect(self, x, y, x2, y2, fill, stroke=None, stroke_w=1):
        self.cmds += ["-fill", fill]
        if stroke:
            self.cmds += ["-stroke", stroke, "-strokewidth", str(stroke_w)]
        else:
            self.cmds += ["-stroke", "none"]
        self.cmds += ["-draw", f"rectangle {x},{y} {x2},{y2}"]

    def hline(self, y, x1=None, x2=None, color=C_RULE, width=1):
        x1 = x1 if x1 is not None else PAD
        x2 = x2 if x2 is not None else self.w - PAD
        self.cmds += ["-fill", "none", "-stroke", color, "-strokewidth", str(width)]
        self.cmds += ["-draw", f"line {x1},{y} {x2},{y}"]

    def text(self, x, y, text: str, font=FONT_SANS, size=FS_ROW, color=C_INK, gravity="NorthWest", weight=400):
        # Bold only available for DejaVu fonts; Noto CJK is Regular-only
        fn = font
        if weight >= 700 and "Mono" in font:
            fn = "DejaVu-Sans-Mono-Bold"
        self.cmds += [
            "-font", fn,
            "-pointsize", str(size),
            "-fill", color,
            "-stroke", "none",
            "-annotate", f"+{x}+{y}", text,
        ]

    def bar(self, x, y, value, max_val, is_up=True, h=16):
        w = max(4, round(abs(value) / max_val * BAR_MAX_W))
        color = C_UP if is_up else C_DOWN
        bg_x2 = x + BAR_MAX_W
        # background
        self.rect(x, y, bg_x2, y + h, fill=C_RULE, stroke=None)
        # filled
        self.rect(x, y, x + w, y + h, fill=color, stroke=None)


c = Canvas(W)

# ── 計算總高度 ───────────────────────────────────────────────────
sections = []
if consensus_buy:
    sections.append(("label", "共識買進 ≥4家"))
    for s in consensus_buy:
        sections.append(("row_buy", s))
if single_bets:
    sections.append(("sep", None))
    sections.append(("label", "單一大注 ≥3億"))
    for s in single_bets:
        sections.append(("row_buy", s))
sections.append(("sep", None))
if consensus_sell:
    sections.append(("label", "共識賣 ≥3家"))
    for s in consensus_sell:
        sections.append(("row_sell", s))
else:
    sections.append(("nosell", None))
sections.append(("foot", None))

HEAD_H  = 60
RULE_H  = 12
LABEL_H = 28
ROW_H   = LINE_H + 4
SEP_H   = 10
NOSELL_H = ROW_H
FOOT_H  = 40

total_h = PAD + HEAD_H + RULE_H
for kind, data in sections:
    if kind == "label":
        total_h += LABEL_H
    elif kind in ("row_buy", "row_sell"):
        total_h += ROW_H
    elif kind == "sep":
        total_h += SEP_H + 1
    elif kind == "nosell":
        total_h += NOSELL_H
    elif kind == "foot":
        total_h += RULE_H + FOOT_H
total_h += PAD

# ── 背景 + 邊框 ──────────────────────────────────────────────────
# 先畫整體背景
c.cmds += ["-fill", C_PAPER, "-stroke", "none", "-draw", f"rectangle 0,0 {W},{total_h}"]
# 面板白底
c.cmds += ["-fill", C_PANEL, "-stroke", C_RULE_DARK, "-strokewidth", "2",
           "-draw", f"rectangle {PAD//2},{PAD//2} {W-PAD//2},{total_h-PAD//2}"]

# ── Header ────────────────────────────────────────────────────────
y = PAD + 4
date_str = f"{month}/{day}"
c.text(PAD + 8, y, "盤前指引", size=FS_HEAD, weight=700)
c.text(PAD + 8 + 130, y, f"· {date_str}", size=FS_HEAD, color=C_INK, weight=700)
c.text(PAD + 8 + 250, y, f"· {covered}/{TOTAL_ETFS}家已揭露", size=FS_HEAD - 8, color=C_INK_SOFT)

y += HEAD_H
c.hline(y, color=C_RULE_DARK, width=1)
y += RULE_H

# ── Sections ─────────────────────────────────────────────────────
for kind, data in sections:
    if kind == "label":
        c.text(PAD + 8, y + 4, data, font=FONT_SANS, size=FS_LABEL, color=C_INK_SOFT)
        y += LABEL_H

    elif kind in ("row_buy", "row_sell"):
        s = data
        is_up = kind == "row_buy"
        codes = etf_buy_codes(s) if is_up else etf_sell_codes(s)
        codes_str = "、".join(codes)
        name = s["name"].replace(" ", "")[:7]  # truncate very long names
        ntd_str = fmt_ntd(s["ntd"])
        cy = y + 4  # text baseline

        # name
        c.text(PAD + 8, cy, name, size=FS_ROW)
        # code
        c.text(PAD + 8 + COL_NAME, cy, s["code"], font=FONT_MONO, size=FS_ROW, color=C_INK_SOFT)
        # ntd (right-aligned in its column)
        ntd_x = PAD + 8 + COL_NAME + COL_CODE + COL_NTD - 10
        ntd_color = C_UP if is_up else C_DOWN
        c.text(ntd_x, cy, ntd_str, font=FONT_MONO, size=FS_ROW, color=ntd_color, weight=700)
        # bar
        bar_x = PAD + 8 + COL_NAME + COL_CODE + COL_NTD + 10
        c.bar(bar_x, cy + 8, s["ntd"], max_ntd, is_up=is_up, h=14)
        # etf codes
        etf_x = bar_x + BAR_MAX_W + 10
        c.text(etf_x, cy, codes_str, size=FS_ROW - 4, color=C_INK_SOFT)

        y += ROW_H
        c.hline(y, x1=PAD+8, color=C_RULE, width=1)

    elif kind == "sep":
        y += SEP_H
        c.hline(y, color=C_RULE, width=1)
        y += 1

    elif kind == "nosell":
        c.text(PAD + 8, y + 4,
               f"共識賣：無 — 沒有任何一檔被 3家以上同時減碼",
               size=FS_ROW - 2, color=C_INK_SOFT)
        y += NOSELL_H

    elif kind == "foot":
        y += SEP_H
        c.hline(y, color=C_RULE_DARK, width=1)
        y += RULE_H
        net = totals.get("net", 0)
        net_str = fmt_ntd(net)
        if dominant_pct > 50 and dominant:
            foot = f"主動ETF 淨流入 {net_str}  ·  {dominant_pct}% basket buy 來自 {dominant['etf']}"
        else:
            foot = f"主動ETF 淨流入 {net_str}  ·  {covered}/{TOTAL_ETFS}家已揭露"
        c.text(PAD + 8, y + 4, foot, size=FS_FOOT, color=C_INK_SOFT)
        y += FOOT_H

# ── Render ────────────────────────────────────────────────────────
cmd = [
    "convert",
    "-size", f"{W}x{total_h}",
    f"xc:{C_PAPER}",
] + c.cmds + [str(OUT)]

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
    sys.exit(1)

print(f"saved: {OUT}  ({W}x{total_h})")
