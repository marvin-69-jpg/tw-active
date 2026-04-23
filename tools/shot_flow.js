/**
 * shot_flow.js — CDP screenshot of TUI flow card
 *
 * Usage:
 *   node tools/shot_flow.js [output_path] [flow_json_path]
 *
 * Generates a standalone HTML from flow.json (no HTTP server needed),
 * loads it via file://, and screenshots the #flow-card element.
 *
 * Deps: ws  (npm install ws)
 */

const WebSocket = require("ws");
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const OUT = process.argv[2] || "/tmp/shot_flow.png";
const FLOW_JSON = process.argv[3] || path.join(__dirname, "../site/preview/flow.json");
const PORT = 19252;     // Chrome CDP port
const HTTP_PORT = 19253; // mini HTML server port
const LOAD_WAIT_MS = 4000;
const CDP_TIMEOUT_MS = 20000;

const CHROMIUM_BIN = (() => {
  for (const b of [
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ]) {
    try { fs.accessSync(b, fs.constants.X_OK); return b; } catch(e) {}
  }
  return "google-chrome-stable";
})();
console.error("using browser:", CHROMIUM_BIN);

// ── Build standalone HTML ────────────────────────────────────────

function buildHtml(flow) {
  const asOf = flow.as_of || "";
  const covered = (flow.etfs_covered || []).length;
  const inflow  = flow.inflow  || [];
  const outflow = flow.outflow || [];
  const totals  = flow.totals  || {};
  const byEtf   = flow.by_etf  || [];

  const month = parseInt(asOf.slice(4, 6));
  const day   = parseInt(asOf.slice(6, 8));

  function fmtNtd(v) {
    const sign = v >= 0 ? "+" : "-";
    const abs = Math.abs(v);
    if (abs >= 1e8) { const n = abs / 1e8; return `${sign}${n >= 10 ? n.toFixed(0) : n.toFixed(1)}億`; }
    return `${sign}${(abs / 1e4).toFixed(0)}萬`;
  }

  const consensusBuy  = inflow.filter(s => s.etfs_buy >= 4).sort((a, b) => b.ntd - a.ntd);
  const singleBets    = inflow.filter(s => s.etfs_buy < 4 && s.ntd >= 3e8).sort((a, b) => b.ntd - a.ntd).slice(0, 7);
  const consensusSell = outflow.filter(s => s.etfs_sell >= 3).sort((a, b) => a.ntd - b.ntd);

  const ntdIn = totals.ntd_in || 0;
  const byEtfSorted = [...byEtf].sort((a, b) => b.ntd_in - a.ntd_in);
  const dominant = byEtfSorted[0];
  const dominantPct = dominant && ntdIn > 0 ? Math.round(dominant.ntd_in / ntdIn * 100) : 0;

  const allBuy = [...consensusBuy, ...singleBets];
  const maxNtd = allBuy.length ? Math.max(...allBuy.map(s => s.ntd)) : 1;
  const BAR_MAX = 14;

  function bar(ntd, isUp) {
    const filled = Math.max(1, Math.round(Math.abs(ntd) / maxNtd * BAR_MAX));
    const empty  = BAR_MAX - filled;
    const c = isUp ? "#b8860b" : "#4a7c4a";
    return `<span style="color:${c}">${"█".repeat(filled)}</span><span style="color:#e0ddd2">${"█".repeat(empty)}</span>`;
  }

  function rows(stocks, isUp) {
    return stocks.map(s => {
      const fam = isUp ? s.etfs_buy : s.etfs_sell;
      return `<div class="row">
        <span class="nm">${s.name.replace(/\s/g, "")}</span>
        <span class="cd">${s.code}</span>
        <span class="nt ${isUp ? "up" : "dn"}">${fmtNtd(s.ntd)}</span>
        <span class="br">${bar(s.ntd, isUp)}</span>
        <span class="fm">${fam}家</span>
      </div>`;
    }).join("");
  }

  let body = `<div class="hd">盤前指引 · <span class="dt">${month}/${day}</span> · <span class="cv">${covered}/21家已揭露</span></div>
<hr class="rs">`;

  if (consensusBuy.length) {
    body += `<div class="lb">共識買進 ≥4家</div><div class="rows">${rows(consensusBuy, true)}</div>`;
    if (singleBets.length) body += `<hr class="r">`;
  }
  if (singleBets.length) {
    body += `<div class="lb">單一大注 ≥3億</div><div class="rows">${rows(singleBets, true)}</div>`;
  }
  body += `<hr class="r">`;

  if (consensusSell.length) {
    body += `<div class="lb">共識賣 ≥3家</div><div class="rows">${rows(consensusSell, false)}</div>`;
  } else {
    body += `<div class="ns">共識賣：無 — 沒有任何一檔被 3家以上同時減碼</div>`;
  }

  body += `<hr class="rs">`;
  const netStr = fmtNtd(totals.net || 0);
  if (dominantPct > 50 && dominant) {
    body += `<div class="ft">主動ETF 淨流入 <b>${netStr}</b> · <span class="pct">${dominantPct}% basket buy</span> ${dominant.etf}</div>`;
  } else {
    body += `<div class="ft">主動ETF 淨流入 <b>${netStr}</b> · ${covered}/21家已揭露</div>`;
  }

  return `<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #fafaf7; padding: 16px; }
#flow-card {
  background: #fff;
  border: 1px solid #1a1a1a;
  padding: 16px 20px 14px;
  font-family: ui-monospace,"JetBrains Mono","SF Mono",Menlo,Consolas,monospace;
  font-size: 14px;
  line-height: 1.7;
  width: 460px;
}
.hd { font-size: 16px; font-weight: 700; color: #1a1a1a; margin-bottom: 3px; }
.dt { color: #1a1a1a; }
.cv { color: #6b6b6b; font-size: 12px; font-weight: 400; }
hr.r  { border: none; border-top: 1px solid #e0ddd2; margin: 8px 0; }
hr.rs { border: none; border-top: 1px solid #1a1a1a; margin: 10px 0 8px; }
.lb { font-size: 10px; color: #6b6b6b; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 4px; }
.rows { display: flex; flex-direction: column; }
.row { display: grid; grid-template-columns: 120px 4.2em 7em 1fr 3em; align-items: center; gap: 0 6px; font-size: 13px; line-height: 1.75; border-bottom: 1px solid #e0ddd2; }
.rows .row:last-child { border-bottom: none; }
.nm { color: #1a1a1a; white-space: nowrap; overflow: hidden; text-overflow: clip; }
.cd { color: #6b6b6b; }
.nt { text-align: right; font-weight: 700; }
.nt.up { color: #b8860b; }
.nt.dn { color: #4a7c4a; }
.br { font-size: 11px; letter-spacing: -.5px; }
.fm { color: #6b6b6b; font-size: 11px; text-align: right; }
.ns { color: #6b6b6b; font-size: 12px; padding: 2px 0; }
.ft { font-size: 12px; color: #6b6b6b; margin-top: 2px; }
.ft b { color: #1a1a1a; font-weight: 700; }
.pct { color: #b8860b; }
</style>
</head>
<body>
<div id="flow-card">${body}</div>
</body>
</html>`;
}

