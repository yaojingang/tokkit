from __future__ import annotations

import json
from html import escape
from typing import Any


def render_range_html_report(
    payload: dict[str, Any],
    *,
    generated_at: str,
    timezone_name: str,
) -> str:
    days = int(payload.get("range_days") or 0)
    title = f"TokKit 用量报告 - 最近 {days} 天"
    safe_payload = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    scan_command = f"tok scan all && tok html last {days} open"

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)}</title>",
            f"<style>{_css()}</style>",
            "</head>",
            "<body>",
            _topbar(days),
            '<main class="report-shell">',
            _hero(title, generated_at, timezone_name),
            '<section id="overview" class="anchor-section">',
            '<div id="summaryCards" class="metrics"></div>',
            "</section>",
            '<section id="filters" class="anchor-section panel control-panel">',
            "<h2>筛选</h2>",
            '<div class="filter-row">',
            '<div><span class="control-label">模型范围</span><div id="modelChips" class="chips"></div></div>',
            '<div class="filter-actions">',
            '<button type="button" class="ghost-button" id="selectCoreModels">只看核心模型</button>',
            '<button type="button" class="ghost-button" id="selectAllModels">全部模型</button>',
            "</div>",
            "</div>",
            '<p class="hint" id="filterHint"></p>',
            "</section>",
            '<section id="trend" class="anchor-section chart-grid">',
            _panel("每日 Token 趋势", '<div id="totalTrend"></div>'),
            _panel("预估费用趋势", '<div id="costTrend"></div>'),
            _panel("Prompt / Output / 缓存趋势", '<div id="promptTrend"></div>'),
            _panel("缓存命中率趋势", '<div id="cacheTrend"></div>'),
            "</section>",
            '<section id="models" class="anchor-section wide-grid">',
            _panel("模型消耗排行", '<div id="modelRank"></div>'),
            _panel("核心模型每日消耗", '<div id="modelTrend"></div>'),
            "</section>",
            '<section id="terminals" class="anchor-section chart-grid">',
            _panel("终端占比", '<div id="terminalShare"></div>'),
            _panel("应用维度", '<div id="appRank"></div>'),
            _panel("记录数趋势", '<div id="recordTrend"></div>'),
            _panel("Unsplit 趋势", '<div id="unsplitTrend"></div>'),
            "</section>",
            '<section id="details" class="anchor-section wide-panel panel">',
            "<h2>每日明细</h2>",
            '<div id="dailyTable"></div>',
            "</section>",
            "</main>",
            f'<script type="application/json" id="tokkit-data">{safe_payload}</script>',
            f'<script>window.TOKKIT_SCAN_COMMAND = {json.dumps(scan_command, ensure_ascii=False)};</script>',
            f"<script>{_js()}</script>",
            "</body>",
            "</html>",
        ]
    )


def _topbar(days: int) -> str:
    range_buttons = []
    for value, label in ((7, "7 天"), (14, "14 天"), (30, "30 天")):
        active = " active" if min(days, 30) == value else ""
        range_buttons.append(f'<button type="button" class="range-button{active}" data-range="{value}">{label}</button>')
    return f"""
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="#overview" aria-label="TokKit 报告首页">TokKit</a>
    <nav class="nav-links" aria-label="报告模块">
      <a href="#overview">总览</a>
      <a href="#filters">筛选</a>
      <a href="#trend">趋势</a>
      <a href="#models">模型</a>
      <a href="#terminals">终端</a>
      <a href="#details">明细</a>
    </nav>
    <div class="top-actions">
      <div class="range-group" aria-label="时间范围">{"".join(range_buttons)}</div>
      <button type="button" class="scan-button" id="rescanButton">重新扫描</button>
    </div>
  </div>
</header>
<div class="toast" id="toast" role="status" aria-live="polite"></div>"""


