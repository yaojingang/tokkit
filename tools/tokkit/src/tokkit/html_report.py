from __future__ import annotations

from html import escape
from typing import Any, Iterable


_COLORS = ("#246b57", "#d67c2c", "#3f73b7", "#9b4d2e", "#707a3f", "#4d6f85", "#a44d61", "#6a6f7a")


def render_range_html_report(
    payload: dict[str, Any],
    *,
    generated_at: str,
    timezone_name: str,
) -> str:
    days = int(payload.get("range_days") or 0)
    by_date = list(payload.get("by_date") or [])
    by_terminal = list(payload.get("by_terminal") or [])
    by_model = list(payload.get("by_model") or [])
    chronological = list(reversed(by_date))
    totals = _totals(by_date)
    title = f"TokKit Usage Report - Last {days} Days"

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)}</title>",
            f"<style>{_css()}</style>",
            "</head>",
            "<body>",
            '<main class="report-shell">',
            _hero(title, generated_at, timezone_name, totals),
            _metric_grid(totals),
            '<section class="chart-grid">',
            _panel(
                "Daily Token Trend",
                _line_chart(chronological, label_field="local_date", value_field="total_tokens", unit="tokens"),
            ),
            _panel(
                "Estimated Cost Trend",
                _bar_chart(chronological, label_field="local_date", value_field="estimated_cost_usd", unit="$"),
            ),
            _panel(
                "Prompt / Output / Cache",
                _multi_line_chart(
                    chronological,
                    label_field="local_date",
                    series=[
                        ("Prompt", "input_tokens", "#246b57"),
                        ("Cached Prompt", "cached_input_tokens", "#8aa15b"),
                        ("Output", "output_tokens", "#d67c2c"),
                    ],
                ),
            ),
            _panel(
                "Terminal Share",
                _donut_with_legend(by_terminal, label_field="terminal", value_field="total_tokens"),
            ),
            "</section>",
            '<section class="wide-grid">',
            _panel("Top Models", _ranked_bars(by_model, label_field="model_label", value_field="total_tokens", limit=8)),
            _panel("Daily Breakdown", _daily_table(by_date)),
            "</section>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _totals(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    total = {
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "unsplit_tokens": 0,
        "credits": 0.0,
        "records": 0,
        "peak_day": "-",
        "peak_tokens": 0,
        "days_with_records": 0,
    }
    for row in rows:
        total["days_with_records"] += 1
        for key in (
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "unsplit_tokens",
            "records",
        ):
            total[key] += int(row.get(key) or 0)
        total["estimated_cost_usd"] += float(row.get("estimated_cost_usd") or 0.0)
        total["credits"] += float(row.get("credits") or 0.0)
        row_tokens = int(row.get("total_tokens") or 0)
        if row_tokens >= int(total["peak_tokens"]):
            total["peak_tokens"] = row_tokens
            total["peak_day"] = str(row.get("local_date") or "-")
    total["estimated_cost_usd"] = round(float(total["estimated_cost_usd"]), 8)
    total["credits"] = round(float(total["credits"]), 8)
    return total


def _hero(title: str, generated_at: str, timezone_name: str, totals: dict[str, Any]) -> str:
    cache_rate = _ratio(int(totals["cached_input_tokens"]), int(totals["input_tokens"]))
    return f"""
<section class="hero">
  <div>
    <p class="eyebrow">Local AI usage ledger</p>
    <h1>{escape(title)}</h1>
    <p class="subtle">Generated {escape(generated_at)} · {escape(timezone_name)}</p>
  </div>
  <div class="hero-stat">
    <span>Cache rate</span>
    <strong>{cache_rate}</strong>
    <small>Cached Prompt / Prompt</small>
  </div>
</section>"""


def _metric_grid(totals: dict[str, Any]) -> str:
    avg_daily = int(int(totals["total_tokens"]) / max(int(totals["days_with_records"]), 1))
    items = [
        ("Total Tokens", _fmt_int(totals["total_tokens"]), f"Peak {escape(str(totals['peak_day']))}: {_fmt_int(totals['peak_tokens'])}"),
        ("Estimated Cost", _fmt_money(totals["estimated_cost_usd"]), "API-priced rows only"),
        ("Prompt", _fmt_int(totals["input_tokens"]), f"Avg/day {_fmt_int(avg_daily)}"),
        ("Output", _fmt_int(totals["output_tokens"]), f"Records {_fmt_int(totals['records'])}"),
        ("Cached Prompt", _fmt_int(totals["cached_input_tokens"]), _ratio(int(totals["cached_input_tokens"]), int(totals["input_tokens"]))),
        ("Unsplit", _fmt_int(totals["unsplit_tokens"]), "Total-only events"),
    ]
    cards = "\n".join(
        f"""
<article class="metric">
  <span>{escape(label)}</span>
  <strong>{escape(value)}</strong>
  <small>{detail}</small>
</article>"""
        for label, value, detail in items
    )
    return f'<section class="metrics">{cards}</section>'


