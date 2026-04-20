// Consensus bar chart — hand-rolled SVG for reliable full-row click targets.
// (Previously used Observable Plot but DOM-level click binding proved fragile:
//  small bars on low-held_by rows were near-unclickable, and subsequent clicks
//  after a selection sometimes stopped registering.)

const DATA_URL = new URL("../data/consensus.json", import.meta.url).href;

const state = {
  data: null,
  sortBy: "held_by",      // held_by | avg_weight | total_weight
  minHeld: 2,
  topN: 50,
  selected: null,         // stock code currently highlighted in side panel
};

const $ = (sel) => document.querySelector(sel);
const SVG_NS = "http://www.w3.org/2000/svg";

function fmtDate(ymd) {
  if (!ymd || ymd.length !== 8) return ymd ?? "—";
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}

function fmtPct(x) {
  return (Math.round(x * 100) / 100).toFixed(2) + "%";
}

function etfNameLookup(data) {
  const m = new Map();
  for (const e of data.etfs) m.set(e.code, e);
  return m;
}

function renderKpi(data) {
  $("#as-of").textContent = fmtDate(data.as_of);
  $("#kpi-n").textContent = data.kpi.n_etfs;
  $("#kpi-all-in").textContent = data.kpi.all_in_count;
  $("#kpi-majority").textContent = data.kpi.majority_count;
  $("#kpi-solo").textContent = data.kpi.solo_count;
}

function filteredRows() {
  const rows = state.data.consensus
    .filter((r) => r.held_by >= state.minHeld)
    .slice();

  rows.sort((a, b) => {
    const diff = (b[state.sortBy] ?? 0) - (a[state.sortBy] ?? 0);
    if (diff !== 0) return diff;
    return (b.total_weight ?? 0) - (a.total_weight ?? 0);
  });
  return rows.slice(0, state.topN);
}

// Linear interpolation between two hex colors at t ∈ [0, 1].
function lerpColor(a, b, t) {
  const pa = [parseInt(a.slice(1, 3), 16), parseInt(a.slice(3, 5), 16), parseInt(a.slice(5, 7), 16)];
  const pb = [parseInt(b.slice(1, 3), 16), parseInt(b.slice(3, 5), 16), parseInt(b.slice(5, 7), 16)];
  const m = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${m[0]},${m[1]},${m[2]})`;
}

function barColor(avgWeight) {
  // match previous Plot scale: linear domain [0, 10] → [#f1e8e6, #8a1a0f], clamp.
  const t = Math.max(0, Math.min(1, avgWeight / 10));
  return lerpColor("#f1e8e6", "#8a1a0f", t);
}

function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function renderChart() {
  const host = $("#chart");
  const rows = filteredRows();
  if (!rows.length) {
    host.innerHTML =
      '<p style="color:var(--ink-soft);padding:48px;text-align:center;">沒有符合篩選條件的股票</p>';
    return;
  }

  const maxHeld = state.data.kpi.n_etfs;
  const rowH = 22;
  const padT = 40;
  const padB = 16;
  const padL = 220;      // space for labels
  const padR = 90;       // space for inline stat text
  const clientW = Math.max(420, host.clientWidth - 32);
  const width = Math.min(960, clientW);
  const innerW = width - padL - padR;
  const height = padT + rows.length * rowH + padB;

  const xOf = (v) => padL + (v / maxHeld) * innerW;

  // Build SVG as an HTML string (fast, simple) — then attach click handlers
  // via delegation on the overlay group so every row is a large click target.
  const ticks = [];
  const nTicks = Math.min(11, maxHeld);
  for (let i = 0; i <= nTicks; i++) {
    const v = (maxHeld / nTicks) * i;
    const x = xOf(v).toFixed(1);
    ticks.push(
      `<line x1="${x}" y1="${padT - 4}" x2="${x}" y2="${height - padB}" stroke="#e6e3dc" stroke-width="0.5" />`,
      `<text x="${x}" y="${padT - 8}" font-family="ui-monospace,monospace" font-size="10" fill="#8a8a8a" text-anchor="middle">${Math.round(v)}</text>`
    );
  }

  const axisLabel =
    `<text x="${padL}" y="${18}" font-family="ui-monospace,monospace" font-size="11" fill="#6b6b6b">被幾檔主動 ETF 持有（共 ${maxHeld} 檔）→</text>`;

  const bars = rows.map((r, i) => {
    const y = padT + i * rowH;
    const cy = y + rowH / 2;
    const barW = Math.max(0.5, xOf(r.held_by) - padL);
    const fill = barColor(r.avg_weight);
    const selected = state.selected === r.code;
    const labelText = `${r.code}  ${truncate(r.name, 18)}`;
    const statText =
      state.sortBy === "held_by"
        ? `${r.held_by} 檔  ·  平均 ${fmtPct(r.avg_weight)}`
        : `平均 ${fmtPct(r.avg_weight)}  ·  ${r.held_by} 檔`;

    const tip =
      `${r.code} ${r.name}\n` +
      `被 ${r.held_by} / ${maxHeld} 檔 ETF 持有\n` +
      `平均權重 ${fmtPct(r.avg_weight)}\n` +
      `最重 ${fmtPct(r.max_weight)}  最輕 ${fmtPct(r.min_weight)}\n` +
      `總權重 ${fmtPct(r.total_weight)}\n` +
      `點擊看哪幾檔 ETF 有買`;

    const rowBg = selected ? "#fff3c4" : "transparent";

    return `<g class="row" data-code="${esc(r.code)}">
      <title>${esc(tip)}</title>
      <rect x="0" y="${y}" width="${width}" height="${rowH}" fill="${rowBg}" class="row-bg" />
      <text x="${padL - 8}" y="${cy}" font-family="ui-monospace,monospace" font-size="12" fill="#1a1a1a"
            text-anchor="end" dominant-baseline="central">${esc(labelText)}</text>
      <rect x="${padL}" y="${y + 3}" width="${barW.toFixed(1)}" height="${rowH - 6}"
            fill="${fill}" class="bar" ${selected ? 'stroke="#111" stroke-width="1.5"' : ""} />
      <text x="${padL + barW + 6}" y="${cy}" font-family="ui-monospace,monospace" font-size="11"
            fill="#3a3a3a" dominant-baseline="central">${esc(statText)}</text>
      <rect x="0" y="${y}" width="${width}" height="${rowH}" fill="transparent" class="row-hit"
            style="cursor:pointer" />
    </g>`;
  }).join("");

  // Axis baseline
  const baseline = `<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${height - padB}" stroke="#1a1a1a" stroke-width="1" />`;

  host.innerHTML =
    `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"
          xmlns="${SVG_NS}" role="img" aria-label="主動 ETF 共識股排行">
       <style>
         .row:hover .row-bg { fill: #f6f1e8; }
         .row:hover .bar { filter: brightness(0.92); }
       </style>
       ${ticks.join("")}
       ${axisLabel}
       ${bars}
       ${baseline}
     </svg>`;

  // Single delegated click listener — robust across re-renders.
  const svg = host.querySelector("svg");
  svg.addEventListener("click", (ev) => {
    const g = ev.target.closest("g.row");
    if (!g) return;
    const code = g.dataset.code;
    if (code) selectStock(code);
  });
}

