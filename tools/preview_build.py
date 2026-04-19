#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
preview_build — 從 raw/cmoney/<ETF>/batch_*_r<largest>.json 產出
                site/preview/<etf>.json（前端壓縮版）。

Filter 規則（見 feedback_preview_new_position_flag memory）：
  收錄條件 = days_held ≥ 30  OR  (last_date == as_of AND days_held < 30)
  後者額外 is_new=true 標記

Usage:
  ./tools/preview_build.py 00981A
  ./tools/preview_build.py 00981A --min-days 30
  ./tools/preview_build.py 00981A --out site/preview/00981a.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ISSUER_OF = {
    # minimal mapping for preview caption; extend as needed
    "00981A": ("主動統一台股增長", "統一投信"),
    "00982A": ("主動統一台股動能", "統一投信"),
    "00980A": ("主動群益台灣強棒", "群益投信"),
    "00988A": ("主動野村臺灣優選", "野村投信"),
    "00983A": ("主動國泰台灣領航", "國泰投信"),
    "00984A": ("主動凱基台灣優勢", "凱基投信"),
    "00985A": ("主動富邦台灣中小", "富邦投信"),
    "00986A": ("主動中信台灣老將", "中信投信"),
    "00987A": ("主動元大台灣優質", "元大投信"),
    "00989A": ("主動群益科技高息", "群益投信"),
    "00990A": ("主動永豐高息優選", "永豐投信"),
    "00991A": ("主動兆豐台灣指數", "兆豐投信"),
    "00992A": ("主動野村台灣股息", "野村投信"),
    "00993A": ("主動富邦台灣智慧", "富邦投信"),
    "00994A": ("主動永豐科技百強", "永豐投信"),
    "00995A": ("主動國泰息收雙王", "國泰投信"),
    "00996A": ("主動中信台灣多元", "中信投信"),
    "00997A": ("主動元大台灣先驅", "元大投信"),
    "00998A": ("主動群益潛力旗艦", "群益投信"),
    "00400A": ("主動宏遠複合", "宏遠投信"),
    "00401A": ("主動凱基多資產", "凱基投信"),
}


def load_latest_raw(etf: str) -> tuple[list[list], str]:
    """Return (rows, source_path). Pick largest 'r' suffix that has .json (not only .meta.json)."""
    pattern = f"raw/cmoney/{etf}/batch_*_r*.json"
    files = [p for p in glob.glob(pattern) if not p.endswith(".meta.json")]
    if not files:
        raise SystemExit(f"no raw data files for {etf} under raw/cmoney/")
    # Prefer the file with largest 'r' suffix then latest timestamp
    def _rank(p: str) -> tuple[int, str]:
        name = Path(p).stem
        try:
            r = int(name.split("_r")[-1])
        except Exception:
            r = 0
        ts = name.split("_")[1] if "_" in name else ""
        return (r, ts)
    files.sort(key=_rank, reverse=True)
    chosen = files[0]
    data = json.loads(Path(chosen).read_text())
    rows = data.get("Data") or data.get("data") or []
    return rows, chosen


