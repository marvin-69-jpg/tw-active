/**
 * shot_flow.js — CDP screenshot of #flow-card on preview/index.html
 *
 * Usage:
 *   node tools/shot_flow.js [output_path]
 *
 * Requires: local HTTP server at PREVIEW_PORT serving site/preview/
 *   python3 -m http.server 18765 --directory site/preview &
 *
 * Deps: ws  (npm install ws)
 */

const WebSocket = require("ws");
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");

const PORT = 19252;
const PREVIEW_PORT = 18765;
const OUT = process.argv[2] || "/tmp/shot_flow.png";
const LOAD_WAIT_MS = 7000;

const CHROMIUM_BIN = (() => {
  for (const b of ["/usr/bin/chromium-browser", "/usr/bin/chromium"]) {
    try { fs.accessSync(b, fs.constants.X_OK); return b; } catch(e) {}
  }
  return "chromium";
})();

const browser = spawn(CHROMIUM_BIN, [
  "--headless=new", "--no-sandbox", "--disable-gpu",
  `--remote-debugging-port=${PORT}`, "--window-size=1080,1920",
], { detached: true, stdio: "ignore" });
browser.unref();

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getWsUrl() {
  for (let i = 0; i < 20; i++) {
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
    const id = Math.floor(Math.random() * 1e9);
    ws.once("message", function handler(raw) {
      const msg = JSON.parse(raw);
      if (msg.id === id) msg.error ? rej(msg.error) : res(msg.result);
      else ws.once("message", handler);
    });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

(async () => {
  const wsUrl = await getWsUrl();
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.on("open", r));

  await cdp(ws, "Emulation.setDeviceMetricsOverride", {
    width: 480, height: 900, deviceScaleFactor: 2.5, mobile: true,
  });

  await cdp(ws, "Page.navigate", {
    url: `http://127.0.0.1:${PREVIEW_PORT}/index.html`,
  });
  await sleep(LOAD_WAIT_MS);

  // Diagnostic: log page title + flow-card status
  const { result: titleR } = await cdp(ws, "Runtime.evaluate", {
    expression: `document.title + ' | flow-card: ' + (document.getElementById('flow-card') ? 'found (h=' + document.getElementById('flow-card').offsetHeight + ')' : 'MISSING')`
  });
  console.error("page check:", titleR.value);

  // Get bounding rect via Runtime.evaluate (more reliable than DOM API in headless)
  const { result: rectR } = await cdp(ws, "Runtime.evaluate", {
    expression: `JSON.stringify((function(){ const el=document.getElementById('flow-card'); if(!el) return null; const r=el.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; })())`
  });

  let clip;
  const rectVal = rectR.value ? JSON.parse(rectR.value) : null;

  if (rectVal && rectVal.w > 0 && rectVal.h > 0) {
    const M = 16;
    clip = {
      x: Math.max(0, rectVal.x - M),
      y: Math.max(0, rectVal.y - M),
      width:  rectVal.w + M * 2,
      height: rectVal.h + M * 2,
      scale: 1,
    };
    console.error(`flow-card rect: ${JSON.stringify(rectVal)}`);
  } else {
    // Fallback: screenshot top portion of page (card should be near top)
    console.error("WARNING: flow-card not found or zero-size, falling back to top-of-page crop");
    clip = { x: 0, y: 60, width: 480, height: 600, scale: 1 };
  }

  // Scroll card into view
  await cdp(ws, "Runtime.evaluate", {
    expression: `document.getElementById('flow-card')?.scrollIntoView()`,
  });
  await sleep(200);

  const shot = await cdp(ws, "Page.captureScreenshot", { format: "png", clip });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(`saved: ${OUT}  (${clip.width.toFixed(0)}×${clip.height.toFixed(0)})`);

  ws.close();
  process.kill(-browser.pid, "SIGTERM");
})().catch(e => { console.error(e); process.exit(1); });