def _hero(title: str, generated_at: str, timezone_name: str) -> str:
    return f"""
<section class="hero">
  <div>
    <p class="eyebrow">本地 AI Token 账本</p>
    <h1>{escape(title)}</h1>
    <p class="subtle">生成时间 {escape(generated_at)} · 时区 {escape(timezone_name)}</p>
  </div>
  <div class="hero-note">
    <span>交互视图</span>
    <strong>趋势 · 模型 · 终端</strong>
    <small>切换天数和模型筛选后，所有图表会同步重算。</small>
  </div>
</section>"""


def _panel(title: str, body: str) -> str:
    return f"""
<section class="panel">
  <h2>{escape(title)}</h2>
  {body}
</section>"""


def _css() -> str:
    return """
:root {
  color-scheme: light;
  --paper: #f5f4ed;
  --ivory: #faf9f5;
  --warm-sand: #e8e6dc;
  --border: #ded9cc;
  --ink: #141413;
  --charcoal: #3d3d3a;
  --olive: #626058;
  --stone: #8d8a80;
  --brand: #1b365d;
  --brand-soft: #e4ecf5;
  --green: #2f6f55;
  --rust: #b56b35;
  --gold: #a38635;
  --rose: #9b5864;
  --ring: #cfc9b8;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    linear-gradient(135deg, rgba(27, 54, 93, 0.08), transparent 34rem),
    linear-gradient(225deg, rgba(181, 107, 53, 0.08), transparent 32rem),
    var(--paper);
  color: var(--ink);
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(245, 244, 237, 0.92);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(18px);
}
.topbar-inner {
  width: min(1220px, calc(100% - 28px));
  min-height: 64px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
}
.brand {
  color: var(--brand);
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: 22px;
  font-weight: 500;
  text-decoration: none;
}
.nav-links {
  display: flex;
  gap: 4px;
  overflow-x: auto;
}
.nav-links a,
.range-button,
.ghost-button,
.scan-button {
  min-height: 34px;
  border: 1px solid transparent;
  border-radius: 8px;
  font: inherit;
  white-space: nowrap;
}
.nav-links a {
  color: var(--charcoal);
  padding: 7px 10px;
  text-decoration: none;
}
.nav-links a:hover {
  background: var(--warm-sand);
  color: var(--brand);
}
.top-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.range-group {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--warm-sand);
  border-radius: 10px;
}
.range-button,
.ghost-button {
  background: transparent;
  color: var(--charcoal);
  padding: 7px 11px;
  cursor: pointer;
}
.range-button.active,
.ghost-button:hover {
  background: var(--ivory);
  border-color: var(--ring);
  color: var(--brand);
}
.scan-button {
  background: var(--brand);
  color: var(--ivory);
  padding: 7px 13px;
  cursor: pointer;
}
.toast {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 30;
  max-width: min(480px, calc(100% - 36px));
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--ink);
  color: var(--ivory);
  opacity: 0;
  transform: translateY(10px);
  pointer-events: none;
  transition: opacity 160ms ease, transform 160ms ease;
}
.toast.visible {
  opacity: 1;
  transform: translateY(0);
}
.report-shell {
  width: min(1220px, calc(100% - 28px));
  margin: 0 auto;
  padding: 30px 0 60px;
}
.anchor-section { scroll-margin-top: 82px; }
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 24px;
  align-items: end;
  margin: 18px 0 18px;
}
.eyebrow {
  margin: 0 0 9px;
  color: var(--brand);
  font-size: 13px;
  font-weight: 700;
}
h1 {
  max-width: 900px;
  margin: 0;
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: clamp(34px, 5vw, 68px);
  font-weight: 500;
  line-height: 1.08;
  letter-spacing: 0;
}
.subtle,
.hint,
.empty {
  color: var(--olive);
}
.subtle {
  margin: 15px 0 0;
}
.hero-note {
  background: var(--ink);
  color: var(--ivory);
  border-radius: 8px;
  padding: 18px;
}
.hero-note span,
.hero-note small {
  display: block;
  color: #d7d2c6;
}
.hero-note strong {
  display: block;
  margin: 8px 0 5px;
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: 25px;
  font-weight: 500;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.metric,
.panel {
  background: rgba(250, 249, 245, 0.92);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 1px 0 rgba(20, 20, 19, 0.04);
}
.metric {
  min-width: 0;
  padding: 15px;
}
.metric span,
.control-label {
  display: block;
  color: var(--olive);
  font-size: 12px;
  font-weight: 700;
}
.metric strong {
  display: block;
  margin: 7px 0 4px;
  color: var(--brand);
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: clamp(22px, 2.4vw, 31px);
  font-weight: 500;
  line-height: 1.1;
  overflow-wrap: anywhere;
}
.metric small {
  color: var(--stone);
}
.panel {
  min-width: 0;
  padding: 18px;
}
.panel h2 {
  margin: 0 0 14px;
  padding-left: 10px;
  border-left: 4px solid var(--brand);
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: 19px;
  font-weight: 500;
  line-height: 1.25;
}
.control-panel {
  margin-bottom: 16px;
}
.filter-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: end;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 9px;
}
.chip {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--ivory);
  color: var(--charcoal);
  padding: 7px 10px;
  cursor: pointer;
}
.chip.active {
  background: var(--brand-soft);
  border-color: #d6e1ee;
  color: var(--brand);
}
.filter-actions {
  display: flex;
  gap: 8px;
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.wide-grid {
  display: grid;
  grid-template-columns: minmax(330px, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
  margin-top: 16px;
}
.wide-panel {
  margin-top: 16px;
}
.chart {
  width: 100%;
  height: auto;
  display: block;
}
.grid {
  stroke: #e5e1d6;
  stroke-width: 1;
}
.axis-label,
.axis-value {
  fill: var(--olive);
  font-size: 12px;
}
.line {
  fill: none;
  stroke: var(--brand);
  stroke-width: 4;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.area {
  fill: #e4ecf5;
}
.bars rect {
  fill: var(--rust);
}
.multi-line {
  fill: none;
  stroke-width: 3.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin-bottom: 6px;
  color: var(--olive);
  font-size: 13px;
}
.legend span,
.share-list span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.legend i,
.share-list i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.donut-wrap {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 20px;
  align-items: center;
}
.donut {
  position: relative;
  width: 180px;
  aspect-ratio: 1;
  border-radius: 50%;
}
.donut::after {
  content: "";
  position: absolute;
  inset: 32px;
  background: var(--ivory);
  border-radius: 50%;
}
.donut span {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-items: center;
  text-align: center;
  color: var(--brand);
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  font-size: 18px;
  font-weight: 500;
  padding: 48px;
}
.share-list,
.rank-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.share-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.rank-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.42fr) minmax(120px, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 8px 0;
}
.rank-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rank-row div {
  height: 12px;
  background: var(--warm-sand);
  border-radius: 999px;
  overflow: hidden;
}
.rank-row i {
  display: block;
  height: 100%;
  border-radius: inherit;
}
.rank-row strong,
.share-list strong,
td,
th {
  font-variant-numeric: tabular-nums;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 10px 9px;
  border-bottom: 1px solid var(--border);
  text-align: right;
  white-space: nowrap;
}
th:first-child,
td:first-child {
  text-align: left;
}
th {
  color: var(--olive);
  font-size: 12px;
  font-weight: 700;
}
@media (max-width: 980px) {
  .topbar-inner,
  .hero,
  .chart-grid,
  .wide-grid,
  .filter-row {
    grid-template-columns: 1fr;
  }
  .top-actions {
    flex-wrap: wrap;
  }
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .report-shell,
  .topbar-inner {
    width: min(100% - 20px, 1220px);
  }
  .metrics,
  .donut-wrap,
  .rank-row {
    grid-template-columns: 1fr;
  }
  .donut {
    width: min(180px, 100%);
  }
}
"""