function selectStock(code) {
  state.selected = code;
  renderChart();        // re-render to update selected row background + bar stroke
  renderPanel();
}

function renderPanel() {
  const panel = $("#panel");
  const stock = state.data.consensus.find((r) => r.code === state.selected);
  if (!stock) {
    panel.classList.add("empty");
    panel.innerHTML =
      '<div class="panel-empty">點任一橫條，看哪幾檔 ETF 持有這支股票</div>';
    return;
  }
  panel.classList.remove("empty");
  const etfNames = etfNameLookup(state.data);
  const rows = stock.etfs
    .map((e) => {
      const meta = etfNames.get(e.etf) || { code: e.etf, name: e.etf, issuer: "" };
      return `
      <li>
        <span class="etf-code">${meta.code}</span>
        <span class="etf-name" title="${esc(meta.name)}">${esc(meta.name)}</span>
        <span class="etf-weight">${fmtPct(e.weight)}</span>
      </li>`;
    })
    .join("");
  panel.innerHTML = `
    <div class="stock-head">
      <div>
        <div class="stock-code">${esc(stock.code)}</div>
        <div class="stock-name">${esc(stock.name)}</div>
      </div>
    </div>
    <div class="stock-stats">
      被 ${stock.held_by} / ${state.data.kpi.n_etfs} 檔 ETF 持有<br>
      平均權重 ${fmtPct(stock.avg_weight)}
      · 最重 ${fmtPct(stock.max_weight)}
      · 最輕 ${fmtPct(stock.min_weight)}
    </div>
    <div class="panel-hint">下面是有買這支股票的 ETF 名單，依權重（配置比重）排序：</div>
    <ul>${rows}</ul>
  `;
}

function bindControls() {
  $("#sort-by").addEventListener("change", (e) => {
    state.sortBy = e.target.value;
    renderChart();
  });
  const slider = $("#min-held");
  slider.max = state.data.kpi.n_etfs;
  slider.addEventListener("input", (e) => {
    state.minHeld = +e.target.value;
    $("#min-held-label").textContent = state.minHeld;
    renderChart();
  });
  $("#top-n").addEventListener("change", (e) => {
    state.topN = +e.target.value;
    renderChart();
  });
  // Re-render on resize (width changes) — debounced.
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderChart, 120);
  });
}

async function main() {
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
  } catch (e) {
    $("#chart").innerHTML = `<p style="color:var(--accent);padding:48px;">
      資料載入失敗：${esc(e.message)}</p>`;
    return;
  }
  renderKpi(state.data);
  bindControls();
  renderChart();
  renderPanel();
}

main();
