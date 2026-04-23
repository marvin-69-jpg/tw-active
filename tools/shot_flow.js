/**
 * shot_flow.js — screenshot of TUI flow card
 *
 * Usage:
 *   node tools/shot_flow.js [output_path] [flow_json_path]
 *
 * Builds standalone HTML from flow.json, serves it via Node http,
 * then takes screenshot with Chrome's built-in --screenshot flag.
 * No CDP required.
 *
 * Deps: none (uses only Node.js builtins + pre-installed Chrome)
 */

const { execSync, spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");

const OUT = process.argv[2] || "/tmp/shot_flow.png";
const FLOW_JSON = process.argv[3] || path.join(__dirname, "../site/preview/flow.json");
const HTTP_PORT = 19253;

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
    if (abs >= 1e8) { const n = abs / 1e8; return `${sign}${n >= 10 ? n.toFixed(0) : n.toFixed(1)}&#x5104;`; }
    return `${sign}${(abs / 1e4).toFixed(0)}&#x842C;`;
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
    return `<span style="color:${c}">${"\u2588".repeat(filled)}</span><span style="color:#e0ddd2">${"\u2588".repeat(empty)}</span>`;
  }

  function rows(stocks, isUp) {
    return stocks.map(s => {
      const fam = isUp ? s.etfs_buy : s.etfs_sell;
      const name = s.name.replace(/\s/g, "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
      return `<div class="row">
        <span class="nm">${name}</span>
        <span class="cd">${s.code}</span>
        <span class="nt ${isUp ? "up" : "dn"}">${fmtNtd(s.ntd)}</span>
        <span class="br">${bar(s.ntd, isUp)}</span>
        <span class="fm">${fam}&#x5BB6;</span>
      </div>`;
    }).join("");
  }

  let body = `<div class="hd">&#x76E4;&#x524D;&#x6307;&#x5F15; &middot; <span class="dt">${month}/${day}</span> &middot; <span class="cv">${covered}/21&#x5BB6;&#x5DF2;&#x63ED;&#x9732;</span></div>
<hr class="rs">`;

  if (consensusBuy.length) {
    body += `<div class="lb">&#x5171;&#x8B58;&#x8CB7;&#x9032; &ge;4&#x5BB6;</div><div class="rows">${rows(consensusBuy, true)}</div>`;
    if (singleBets.length) body += `<hr class="r">`;
  }
  if (singleBets.length) {
    body += `<div class="lb">&#x55AE;&#x4E00;&#x5927;&#x6CE8; &ge;3&#x5104;</div><div class="rows">${rows(singleBets, true)}</div>`;
  }
  body += `<hr class="r">`;

  if (consensusSell.length) {
    body += `<div class="lb">&#x5171;&#x8B58;&#x8CE3; &ge;3&#x5BB6;</div><div class="rows">${rows(consensusSell, false)}</div>`;
  } else {
    body += `<div class="ns">&#x5171;&#x8B58;&#x8CE3;&#xFF1A;&#x7121; &mdash; &#x6C92;&#x6709;&#x4EFB;&#x4F55;&#x4E00;&#x6A94;&#x88AB; 3&#x5BB6;&#x4EE5;&#x4E0A;&#x540C;&#x6642;&#x6E1B;&#x78BC;</div>`;
  }

  body += `<hr class="rs">`;
  const netStr = fmtNtd(totals.net || 0);
  if (dominantPct > 50 && dominant) {
    body += `<div class="ft">&#x4E3B;&#x52D5;ETF &#x6DE8;&#x6D41;&#x5165; <b>${netStr}</b> &middot; <span class="pct">${dominantPct}% basket buy</span> ${dominant.etf}</div>`;
  } else {
    body += `<div class="ft">&#x4E3B;&#x52D5;ETF &#x6DE8;&#x6D41;&#x5165; <b>${netStr}</b> &middot; ${covered}/21&#x5BB6;&#x5DF2;&#x63ED;&#x9732;</div>`;
  }

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fafaf7;padding:16px;font-family:monospace}
#flow-card{background:#fff;border:1px solid #1a1a1a;padding:16px 20px 14px;font-family:monospace;font-size:14px;line-height:1.7;width:460px}
.hd{font-size:16px;font-weight:700;color:#1a1a1a;margin-bottom:3px}
.dt{color:#1a1a1a}.cv{color:#6b6b6b;font-size:12px;font-weight:400}
hr.r{border:none;border-top:1px solid #e0ddd2;margin:8px 0}
hr.rs{border:none;border-top:1px solid #1a1a1a;margin:10px 0 8px}
.lb{font-size:10px;color:#6b6b6b;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px}
.rows{display:flex;flex-direction:column}
.row{display:grid;grid-template-columns:120px 4.2em 7em 1fr 3em;align-items:center;gap:0 6px;font-size:13px;line-height:1.75;border-bottom:1px solid #e0ddd2}
.rows .row:last-child{border-bottom:none}
.nm{color:#1a1a1a;white-space:nowrap;overflow:hidden;text-overflow:clip}
.cd{color:#6b6b6b}.nt{text-align:right;font-weight:700}
.nt.up{color:#b8860b}.nt.dn{color:#4a7c4a}
.br{font-size:11px;letter-spacing:-.5px}
.fm{color:#6b6b6b;font-size:11px;text-align:right}
.ns{color:#6b6b6b;font-size:12px;padding:2px 0}
.ft{font-size:12px;color:#6b6b6b;margin-top:2px}
.ft b{color:#1a1a1a;font-weight:700}.pct{color:#b8860b}
</style>
</head>
<body>
<div id="flow-card">${body}</div>
</body>
</html>`;
}

// ── Serve HTML via Node.js http ──────────────────────────────────

async function startServer(html) {
  return new Promise((res, rej) => {
    const server = http.createServer((req, resp) => {
      resp.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      resp.end(html, "utf8");
    });
    server.listen(HTTP_PORT, "127.0.0.1", () => res(server));
    server.on("error", rej);
  });
}

// ── Main ─────────────────────────────────────────────────────────

(async () => {
  const flow = JSON.parse(fs.readFileSync(FLOW_JSON, "utf8"));
  const html = buildHtml(flow);

  const server = await startServer(html);
  console.error(`html server: http://127.0.0.1:${HTTP_PORT}/`);

  const url = `http://127.0.0.1:${HTTP_PORT}/`;

  // Chrome --screenshot mode: much simpler than CDP, no WebSocket needed.
  // Use async spawn so Node.js event loop stays alive to serve HTTP requests.
  const tmpOut = OUT + ".full.png";
  await new Promise((res, rej) => {
    const browser = spawn(CHROMIUM_BIN, [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--disable-software-rasterizer",
      "--disable-extensions",
      "--no-first-run",
      "--hide-scrollbars",
      `--window-size=492,900`,
      `--screenshot=${tmpOut}`,
      url,
    ], { stdio: ["ignore", "ignore", "pipe"] });
    const timer = setTimeout(() => { browser.kill(); rej(new Error("Chrome timeout")); }, 30000);
    browser.on("close", code => {
      clearTimeout(timer);
      code === 0 ? res() : rej(new Error(`Chrome exited ${code}`));
    });
  });

  server.close();

  if (!fs.existsSync(tmpOut)) {
    throw new Error(`Screenshot file not created: ${tmpOut}`);
  }

  // Trim to card area using ImageMagick (if available), else use as-is
  // The card starts at roughly x=16,y=16 and is width=460
  try {
    // Try to auto-trim whitespace and crop to content
    execSync(
      `convert "${tmpOut}" -trim -bordercolor "#fafaf7" -border 12 "${OUT}"`,
      { stdio: "ignore" }
    );
    console.log(`saved (trimmed): ${OUT}`);
  } catch(e) {
    // ImageMagick not available — just use the full screenshot
    fs.copyFileSync(tmpOut, OUT);
    console.log(`saved (full): ${OUT}`);
  }
  try { fs.unlinkSync(tmpOut); } catch(e) {}

})().catch(e => { console.error(e); process.exit(1); });