def _js() -> str:
    return r"""
const RAW = JSON.parse(document.getElementById('tokkit-data').textContent);
const COLORS = ['#1b365d', '#b56b35', '#2f6f55', '#a38635', '#9b5864', '#596f83', '#6d6250', '#707a3f'];
const state = {
  range: Math.min(Number(RAW.range_days || 30), 30),
  selectedModels: new Set(),
};

function numberValue(row, key) {
  return Number(row && row[key] ? row[key] : 0);
}

function fmtInt(value) {
  return Math.round(Number(value || 0)).toLocaleString('zh-CN');
}

function fmtMoney(value) {
  return '$' + Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(numerator, denominator) {
  return denominator > 0 ? (numerator / denominator * 100).toFixed(1) + '%' : '-';
}

function terminalLabel(row) {
  const app = String(row.app || '').toLowerCase();
  const source = String(row.source || '').toLowerCase();
  const originator = String(row.originator || '').toLowerCase();
  if (app === 'codex' && source === 'codex:vscode') {
    return originator.includes('codex desktop') ? 'Codex Desktop' : 'VS Code';
  }
  if (source.includes('vscode')) return 'VS Code';
  if (source.endsWith(':cli') || source === 'cli') return 'CLI';
  if (source.startsWith('warp') || app === 'warp') return 'Warp';
  if (source.startsWith('codebuddy') || app === 'codebuddy') return 'CodeBuddy';
  if (source.startsWith('chatgpt') || app === 'chatgpt') return 'ChatGPT';
  if (app) return row.app;
  return row.source || 'unknown';
}

function sourceRows() {
  const source = Array.isArray(RAW.by_source) && RAW.by_source.length ? RAW.by_source : [];
  if (source.length) return source;
  return (RAW.by_date || []).map(row => ({ ...row, model_label: '全部模型', app: 'unknown', source: 'unknown' }));
}

function availableDates() {
  return [...new Set(sourceRows().map(row => row.local_date).filter(Boolean))].sort();
}

function activeDates() {
  const dates = availableDates();
  const count = Math.min(state.range, dates.length);
  return dates.slice(Math.max(0, dates.length - count));
}

function filteredRows() {
  const dateSet = new Set(activeDates());
  return sourceRows().filter(row => {
    if (!dateSet.has(row.local_date)) return false;
    if (state.selectedModels.size === 0) return true;
    return state.selectedModels.has(row.model_label || 'Unknown');
  });
}

function aggregate(rows, keyFn) {
  const map = new Map();
  rows.forEach(row => {
    const key = keyFn(row);
    const item = map.get(key) || {
      key,
      total_tokens: 0,
      estimated_cost_usd: 0,
      input_tokens: 0,
      output_tokens: 0,
      cached_input_tokens: 0,
      reasoning_tokens: 0,
      unsplit_tokens: 0,
      credits: 0,
      records: 0,
    };
    ['total_tokens', 'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens', 'unsplit_tokens', 'records'].forEach(field => {
      item[field] += numberValue(row, field);
    });
    item.estimated_cost_usd += numberValue(row, 'estimated_cost_usd');
    item.credits += numberValue(row, 'credits');
    map.set(key, item);
  });
  return [...map.values()];
}

function dailyRows(rows) {
  const byDate = new Map(aggregate(rows, row => row.local_date).map(row => [row.key, row]));
  return activeDates().map(date => ({ key: date, local_date: date, ...(byDate.get(date) || {}) }));
}

function topModels(limit = 8) {
  return aggregate(filteredRows(), row => row.model_label || 'Unknown')
    .sort((a, b) => b.total_tokens - a.total_tokens)
    .slice(0, limit);
}

function allModels() {
  return aggregate(sourceRows(), row => row.model_label || 'Unknown')
    .filter(row => row.total_tokens > 0)
    .sort((a, b) => b.total_tokens - a.total_tokens);
}

function totalOf(rows) {
  return rows.reduce((acc, row) => {
    ['total_tokens', 'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens', 'unsplit_tokens', 'records'].forEach(field => {
      acc[field] += numberValue(row, field);
    });
    acc.estimated_cost_usd += numberValue(row, 'estimated_cost_usd');
    acc.credits += numberValue(row, 'credits');
    return acc;
  }, { total_tokens: 0, input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, reasoning_tokens: 0, unsplit_tokens: 0, records: 0, estimated_cost_usd: 0, credits: 0 });
}

function renderCards(rows) {
  const totals = totalOf(rows);
  const days = Math.max(activeDates().length, 1);
  const items = [
    ['总 Token', fmtInt(totals.total_tokens), '当前筛选范围'],
    ['预估费用', fmtMoney(totals.estimated_cost_usd), '仅 API 可估价记录'],
    ['Prompt', fmtInt(totals.input_tokens), '日均 ' + fmtInt(totals.input_tokens / days)],
    ['Output', fmtInt(totals.output_tokens), '生成输出'],
    ['缓存 Prompt', fmtInt(totals.cached_input_tokens), '命中率 ' + pct(totals.cached_input_tokens, totals.input_tokens)],
    ['Unsplit', fmtInt(totals.unsplit_tokens), 'total-only 事件'],
  ];
  document.getElementById('summaryCards').innerHTML = items.map(([label, value, detail]) => `
    <article class="metric"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>
  `).join('');
}

function renderModelChips() {
  const models = allModels().slice(0, 12);
  document.getElementById('modelChips').innerHTML = models.map(row => {
    const key = row.key;
    const active = state.selectedModels.size === 0 || state.selectedModels.has(key);
    return `<button type="button" class="chip ${active ? 'active' : ''}" data-model="${escapeHtml(key)}">${escapeHtml(key)} · ${fmtInt(row.total_tokens)}</button>`;
  }).join('');
  const label = state.selectedModels.size === 0 ? '当前显示全部模型。' : `当前显示 ${state.selectedModels.size} 个模型。`;
  document.getElementById('filterHint').textContent = `${label} 时间范围：最近 ${state.range} 天。`;
}

function lineChart(rows, key, options = {}) {
  const unit = options.unit || 'tokens';
  const color = options.color || '#1b365d';
  const values = rows.map(row => Number(row[key] || 0));
  const max = Math.max(...values, 0);
  if (!rows.length || max <= 0) return '<p class="empty">暂无记录。</p>';
  const w = 760, h = 280, left = 62, right = 22, top = 22, bottom = 52;
  const cw = w - left - right, ch = h - top - bottom;
  const points = rows.map((row, idx) => {
    const x = left + cw * idx / Math.max(rows.length - 1, 1);
    const y = top + ch - ch * Number(row[key] || 0) / max;
    return [x, y, Number(row[key] || 0), row.local_date || row.key];
  });
  const pointText = points.map(point => `${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ');
  const area = `M ${left},${top + ch} L ${pointText} L ${left + cw},${top + ch} Z`;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${key}">
    ${grid(left, top, cw, ch, max, unit)}
    <path class="area" d="${area}"></path>
    <polyline class="line" style="stroke:${color}" points="${pointText}"></polyline>
    ${points.map(point => `<circle cx="${point[0].toFixed(2)}" cy="${point[1].toFixed(2)}" r="4" fill="#faf9f5" stroke="${color}" stroke-width="3"><title>${point[3]}: ${formatByUnit(point[2], unit)}</title></circle>`).join('')}
    ${axisLabels(rows, left, cw, top + ch + 26)}
  </svg>`;
}

function barChart(rows, key, options = {}) {
  const unit = options.unit || 'tokens';
  const color = options.color || '#b56b35';
  const values = rows.map(row => Number(row[key] || 0));
  const max = Math.max(...values, 0);
  if (!rows.length || max <= 0) return '<p class="empty">暂无记录。</p>';
  const w = 760, h = 280, left = 62, right = 22, top = 22, bottom = 52;
  const cw = w - left - right, ch = h - top - bottom;
  const gap = 7;
  const bw = Math.max(8, (cw - gap * Math.max(rows.length - 1, 0)) / Math.max(rows.length, 1));
  return `<svg class="chart bars" viewBox="0 0 ${w} ${h}" role="img" aria-label="${key}">
    ${grid(left, top, cw, ch, max, unit)}
    ${rows.map((row, idx) => {
      const value = Number(row[key] || 0);
      const bh = ch * value / max;
      const x = left + idx * (bw + gap);
      const y = top + ch - bh;
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${bw.toFixed(2)}" height="${bh.toFixed(2)}" rx="5" fill="${color}"><title>${row.local_date || row.key}: ${formatByUnit(value, unit)}</title></rect>`;
    }).join('')}
    ${axisLabels(rows, left, cw, top + ch + 26)}
  </svg>`;
}

function multiLineChart(rows, series) {
  const max = Math.max(...series.flatMap(item => rows.map(row => Number(row[item.key] || 0))), 0);
  if (!rows.length || max <= 0) return '<p class="empty">暂无记录。</p>';
  const w = 760, h = 280, left = 62, right = 22, top = 22, bottom = 62;
  const cw = w - left - right, ch = h - top - bottom;
  const legend = `<div class="legend">${series.map(item => `<span><i style="background:${item.color}"></i>${item.label}</span>`).join('')}</div>`;
  const lines = series.map(item => {
    const points = rows.map((row, idx) => {
      const value = Number(row[item.key] || 0);
      const x = left + cw * idx / Math.max(rows.length - 1, 1);
      const y = top + ch - ch * value / max;
      return [x, y, value, row.local_date || row.key];
    });
    return `<polyline class="multi-line" points="${points.map(point => `${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ')}" stroke="${item.color}"></polyline>
      ${points.map(point => `<circle cx="${point[0].toFixed(2)}" cy="${point[1].toFixed(2)}" r="3" fill="${item.color}"><title>${item.label} · ${point[3]}: ${fmtInt(point[2])}</title></circle>`).join('')}`;
  }).join('');
  return `${legend}<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="multi-line">
    ${grid(left, top, cw, ch, max, 'tokens')}
    ${lines}
    ${axisLabels(rows, left, cw, top + ch + 26)}
  </svg>`;
}

function stackedModelTrend(rows, models) {
  if (!rows.length || !models.length) return '<p class="empty">暂无记录。</p>';
  const byDateModel = new Map();
  filteredRows().forEach(row => {
    const model = row.model_label || 'Unknown';
    if (!models.includes(model)) return;
    const key = `${row.local_date}||${model}`;
    byDateModel.set(key, (byDateModel.get(key) || 0) + numberValue(row, 'total_tokens'));
  });
  const daily = activeDates().map(date => ({ key: date, local_date: date }));
  const series = models.map((model, idx) => ({
    label: model,
    key: model,
    color: COLORS[idx % COLORS.length],
  }));
  daily.forEach(row => {
    models.forEach(model => {
      row[model] = byDateModel.get(`${row.local_date}||${model}`) || 0;
    });
  });
  return multiLineChart(daily, series);
}

function donut(rows, labelKey, valueKey) {
  const visible = rows.filter(row => Number(row[valueKey] || 0) > 0).slice(0, 8);
  const total = visible.reduce((sum, row) => sum + Number(row[valueKey] || 0), 0);
  if (total <= 0) return '<p class="empty">暂无记录。</p>';
  let cursor = 0;
  const stops = visible.map((row, idx) => {
    const pctValue = Number(row[valueKey] || 0) / total * 100;
    const color = COLORS[idx % COLORS.length];
    const stop = `${color} ${cursor.toFixed(4)}% ${(cursor + pctValue).toFixed(4)}%`;
    cursor += pctValue;
    return stop;
  });
  return `<div class="donut-wrap">
    <div class="donut" style="background: conic-gradient(${stops.join(', ')});"><span>${fmtInt(total)}</span></div>
    <ul class="share-list">${visible.map((row, idx) => `<li><span><i style="background:${COLORS[idx % COLORS.length]}"></i>${escapeHtml(row[labelKey] || row.key)}</span><strong>${fmtInt(row[valueKey])}</strong></li>`).join('')}</ul>
  </div>`;
}

function rankedBars(rows, labelKey, valueKey, limit = 8) {
  const visible = rows.filter(row => Number(row[valueKey] || 0) > 0).slice(0, limit);
  const max = Math.max(...visible.map(row => Number(row[valueKey] || 0)), 0);
  if (max <= 0) return '<p class="empty">暂无记录。</p>';
  return `<ul class="rank-list">${visible.map((row, idx) => {
    const width = Number(row[valueKey] || 0) / max * 100;
    return `<li class="rank-row"><span title="${escapeHtml(row[labelKey] || row.key)}">${escapeHtml(row[labelKey] || row.key)}</span><div><i style="width:${width.toFixed(2)}%; background:${COLORS[idx % COLORS.length]}"></i></div><strong>${fmtInt(row[valueKey])}</strong></li>`;
  }).join('')}</ul>`;
}

function dailyTable(rows) {
  if (!rows.length) return '<p class="empty">暂无记录。</p>';
  return `<div class="table-wrap"><table>
    <thead><tr><th>日期</th><th>总量</th><th>预估费用</th><th>Prompt</th><th>Output</th><th>缓存 Prompt</th><th>Reasoning</th><th>Unsplit</th><th>记录</th></tr></thead>
    <tbody>${[...rows].reverse().map(row => `<tr>
      <td>${escapeHtml(row.local_date || row.key)}</td>
      <td>${fmtInt(row.total_tokens)}</td>
      <td>${fmtMoney(row.estimated_cost_usd)}</td>
      <td>${fmtInt(row.input_tokens)}</td>
      <td>${fmtInt(row.output_tokens)}</td>
      <td>${fmtInt(row.cached_input_tokens)}</td>
      <td>${fmtInt(row.reasoning_tokens)}</td>
      <td>${fmtInt(row.unsplit_tokens)}</td>
      <td>${fmtInt(row.records)}</td>
    </tr>`).join('')}</tbody>
  </table></div>`;
}

function grid(left, top, width, height, max, unit) {
  return [0, 1, 2, 3].map(idx => {
    const ratio = idx / 3;
    const y = top + height - height * ratio;
    return `<line class="grid" x1="${left}" y1="${y.toFixed(2)}" x2="${left + width}" y2="${y.toFixed(2)}"></line>
      <text class="axis-value" x="${left - 10}" y="${(y + 4).toFixed(2)}" text-anchor="end">${axisValue(max * ratio, unit)}</text>`;
  }).join('');
}

function axisLabels(rows, left, width, y) {
  const indexes = new Set([0, rows.length - 1]);
  if (rows.length > 4) indexes.add(Math.floor(rows.length / 2));
  else if (rows.length > 2) indexes.add(1);
  return [...indexes].sort((a, b) => a - b).map(idx => {
    const x = left + width * idx / Math.max(rows.length - 1, 1);
    return `<text class="axis-label" x="${x.toFixed(2)}" y="${y}" text-anchor="middle">${escapeHtml(rows[idx].local_date || rows[idx].key)}</text>`;
  }).join('');
}

function axisValue(value, unit) {
  if (unit === '$') return value >= 10 ? '$' + value.toFixed(0) : '$' + value.toFixed(1);
  if (unit === '%') return value.toFixed(0) + '%';
  if (value >= 1000000000) return (value / 1000000000).toFixed(1) + 'B';
  if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
  if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
  return value.toFixed(0);
}

function formatByUnit(value, unit) {
  if (unit === '%') return value.toFixed(1) + '%';
  return unit === '$' ? fmtMoney(value) : fmtInt(value);
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderDashboard() {
  const rows = filteredRows();
  const daily = dailyRows(rows);
  const models = topModels(8);
  const terminals = aggregate(rows, terminalLabel).sort((a, b) => b.total_tokens - a.total_tokens);
  const apps = aggregate(rows, row => row.app || 'unknown').sort((a, b) => b.total_tokens - a.total_tokens);
  const modelNames = models.slice(0, Math.min(5, models.length)).map(row => row.key);

  renderCards(rows);
  renderModelChips();
  document.getElementById('totalTrend').innerHTML = lineChart(daily, 'total_tokens', { unit: 'tokens', color: '#1b365d' });
  document.getElementById('costTrend').innerHTML = barChart(daily, 'estimated_cost_usd', { unit: '$', color: '#b56b35' });
  document.getElementById('promptTrend').innerHTML = multiLineChart(daily, [
    { label: 'Prompt', key: 'input_tokens', color: '#1b365d' },
    { label: '缓存 Prompt', key: 'cached_input_tokens', color: '#2f6f55' },
    { label: 'Output', key: 'output_tokens', color: '#b56b35' },
  ]);
  const cacheRows = daily.map(row => ({ ...row, cache_rate: row.input_tokens ? row.cached_input_tokens / row.input_tokens * 100 : 0 }));
  document.getElementById('cacheTrend').innerHTML = lineChart(cacheRows, 'cache_rate', { unit: '%', color: '#2f6f55' });
  document.getElementById('modelRank').innerHTML = rankedBars(models, 'key', 'total_tokens', 8);
  document.getElementById('modelTrend').innerHTML = stackedModelTrend(daily, modelNames);
  document.getElementById('terminalShare').innerHTML = donut(terminals, 'key', 'total_tokens');
  document.getElementById('appRank').innerHTML = rankedBars(apps, 'key', 'total_tokens', 8);
  document.getElementById('recordTrend').innerHTML = barChart(daily, 'records', { unit: 'tokens', color: '#a38635' });
  document.getElementById('unsplitTrend').innerHTML = lineChart(daily, 'unsplit_tokens', { unit: 'tokens', color: '#9b5864' });
  document.getElementById('dailyTable').innerHTML = dailyTable(daily);
}

function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('visible'), 4200);
}

document.addEventListener('click', event => {
  const rangeButton = event.target.closest('[data-range]');
  if (rangeButton) {
    state.range = Number(rangeButton.dataset.range);
    document.querySelectorAll('.range-button').forEach(button => button.classList.toggle('active', button === rangeButton));
    renderDashboard();
    return;
  }
  const chip = event.target.closest('[data-model]');
  if (chip) {
    const model = chip.dataset.model;
    if (state.selectedModels.size === 0) {
      allModels().slice(0, 12).forEach(row => state.selectedModels.add(row.key));
    }
    if (state.selectedModels.has(model)) state.selectedModels.delete(model);
    else state.selectedModels.add(model);
    if (state.selectedModels.size === allModels().slice(0, 12).length) state.selectedModels.clear();
    renderDashboard();
  }
});

document.getElementById('selectCoreModels').addEventListener('click', () => {
  state.selectedModels = new Set(allModels().slice(0, 4).map(row => row.key));
  renderDashboard();
});

document.getElementById('selectAllModels').addEventListener('click', () => {
  state.selectedModels.clear();
  renderDashboard();
});

document.getElementById('rescanButton').addEventListener('click', async () => {
  const command = window.TOKKIT_SCAN_COMMAND || 'tok scan all && tok html month open';
  try {
    await navigator.clipboard.writeText(command);
    showToast(`当前是静态 HTML，浏览器不能直接执行本地命令。已复制：${command}`);
  } catch {
    showToast(`当前是静态 HTML，请在终端执行：${command}`);
  }
});

renderDashboard();
"""