def _panel(title: str, body: str) -> str:
    return f"""
<section class="panel">
  <h2>{escape(title)}</h2>
  {body}
</section>"""


def _line_chart(rows: list[dict[str, Any]], *, label_field: str, value_field: str, unit: str) -> str:
    values = [float(row.get(value_field) or 0.0) for row in rows]
    if not rows or max(values or [0.0]) <= 0:
        return '<p class="empty">No records.</p>'

    width = 760
    height = 280
    left = 58
    right = 22
    top = 22
    bottom = 52
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max(values)
    points = [
        (
            left + (chart_w * idx / max(len(values) - 1, 1)),
            top + chart_h - (chart_h * value / max_value),
            value,
        )
        for idx, value in enumerate(values)
    ]
    point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y, _ in points)
    area_path = f"M {left},{top + chart_h} L {point_text} L {left + chart_w},{top + chart_h} Z"
    circles = "\n".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4"><title>{escape(str(rows[idx].get(label_field)))}: {escape(_fmt_number(value, unit))}</title></circle>'
        for idx, (x, y, value) in enumerate(points)
    )
    labels = _axis_labels(rows, label_field, left, chart_w, top + chart_h + 25)
    grid = _grid_lines(left, top, chart_w, chart_h, max_value, unit)
    return f"""
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(value_field)} trend">
  {grid}
  <path class="area" d="{area_path}"></path>
  <polyline class="line" points="{point_text}"></polyline>
  <g class="points">{circles}</g>
  {labels}
</svg>"""


def _multi_line_chart(
    rows: list[dict[str, Any]],
    *,
    label_field: str,
    series: list[tuple[str, str, str]],
) -> str:
    max_value = max((float(row.get(field) or 0.0) for _, field, _ in series for row in rows), default=0.0)
    if not rows or max_value <= 0:
        return '<p class="empty">No records.</p>'

    width = 760
    height = 280
    left = 58
    right = 22
    top = 22
    bottom = 64
    chart_w = width - left - right
    chart_h = height - top - bottom
    grid = _grid_lines(left, top, chart_w, chart_h, max_value, "tokens")
    lines: list[str] = [grid]
    for label, field, color in series:
        points = []
        for idx, row in enumerate(rows):
            value = float(row.get(field) or 0.0)
            x = left + (chart_w * idx / max(len(rows) - 1, 1))
            y = top + chart_h - (chart_h * value / max_value)
            points.append((x, y, value))
        point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y, _ in points)
        dots = "\n".join(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"><title>{escape(label)} · {escape(str(rows[idx].get(label_field)))}: {escape(_fmt_int(value))}</title></circle>'
            for idx, (x, y, value) in enumerate(points)
        )
        lines.append(f'<polyline class="multi-line" points="{point_text}" stroke="{color}"></polyline>')
        lines.append(dots)
    labels = _axis_labels(rows, label_field, left, chart_w, top + chart_h + 25)
    legend = "".join(
        f'<span><i style="background:{color}"></i>{escape(label)}</span>'
        for label, _, color in series
    )
    return f"""
<div class="legend">{legend}</div>
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="prompt output cache trend">
  {"".join(lines)}
  {labels}
</svg>"""


def _bar_chart(rows: list[dict[str, Any]], *, label_field: str, value_field: str, unit: str) -> str:
    values = [float(row.get(value_field) or 0.0) for row in rows]
    if not rows or max(values or [0.0]) <= 0:
        return '<p class="empty">No records.</p>'

    width = 760
    height = 280
    left = 58
    right = 22
    top = 22
    bottom = 52
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max(values)
    gap = 7
    bar_w = max(8, (chart_w - gap * max(len(rows) - 1, 0)) / max(len(rows), 1))
    bars = []
    for idx, row in enumerate(rows):
        value = float(row.get(value_field) or 0.0)
        h = chart_h * value / max_value
        x = left + idx * (bar_w + gap)
        y = top + chart_h - h
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" rx="5"><title>{escape(str(row.get(label_field)))}: {escape(_fmt_number(value, unit))}</title></rect>'
        )
    labels = _axis_labels(rows, label_field, left, chart_w, top + chart_h + 25)
    grid = _grid_lines(left, top, chart_w, chart_h, max_value, unit)
    return f"""
<svg class="chart bars" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(value_field)} bars">
  {grid}
  {"".join(bars)}
  {labels}
</svg>"""


