"""纯 Python 交互式 HTML 报告生成。

不依赖 web/ 目录或 Node.js，直接用 Plotly Python API 生成图表，
嵌入 ~300 行 JS 实现跨图表点选联动和图表目录功能。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vo_eval.chart_specs import build_vloc_figures, build_vo_figures


def report_to_interactive_html(report: dict, entry_mode: str) -> str:
    """主入口：根据报告字典生成交互式 HTML 字符串。"""
    # 自动检测 entry_mode（优先从报告内部获取）
    actual_mode = report.get("inputs", {}).get("entry_mode", entry_mode)
    if actual_mode not in ("vloc", "vo"):
        actual_mode = entry_mode

    css = _build_css()
    metric_cards = _build_metric_cards(report, actual_mode)
    chart_directory = _build_chart_directory(actual_mode)
    point_selection_panel = _build_point_selection_panel()
    interaction_js = _interaction_js()

    # 生成图表
    if actual_mode == "vloc":
        figures = build_vloc_figures(report)
    else:
        figures = build_vo_figures(report)

    # 构建图表容器 HTML 和渲染脚本
    chart_containers = []
    chart_render_calls = []
    for fig_info in figures:
        chart_id = fig_info["id"]
        fig = fig_info["figure"]
        # 容器 div：id 与 Plotly 渲染目标一致
        chart_containers.append(
            f'<div id="{chart_id}" class="chart" data-chart-id="{chart_id}"></div>'
        )
        # 获取图表的 data 和 layout JSON
        chart_json = fig.to_json()
        data_json, layout_json = _split_plotly_json(chart_json)
        # 生成渲染调用: Plotly.newPlot(divId, data, layout, config)
        chart_render_calls.append(
            f'Plotly.newPlot("{chart_id}", {data_json}, {layout_json}, '
            f'{{responsive: true, displayModeBar: true}});'
        )

    chart_grid = "\n".join(chart_containers)
    render_script = "\n".join(chart_render_calls)

    # 构建运行结果标题
    mode_label = "VLOC" if actual_mode == "vloc" else "VO"
    result_heading = f'<h2>{mode_label} 运行结果</h2>'

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>VO 评估报告</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>VO 评估报告</h1>
    <span class="status-badge">{actual_mode.upper()}</span>
  </header>
  <main class="layout">
    <aside class="panel controls">
      {metric_cards}
      {chart_directory}
      {point_selection_panel}
    </aside>
    <section class="content">
      {result_heading}
      <div class="chart-grid">
        {chart_grid}
      </div>
    </section>
  </main>
  <script>
{render_script}
{interaction_js}
  </script>
</body>
</html>"""
    return html


def _split_plotly_json(chart_json: str) -> tuple[str, str]:
    """将 Plotly 的 to_json() 输出拆分为 data 和 layout 的 JSON 字符串。

    Plotly to_json() 返回 '{"data": [...], "layout": {...}}'，
    我们需要分别传给 Plotly.newPlot(divId, data, layout, config)。
    """
    try:
        parsed = json.loads(chart_json)
        data = parsed.get("data", [])
        layout = parsed.get("layout", {})
        return json.dumps(data), json.dumps(layout)
    except (json.JSONDecodeError, TypeError):
        return "[]", "{}"


