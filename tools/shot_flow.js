/**
 * shot_flow.js — CDP screenshot of flow.html
 *
 * Usage:
 *   node tools/shot_flow.js [output_path]
 *
 * Requires: local HTTP server at PREVIEW_PORT serving site/preview/
 *   python3 -m http.server 18765 --directory site/preview &
 *
 * Deps: ws (npm install ws)
 */

const WebSocket = require("ws");
const http = require("http");
const { execSync, spawn } = require("child_process");
const fs = require("fs");

const PORT = 19252;           // CDP remote debugging port
const PREVIEW_PORT = 18765;   // local preview HTTP server
const OUT = process.argv[2] || "/tmp/shot_flow.png";
const LOAD_WAIT_MS = 4000;    // wait for JS to render

try { execSync(`kill $(lsof -ti:${PORT})`, { shell: true }); } catch (e) {}

const browser = spawn("/usr/bin/chromium-browser", [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  `--remote-debugging-port=${PORT}`,
  "--window-size=1366,900",
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
    } catch (e) {}
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
    width: 1366, height: 900, deviceScaleFactor: 1.5, mobile: false,
  });

  await cdp(ws, "Page.navigate", {
    url: `http://127.0.0.1:${PREVIEW_PORT}/flow.html`,
  });
  await sleep(LOAD_WAIT_MS);

  const shot = await cdp(ws, "Page.captureScreenshot", {
    format: "png",
    clip: { x: 0, y: 0, width: 1366, height: 900, scale: 1 },
  });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(`saved: ${OUT}`);

  ws.close();
  process.kill(-browser.pid, "SIGTERM");
})().catch(e => { console.error(e); process.exit(1); });