def _donut_with_legend(rows: list[dict[str, Any]], *, label_field: str, value_field: str) -> str:
    visible = [row for row in rows if int(row.get(value_field) or 0) > 0][:8]
    total = sum(int(row.get(value_field) or 0) for row in visible)
    if total <= 0:
        return '<p class="empty">No records.</p>'

    cursor = 0.0
    stops: list[str] = []
    legend_rows: list[str] = []
    for idx, row in enumerate(visible):
        value = int(row.get(value_field) or 0)
        percent = value / total * 100
        color = _COLORS[idx % len(_COLORS)]
        stops.append(f"{color} {cursor:.4f}% {cursor + percent:.4f}%")
        cursor += percent
        legend_rows.append(
            f"""
<li>
  <span><i style="background:{color}"></i>{escape(str(row.get(label_field) or '-'))}</span>
  <strong>{_fmt_int(value)}</strong>
</li>"""
        )
    return f"""
<div class="donut-wrap">
  <div class="donut" style="background: conic-gradient({", ".join(stops)});">
    <span>{_fmt_int(total)}</span>
  </div>
  <ul class="share-list">{"".join(legend_rows)}</ul>
</div>"""


def _ranked_bars(rows: list[dict[str, Any]], *, label_field: str, value_field: str, limit: int) -> str:
    visible = [row for row in rows if int(row.get(value_field) or 0) > 0][:limit]
    if not visible:
        return '<p class="empty">No records.</p>'
    max_value = max(int(row.get(value_field) or 0) for row in visible)
    items = []
    for idx, row in enumerate(visible):
        value = int(row.get(value_field) or 0)
        width = value / max_value * 100
        items.append(
            f"""
<li class="rank-row">
  <span>{escape(str(row.get(label_field) or '-'))}</span>
  <div><i style="width:{width:.2f}%; background:{_COLORS[idx % len(_COLORS)]}"></i></div>
  <strong>{_fmt_int(value)}</strong>
</li>"""
        )
    return f'<ul class="rank-list">{"".join(items)}</ul>'


def _daily_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No records.</p>'
    body = "\n".join(
        f"""
<tr>
  <td>{escape(str(row.get("local_date") or "-"))}</td>
  <td>{_fmt_int(row.get("total_tokens"))}</td>
  <td>{_fmt_money(row.get("estimated_cost_usd"))}</td>
  <td>{_fmt_int(row.get("input_tokens"))}</td>
  <td>{_fmt_int(row.get("output_tokens"))}</td>
  <td>{_fmt_int(row.get("cached_input_tokens"))}</td>
  <td>{_fmt_int(row.get("unsplit_tokens"))}</td>
</tr>"""
        for row in rows
    )
    return f"""
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Total</th>
        <th>Est.$</th>
        <th>Prompt</th>
        <th>Output</th>
        <th>Cached Prompt</th>
        <th>Unsplit</th>
      </tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
</div>"""


def _axis_labels(rows: list[dict[str, Any]], label_field: str, left: int, chart_w: int, y: int) -> str:
    if not rows:
        return ""
    indexes = {0, len(rows) - 1}
    if len(rows) > 4:
        indexes.add(len(rows) // 2)
    elif len(rows) > 2:
        indexes.add(1)
    labels = []
    for idx in sorted(indexes):
        x = left + (chart_w * idx / max(len(rows) - 1, 1))
        label = str(rows[idx].get(label_field) or "-")
        labels.append(f'<text class="axis-label" x="{x:.2f}" y="{y}" text-anchor="middle">{escape(label)}</text>')
    return "".join(labels)


def _grid_lines(left: int, top: int, chart_w: int, chart_h: int, max_value: float, unit: str) -> str:
    lines = []
    for idx in range(4):
        ratio = idx / 3
        y = top + chart_h - chart_h * ratio
        value = max_value * ratio
        lines.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}"></line>')
        lines.append(f'<text class="axis-value" x="{left - 10}" y="{y + 4:.2f}" text-anchor="end">{escape(_fmt_axis(value, unit))}</text>')
    return "".join(lines)


def _fmt_axis(value: float, unit: str) -> str:
    if unit == "$":
        return f"${value:.0f}" if value >= 10 else f"${value:.1f}"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def _fmt_number(value: float, unit: str) -> str:
    if unit == "$":
        return _fmt_money(value)
    return _fmt_int(value)


