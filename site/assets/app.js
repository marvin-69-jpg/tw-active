// Consensus bar chart — vanilla JS + Observable Plot from CDN.
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/+esm";

const DATA_URL = "./data/consensus.json";

const state = {
  data: null,
  sortBy: "held_by",      // held_by | avg_weight | total_weight
  minHeld: 2,
  topN: 50,
  selected: null,         // stock code currently highlighted in side panel
};

const $ = (sel) => document.querySelector(sel);

function fmtDate(ymd) {
  // "20260417" → "2026-04-17"
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
    // secondary
    return (b.total_weight ?? 0) - (a.total_weight ?? 0);
  });
  return rows.slice(0, state.topN);
}

function renderChart() {
  const rows = filteredRows();
  if (!rows.length) {
    $("#chart").innerHTML =
      '<p style="color:var(--ink-soft);padding:48px;text-align:center;">沒有符合篩選條件的股票</p>';
    return;
  }
  // label with code + name (truncate long English names)
  const decorated = rows.map((r) => ({
    ...r,
    label: `${r.code}  ${truncate(r.name, 18)}`,
  }));

  const maxHeld = state.data.kpi.n_etfs;
  const barHeight = 22;
  const marginLeft = 220;
  const width = Math.min(
    900,
    Math.max(480, $("#chart").clientWidth - 32)
  );

  const plot = Plot.plot({
    width,
    height: Math.max(360, rows.length * barHeight + 80),
    marginLeft,
    marginRight: 60,
    marginTop: 36,
    marginBottom: 24,
    x: {
      domain: [0, maxHeld],
      axis: "top",
      label: `被幾檔主動 ETF 持有（共 ${maxHeld} 檔） →`,
      labelAnchor: "left",
      labelOffset: 22,
      ticks: Math.min(11, maxHeld),
      grid: true,
    },
    y: {
      domain: decorated.map((d) => d.label),
      label: null,
    },
    color: {
      type: "linear",
      domain: [0, 10],
      range: ["#f1e8e6", "#8a1a0f"],
      clamp: true,
    },
    marks: [
      Plot.barX(decorated, {
        y: "label",
        x: "held_by",
        fill: "avg_weight",
        title: (d) =>
          `${d.code} ${d.name}\n` +
          `被 ${d.held_by} / ${maxHeld} 檔 ETF 持有\n` +
          `平均權重 ${fmtPct(d.avg_weight)}（有買的 ETF 平均配多少）\n` +
          `最重 ${fmtPct(d.max_weight)}（下手最重那檔的比重）\n` +
          `最輕 ${fmtPct(d.min_weight)}（下手最輕那檔的比重）\n` +
          `總權重 ${fmtPct(d.total_weight)}（所有持有者加總）\n` +
          `點擊看哪幾檔 ETF 有買`,
        className: "consensus-bar",
      }),
      Plot.text(decorated, {
        y: "label",
        x: "held_by",
        text: (d) =>
          state.sortBy === "held_by"
            ? `${d.held_by} 檔  ·  平均 ${fmtPct(d.avg_weight)}`
            : `平均 ${fmtPct(d.avg_weight)}  ·  ${d.held_by} 檔`,
        dx: 6,
        textAnchor: "start",
        fontFamily:
          'ui-monospace, "SF Mono", Menlo, Consolas, "Noto Sans Mono TC", monospace',
        fontSize: 11,
        fill: "#3a3a3a",
      }),
      Plot.ruleX([0]),
    ],
  });

  const host = $("#chart");
  host.innerHTML = "";
  host.append(plot);

  // wire click handlers via DOM (Observable Plot doesn't expose row-level events directly)
  const bars = plot.querySelectorAll("[aria-label][fill]");
  bars.forEach((bar, i) => {
    const row = decorated[i];
    if (!row) return;
    bar.style.cursor = "pointer";
    bar.addEventListener("click", () => selectStock(row.code));
  });

  // re-highlight selected
  if (state.selected) {
    highlightInChart();
  }
}

function highlightInChart() {
  const bars = document.querySelectorAll("#chart [aria-label][fill]");
  const rows = filteredRows();
  bars.forEach((bar, i) => {
    const row = rows[i];
    if (!row) return;
    bar.style.outline =
      row.code === state.selected ? "2px solid #111" : "none";
    bar.style.outlineOffset = "-1px";
  });
}

function selectStock(code) {
  state.selected = code;
  renderPanel();
  highlightInChart();
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

function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
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
