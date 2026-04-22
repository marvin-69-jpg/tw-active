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
const { execSync, spawn } = require("child_process");
const fs = require("fs");

const PORT = 19252;           // CDP remote debugging port
const PREVIEW_PORT = 18765;   // local preview HTTP server
const OUT = process.argv[2] || "/tmp/shot_flow.png";
const LOAD_WAIT_MS = 4500;    // wait for JS fetch + render

// Try both common Chromium binary names
const CHROMIUM_BIN = (() => {
  for (const b of ["/usr/bin/chromium-browser", "/usr/bin/chromium"]) {
    try { fs.accessSync(b, fs.constants.X_OK); return b; } catch(e) {}
  }
  return "chromium";
})();

try { execSync(`kill $(lsof -ti:${PORT}) 2>/dev/null`, { shell: true }); } catch(e) {}

const browser = spawn(CHROMIUM_BIN, [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  `--remote-debugging-port=${PORT}`,
  "--window-size=1080,1920",  // tall window so full card fits
], { detached: true, stdio: "ignore" });
browser.unref();

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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

  // 430px wide → enough for footer line, 2.5x DPR → clean on mobile/Threads
  await cdp(ws, "Emulation.setDeviceMetricsOverride", {
    width: 430, height: 900, deviceScaleFactor: 2.5, mobile: true,
  });

  await cdp(ws, "Page.navigate", {
    url: `http://127.0.0.1:${PREVIEW_PORT}/index.html`,
  });
  await sleep(LOAD_WAIT_MS);

  // Get bounding box of #flow-card
  const { root: { nodeId: rootId } } = await cdp(ws, "DOM.getDocument");
  const { nodeIds } = await cdp(ws, "DOM.querySelectorAll", {
    nodeId: rootId, selector: "#flow-card",
  });

  if (!nodeIds.length) {
    console.error("✗ #flow-card not found");
    process.exit(1);
  }

  const box = await cdp(ws, "DOM.getBoxModel", { nodeId: nodeIds[0] });
  const [x1, y1, x2, , , , , y2] = box.model.border;
  const MARGIN = 16;
  const clip = {
    x: Math.max(0, x1 - MARGIN),
    y: Math.max(0, y1 - MARGIN),
    width:  (x2 - x1) + MARGIN * 2,
    height: (y2 - y1) + MARGIN * 2,
    scale: 1,
  };

  // Scroll card into view
  await cdp(ws, "Runtime.evaluate", {
    expression: `document.getElementById('flow-card')?.scrollIntoView()`,
  });
  await sleep(200);

  const shot = await cdp(ws, "Page.captureScreenshot", {
    format: "png",
    clip,
  });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(`saved: ${OUT}  (${clip.width}×${clip.height})`);

  ws.close();
  process.kill(-browser.pid, "SIGTERM");
})().catch(e => { console.error(e); process.exit(1); });