def build(etf: str, min_days: int = 30) -> dict:
    rows, src = load_latest_raw(etf)
    # rows: [date, name, weight(%), code]
    by_code: dict[str, list[dict]] = {}
    name_of: dict[str, str] = {}
    for r in rows:
        if len(r) < 4:
            continue
        date, name, wt, code = r[0], r[1], r[2], r[3]
        try:
            weight = float(wt)
        except Exception:
            continue
        if not code or not date:
            continue
        by_code.setdefault(code, []).append({"date": date, "weight": weight})
        name_of[code] = name

    for code in by_code:
        by_code[code].sort(key=lambda x: x["date"])

    all_dates = sorted({r[0] for r in rows if len(r) >= 1 and r[0]})
    as_of = all_dates[-1] if all_dates else ""
    first_date = all_dates[0] if all_dates else ""
    n_days = len(all_dates)

    # Today's holdings
    current = []
    for code, s in by_code.items():
        last = s[-1]
        if last["date"] == as_of and last["weight"] > 0:
            current.append({"date": as_of, "code": code, "name": name_of[code], "weight": last["weight"]})
    current.sort(key=lambda x: -x["weight"])

    # days_held: number of distinct dates the stock appeared
    days_held = {code: len(s) for code, s in by_code.items()}

    # Apply filter
    series_out: dict[str, list[dict]] = {}
    is_new: dict[str, bool] = {}
    for code, s in by_code.items():
        # 跳過從未持有（weight 全 0）的 cash-like 條目（PFUR_NTD 等）
        if not any(p["weight"] > 0 for p in s):
            continue
        n = days_held[code]
        last_date = s[-1]["date"]
        held_now = last_date == as_of and s[-1]["weight"] > 0
        if n >= min_days:
            series_out[code] = s
        elif held_now:
            # 新建倉，仍在場上：保留並打 NEW 標記
            series_out[code] = s
            is_new[code] = True
        # else: 短期已出清，丟掉（noise）

    # Exited codes: only long-held (days_held >= min_days) positions that are no longer held.
    # 短期已出清（days_held < min_days）= 試水溫/停損雜訊，跟 current side 的 filter 對齊，一併丟掉。
    # 這層 filter 保證 exited_codes 都在 series_out 裡 → 有 name/chart data 可點看歷史。
    #
    # Raw 資料源（CMoney）對「出清」有兩種表示法：
    #   (a) 出清後補 weight=0 rows 一路到 as_of（e.g. 2357 華碩）
    #   (b) 出清後直接不再出現（e.g. 1326 台化）
    # 為了前端 chart 一致呈現「權重一路降到 0%」，(b) 類要在 last_date 之後補一筆 weight=0 synthetic row。
    exited_codes = []
    exit_date: dict[str, str] = {}   # code -> last date with weight > 0（真正出清日）
    active_days: dict[str, int] = {} # code -> 非零權重的天數（真正持有天數）
    for code, s in series_out.items():
        if is_new.get(code):
            continue  # NEW 倉位本來就還在場上，不算 exited
        last = s[-1]
        if last["date"] != as_of or last["weight"] == 0:
            exited_codes.append(code)
            nz = [p for p in s if p["weight"] > 0]
            exit_date[code] = nz[-1]["date"] if nz else s[-1]["date"]
            active_days[code] = len(nz)
            # 補 synthetic zero row 讓 chart 視覺化出「降到 0」
            if last["weight"] > 0:
                # 找 last_date 後的下一個交易日（優先），否則放 as_of
                next_day = next((d for d in all_dates if d > last["date"]), as_of)
                s.append({"date": next_day, "weight": 0.0})
    # 按實際出清日倒序（最近出清的排前面）
    exited_codes.sort(key=lambda c: exit_date.get(c, ""), reverse=True)

    name, issuer = ISSUER_OF.get(etf, (etf, ""))
    out = {
        "etf": {"code": etf, "name": name, "issuer": issuer},
        "as_of": as_of,
        "first_date": first_date,
        "n_days": n_days,
        "current": current,
        "exited_codes": exited_codes,
        "exit_date": exit_date,
        "active_days": active_days,
        "series": series_out,
        "name_of": {k: name_of[k] for k in series_out},
        "days_held": {k: days_held[k] for k in series_out},
        "is_new": is_new,  # {code: true} only for brand-new positions
        "_source_file": src,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build preview JSON from raw/cmoney/")
    ap.add_argument("etf", help="ETF code, e.g. 00981A")
    ap.add_argument("--min-days", type=int, default=30, help="default 30")
    ap.add_argument("--out", help="output path; default site/preview/<etf lower>.json")
    args = ap.parse_args()

    out = build(args.etf, min_days=args.min_days)
    default_out = f"site/preview/{args.etf.lower()}.json"
    out_path = Path(args.out or default_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False))
    newly = [c for c, v in out["is_new"].items() if v]
    print(f"[done] {out_path}", file=sys.stderr)
    print(f"  range: {out['first_date']} → {out['as_of']} ({out['n_days']} days)", file=sys.stderr)
    print(f"  current: {len(out['current'])} · kept series: {len(out['series'])} · exited: {len(out['exited_codes'])}", file=sys.stderr)
    print(f"  NEW positions: {len(newly)}" + (" (" + ", ".join(newly) + ")" if newly else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