// ── CDP helpers ──────────────────────────────────────────────────

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getWsUrl() {
  for (let i = 0; i < 25; i++) {
    try {
      const data = await new Promise((res, rej) => {
        http.get(`http://127.0.0.1:${PORT}/json`, r => {
          let b = ""; r.on("data", d => b += d); r.on("end", () => res(b));
        }).on("error", rej);
      });
      const tabs = JSON.parse(data);
      if (tabs[0]?.webSocketDebuggerUrl) return tabs[0].webSocketDebuggerUrl;
    } catch(e) {}
    await sleep(300);
  }
  throw new Error("CDP: no ws url after retries");
}

async function cdp(ws, method, params = {}) {
  return new Promise((res, rej) => {
    const timer = setTimeout(() => rej(new Error(`CDP timeout: ${method}`)), CDP_TIMEOUT_MS);
    const id = Math.floor(Math.random() * 1e9);
    ws.once("message", function handler(raw) {
      const msg = JSON.parse(raw);
      if (msg.id === id) {
        clearTimeout(timer);
        msg.error ? rej(msg.error) : res(msg.result);
      } else {
        ws.once("message", handler);
      }
    });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

// ── Main ─────────────────────────────────────────────────────────

(async () => {
  // Read flow.json and generate standalone HTML
  const flow = JSON.parse(fs.readFileSync(FLOW_JSON, "utf8"));
  const html = buildHtml(flow);

  // Serve HTML via Node's built-in http (avoids file:// restrictions in CI)
  const htmlServer = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(html);
  });
  await new Promise(r => htmlServer.listen(HTTP_PORT, "127.0.0.1", r));
  console.error(`html server: http://127.0.0.1:${HTTP_PORT}/`);

  // Launch Chrome
  const browser = spawn(CHROMIUM_BIN, [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",         // critical for CI/Docker containers
    "--disable-software-rasterizer",
    `--remote-debugging-port=${PORT}`,
    "--window-size=520,900",
  ], { detached: true, stdio: "ignore" });
  browser.unref();

  let ws;
  try {
    const wsUrl = await getWsUrl();
    ws = new WebSocket(wsUrl);
    await new Promise(r => ws.on("open", r));

    await cdp(ws, "Emulation.setDeviceMetricsOverride", {
      width: 492, height: 900, deviceScaleFactor: 2.5, mobile: false,
    });

    await cdp(ws, "Page.navigate", { url: `http://127.0.0.1:${HTTP_PORT}/` });
    await sleep(LOAD_WAIT_MS);

    // Diagnostics
    const { result: diagR } = await cdp(ws, "Runtime.evaluate", {
      expression: `document.title + " | len=" + document.body.innerHTML.length + " | fc=" + !!document.getElementById("flow-card")`
    });
    console.error("page:", diagR.value);

    // Get bounding rect of flow-card
    const { result: rectR } = await cdp(ws, "Runtime.evaluate", {
      expression: `JSON.stringify((function(){ const el=document.getElementById("flow-card"); if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; })())`
    });

    let clip;
    const rv = rectR.value ? JSON.parse(rectR.value) : null;
    console.error("rect:", rv);

    if (rv && rv.w > 0 && rv.h > 0) {
      const M = 14;
      clip = { x: Math.max(0, rv.x - M), y: Math.max(0, rv.y - M), width: rv.w + M * 2, height: rv.h + M * 2, scale: 1 };
    } else {
      // Fallback: full-width top crop
      clip = { x: 0, y: 0, width: 492, height: 700, scale: 1 };
    }

    const shot = await cdp(ws, "Page.captureScreenshot", { format: "png", clip });
    fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
    console.log(`saved: ${OUT}  (${clip.width.toFixed(0)}×${clip.height.toFixed(0)})`);

    ws.close();
  } finally {
    htmlServer.close();
    try { process.kill(-browser.pid, "SIGTERM"); } catch(e) {}
  }
})().catch(e => { console.error(e); process.exit(1); });