def _fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    return f"{int(float(value)):,}"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "-"
    return f"${float(value):,.2f}"


def _ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "-"
    return f"{numerator / denominator * 100:.1f}%"


def _css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f4f7f4;
  --ink: #18201d;
  --muted: #66716b;
  --panel: #ffffff;
  --line: #dbe2dd;
  --green: #246b57;
  --orange: #d67c2c;
  --blue: #3f73b7;
  --shadow: 0 18px 55px rgba(28, 44, 36, 0.10);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background:
    linear-gradient(135deg, rgba(36, 107, 87, 0.10), transparent 32rem),
    linear-gradient(225deg, rgba(214, 124, 44, 0.10), transparent 28rem),
    var(--bg);
  color: var(--ink);
  font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", sans-serif;
}
.report-shell {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 34px 0 54px;
}
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 24px;
  align-items: end;
  margin-bottom: 22px;
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--green);
  font-size: 13px;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
h1 {
  margin: 0;
  font-size: clamp(34px, 5vw, 70px);
  line-height: 0.94;
  letter-spacing: 0;
}
.subtle {
  margin: 16px 0 0;
  color: var(--muted);
  font-size: 15px;
}
.hero-stat {
  background: var(--ink);
  color: #fff;
  border-radius: 8px;
  padding: 18px;
  box-shadow: var(--shadow);
}
.hero-stat span,
.hero-stat small {
  color: rgba(255, 255, 255, 0.70);
  display: block;
  font-size: 13px;
}
.hero-stat strong {
  display: block;
  margin: 8px 0 4px;
  font-size: 42px;
  line-height: 1;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.metric,
.panel {
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(219, 226, 221, 0.95);
  border-radius: 8px;
  box-shadow: var(--shadow);
}
.metric {
  min-width: 0;
  padding: 15px;
}
.metric span {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.metric strong {
  display: block;
  margin: 7px 0 5px;
  font-size: clamp(20px, 2.6vw, 30px);
  line-height: 1.05;
  overflow-wrap: anywhere;
}
.metric small {
  color: var(--muted);
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.wide-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.8fr) minmax(0, 1.2fr);
  gap: 18px;
  margin-top: 18px;
}
.panel {
  min-width: 0;
  padding: 18px;
}
.panel h2 {
  margin: 0 0 14px;
  font-size: 18px;
  letter-spacing: 0;
}
.chart {
  width: 100%;
  height: auto;
  display: block;
}
.grid {
  stroke: var(--line);
  stroke-width: 1;
}
.axis-label,
.axis-value {
  fill: var(--muted);
  font-size: 12px;
}
.area {
  fill: rgba(36, 107, 87, 0.14);
}
.line {
  fill: none;
  stroke: var(--green);
  stroke-width: 4;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.points circle {
  fill: #fff;
  stroke: var(--green);
  stroke-width: 3;
}
.bars rect {
  fill: var(--orange);
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
  margin-bottom: 4px;
  color: var(--muted);
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
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 20px;
  align-items: center;
}
.donut {
  position: relative;
  width: 190px;
  aspect-ratio: 1;
  border-radius: 50%;
}
.donut::after {
  content: "";
  position: absolute;
  inset: 34px;
  background: var(--panel);
  border-radius: 50%;
}
.donut span {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-items: center;
  text-align: center;
  font-weight: 800;
  font-size: 17px;
  padding: 50px;
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
  border-bottom: 1px solid var(--line);
}
.share-list strong,
.rank-row strong {
  font-variant-numeric: tabular-nums;
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
  background: #e9eee9;
  border-radius: 999px;
  overflow: hidden;
}
.rank-row i {
  display: block;
  height: 100%;
  border-radius: inherit;
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
  border-bottom: 1px solid var(--line);
  text-align: right;
  white-space: nowrap;
}
th:first-child,
td:first-child {
  text-align: left;
}
th {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.empty {
  margin: 0;
  color: var(--muted);
}
@media (max-width: 900px) {
  .hero,
  .chart-grid,
  .wide-grid {
    grid-template-columns: 1fr;
  }
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .hero-stat {
    width: min(100%, 260px);
  }
}
@media (max-width: 560px) {
  .report-shell {
    width: min(100% - 20px, 1180px);
    padding-top: 22px;
  }
  .metrics,
  .donut-wrap,
  .rank-row {
    grid-template-columns: 1fr;
  }
  .donut {
    width: min(190px, 100%);
  }
  .rank-row {
    gap: 7px;
  }
}
"""