def _build_css() -> str:
    """返回嵌入式 CSS，定义布局和样式。"""
    return """
/* ========== 基础布局 ========== */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f8fafc;
  color: #1e293b;
}

header {
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  padding: 1rem 2rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}

header h1 {
  font-size: 1.25rem;
  font-weight: 600;
}

.status-badge {
  background: #2563eb;
  color: #fff;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}

.layout {
  display: flex;
  gap: 1.5rem;
  padding: 1.5rem;
  max-width: 100%;
}

.panel.controls {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  overflow-y: auto;
  max-height: calc(100vh - 4rem);
}

.content {
  flex: 1;
  min-width: 0;
}

/* ========== 指标卡片 ========== */
.metric-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

.metric-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.metric-kicker {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.25rem;
}

.metric-value {
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
}

/* ========== 图表网格 ========== */
.chart-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.5rem;
}

.chart {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
  min-height: 400px;
}

/* ========== 图表目录 ========== */
.chart-directory-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
}

.chart-directory-section h2 {
  font-size: 0.875rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.chart-directory-controls {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.chart-directory-controls button {
  padding: 0.25rem 0.75rem;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 4px;
  font-size: 0.75rem;
  cursor: pointer;
}

.chart-directory-controls button:hover {
  background: #f1f5f9;
}

.chart-directory-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chart-directory-list label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.chart-directory-list input[type="checkbox"] {
  accent-color: #2563eb;
}

/* ========== 点选输出面板 ========== */
#pointSelectionOutputSection {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
}

#pointSelectionOutputSection h2 {
  font-size: 0.875rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.section-hint {
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 0.75rem;
}

#pointSelectionOutput {
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 0.75rem;
}

.point-selection-item {
  padding: 0.5rem;
  margin-bottom: 0.5rem;
  background: #f8fafc;
  border-radius: 4px;
  font-size: 0.75rem;
}

.point-selection-item div {
  margin-bottom: 0.25rem;
}

#clearAllPointSelections {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #dc2626;
  background: #fff;
  color: #dc2626;
  border-radius: 4px;
  font-size: 0.75rem;
  cursor: pointer;
}

#clearAllPointSelections:hover {
  background: #fef2f2;
}
"""


def _format_value(value: Any, precision: int = 4) -> str:
    """格式化数值，处理 None 和非数值类型。"""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    if isinstance(value, (int, str)):
        return str(value)
    return str(value)


def _build_metric_cards(report: dict, entry_mode: str) -> str:
    """提取关键指标并生成 HTML 卡片。"""
    cards = []

    if entry_mode == "vloc":
        # VLOC 指标在 vloc_details.summary 中
        vds = report.get("vloc_details", {}).get("summary", {})
        metrics = [
            ("平均水平位置误差", vds.get("mean_error_pos_xy")),
            ("最大水平位置误差", vds.get("max_error_pos_xy")),
            ("平均高度误差", vds.get("mean_error_pos_z")),
            ("最大高度误差", vds.get("max_error_pos_z")),
            ("平均欧拉角误差", vds.get("mean_error_euler")),
            ("最大欧拉角误差", vds.get("max_error_euler")),
            ("轨迹长度", vds.get("trajectory_length_m")),
        ]
    else:  # vo
        ate_position = report.get("ate_position_m", {})
        ate_horizontal = report.get("ate_horizontal_m", {})
        ate_vertical = report.get("ate_vertical_m", {})
        rpe_frame_delta = report.get("rpe_frame_delta", {})
        summary = report.get("summary", {})
        alignment = report.get("alignment", {})

        metrics = [
            ("ATE 位置 RMSE", ate_position.get("rmse")),
            ("ATE 水平 RMSE", ate_horizontal.get("rmse")),
            ("ATE 垂直 RMSE", ate_vertical.get("rmse")),
            ("RPE 平移 RMSE", rpe_frame_delta.get("translation_m", {}).get("rmse")),
            ("GT 路径长度", summary.get("gt_path_length_m")),
            ("持续时间", summary.get("duration_s")),
            ("匹配位姿数", summary.get("matched_poses")),
            ("对齐尺度", alignment.get("scale")),
        ]

    for label, value in metrics:
        formatted = _format_value(value)
        cards.append(
            f'<div class="metric-card">'
            f'<div class="metric-kicker">{label}</div>'
            f'<div class="metric-value">{formatted}</div>'
            f"</div>"
        )

    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def _build_chart_directory(entry_mode: str) -> str:
    """生成图表可见性控制的复选框列表。"""
    if entry_mode == "vloc":
        charts = [
            ("trajectory3d", "3D 轨迹"),
            ("trajectoryXY", "俯视 NE 轨迹"),
            ("errorDistance", "误差随路程变化"),
            ("heightComparison", "对地高随时间变化"),
            ("navStatusModes", "导航状态信息"),
            ("navVelocity", "导航速度信息"),
            ("navResetCounts", "导航 reset 计数"),
            ("vlocStatus", "VLOC 状态信息"),
            ("positionCompareComposite", "NED 随时间变化"),
            ("attitudeCompareComposite", "YPR 随时间变化"),
            ("positionErrorComposite", "NED 误差随时间变化"),
            ("attitudeErrorComposite", "YPR 误差随时间变化"),
        ]
    else:  # vo
        charts = [
            ("trajectory3d", "3D 轨迹"),
            ("trajectoryXY", "俯视 NE 轨迹"),
            ("errorDistance", "误差随路程变化"),
            ("heightComparison", "对地高随时间变化"),
            ("navStatusModes", "导航状态信息"),
            ("navVelocity", "导航速度信息"),
            ("navResetCounts", "导航 reset 计数"),
            ("vlocStatus", "VO 状态信息"),
            ("positionCompareComposite", "NED 随时间变化"),
            ("attitudeCompareComposite", "YPR 随时间变化"),
            ("positionErrorComposite", "NED 误差随时间变化"),
            ("attitudeErrorComposite", "YPR 误差随时间变化"),
            ("rpeTranslationTime", "RPE 平移误差"),
            ("rpeRotationTime", "RPE 旋转误差"),
            ("scaleFrameTime", "局部 Sim3 尺度"),
        ]

    checkboxes = []
    for chart_id, label in charts:
        checkboxes.append(
            f'<label><input type="checkbox" checked data-chart-id="{chart_id}"> {label}</label>'
        )

    checkbox_html = "".join(checkboxes)

    return f"""<div class="chart-directory-section">
  <h2>图表目录</h2>
  <div class="chart-directory-controls">
    <button id="selectAllCharts">全选</button>
    <button id="clearAllCharts">清除</button>
  </div>
  <div class="chart-directory-list">
    {checkbox_html}
  </div>
</div>"""


def _build_point_selection_panel() -> str:
    """生成点选输出面板的 HTML 容器。"""
    return """<section id="pointSelectionOutputSection">
  <h2>输出对比</h2>
  <p class="section-hint">选取图中点后，这里汇总点所在曲线、时间戳和值。</p>
  <div id="pointSelectionOutput"></div>
  <button id="clearAllPointSelections">清除所有点</button>
</section>"""


def _interaction_js() -> str:
    """返回实现图表联动和交互的 JavaScript 代码。"""
    return r"""
// ========== 工具函数 ==========
function getChartDivs() {
  return Array.from(document.querySelectorAll('.chart[data-chart-id]'))
    .map(el => document.getElementById(el.dataset.chartId))
    .filter(div => div && div.data);
}

// ========== 图表目录控制 ==========
document.querySelectorAll('[data-chart-id]').forEach(cb => {
  cb.addEventListener('change', () => {
    const el = document.querySelector('[data-chart-id="' + cb.dataset.chartId + '"]');
    const chart = el ? document.getElementById(el.id) : null;
    if (chart) chart.style.display = cb.checked ? '' : 'none';
  });
});

document.getElementById('selectAllCharts')?.addEventListener('click', () => {
  document.querySelectorAll('[data-chart-id]').forEach(cb => {
    cb.checked = true;
    const el = document.querySelector('[data-chart-id="' + cb.dataset.chartId + '"]');
    const chart = el ? document.getElementById(el.id) : null;
    if (chart) chart.style.display = '';
  });
});

document.getElementById('clearAllCharts')?.addEventListener('click', () => {
  document.querySelectorAll('[data-chart-id]').forEach(cb => {
    cb.checked = false;
    const el = document.querySelector('[data-chart-id="' + cb.dataset.chartId + '"]');
    const chart = el ? document.getElementById(el.id) : null;
    if (chart) chart.style.display = 'none';
  });
});

// ========== 跨子图选点标记 ==========
const selections = [];
const colorPalette = ['#f59e0b', '#8b5cf6', '#06b6d4', '#ef4444', '#10b981'];
let colorIndex = 0;
const SELECTION_TRACE_PREFIX = '__sel__';

function addSelectionMarkers(xValue, color) {
  getChartDivs().forEach(div => {
    if (!div.data || !div.data.length) return;

    // 找到离 xValue 最近的点
    let bestTraceIdx = 0, bestPointIdx = 0, bestDist = Infinity;
    let bestX = xValue, bestY = 0;

    for (let t = 0; t < div.data.length; t++) {
      const trace = div.data[t];
      if (trace.name && trace.name.startsWith(SELECTION_TRACE_PREFIX)) continue;
      if (!trace.x || !Array.isArray(trace.x)) continue;
      for (let i = 0; i < trace.x.length; i++) {
        const d = Math.abs(trace.x[i] - xValue);
        if (d < bestDist) {
          bestDist = d;
          bestTraceIdx = t;
          bestPointIdx = i;
          bestX = trace.x[i];
          bestY = trace.y ? trace.y[i] : (trace.z ? trace.z[i] : 0);
        }
      }
    }

    if (bestDist > 1e10) return; // 没找到

    // 添加或更新选点标记 trace
    const existingIdx = div.data.findIndex(t => t.name === SELECTION_TRACE_PREFIX + color);
    const markerTrace = {
      x: [bestX],
      y: [bestY],
      mode: 'markers',
      name: SELECTION_TRACE_PREFIX + color,
      marker: { size: 14, color: color, symbol: 'circle', line: { color: 'white', width: 2 } },
      showlegend: false,
      hoverinfo: 'skip'
    };

    if (existingIdx >= 0) {
      // 追加到已有标记
      const existing = div.data[existingIdx];
      existing.x = [...(existing.x || []), bestX];
      existing.y = [...(existing.y || []), bestY];
      Plotly.redraw(div);
    } else {
      Plotly.addTraces(div, markerTrace);
    }
  });
}

function clearSelectionMarkers() {
  getChartDivs().forEach(div => {
    if (!div.data) return;
    const removeIndices = [];
    for (let i = div.data.length - 1; i >= 0; i--) {
      if (div.data[i].name && div.data[i].name.startsWith(SELECTION_TRACE_PREFIX)) {
        removeIndices.push(i);
      }
    }
    if (removeIndices.length > 0) {
      Plotly.deleteTraces(div, removeIndices);
    }
  });
}

// ========== 点选面板 ==========
function updatePointSelectionPanel() {
  const panel = document.getElementById('pointSelectionOutput');
  if (!panel) return;

  if (selections.length === 0) {
    panel.innerHTML = '<p class="section-hint">未选中任何点</p>';
    return;
  }

  const items = selections.map((s) => {
    const ts = typeof s.timestamp === 'number' ? s.timestamp.toFixed(4) : (s.timestamp || 'N/A');
    const yVal = typeof s.y === 'number' ? s.y.toFixed(4) : s.y;
    return '<div class="point-selection-item" style="border-left: 3px solid ' + s.color + '">' +
      '<div>图表: ' + s.chartId + '</div>' +
      '<div>时间: ' + ts + '</div>' +
      '<div>值: y=' + yVal + '</div>' +
    '</div>';
  }).join('');

  panel.innerHTML = items;
}

// ========== 绑定事件（等待 Plotly 加载完成）==========
function bindChartEvents() {
  getChartDivs().forEach(div => {
    if (div._eventsBound) return;
    div._eventsBound = true;
    const chartId = div.dataset?.chartId || div.id;

    // --- 点击选点 ---
    div.on('plotly_click', function(eventData) {
      if (!eventData || !eventData.points || !eventData.points.length) return;
      const pt = eventData.points[0];
      const color = colorPalette[colorIndex % colorPalette.length];

      selections.push({
        chartId: chartId,
        x: pt.x,
        y: pt.y !== undefined ? pt.y : (pt.z || 0),
        timestamp: pt.x,
        color: color
      });

      // 在所有图表上添加标记
      addSelectionMarkers(pt.x, color);
      updatePointSelectionPanel();
    });
  });
}

// 清除选点
document.getElementById('clearAllPointSelections')?.addEventListener('click', () => {
  selections.length = 0;
  colorIndex = 0;
  clearSelectionMarkers();
  updatePointSelectionPanel();
});

// 延迟绑定事件（等待所有图表渲染完成）
if (document.readyState === 'complete') {
  setTimeout(bindChartEvents, 200);
} else {
  window.addEventListener('load', () => setTimeout(bindChartEvents, 200));
}
"""
