// figure_specs.js — 图表规格定义（ES module export）
// FR-004: 从 globalThis 挥手协议改为 ES module export

import { reportEntryMode } from "../js/entry-mode.js";

export function compositePairColors(index) {
  const palette = [
    ["#2563eb", "#16a34a"],
    ["#7c3aed", "#f97316"],
    ["#dc2626", "#0891b2"],
  ];
  return palette[index % palette.length];
}

function segmentEndpointTraces3d(rows, columns, prefix, style) {
  const endpoints = segmentEndpoints(rows, columns);
  return [
    endpointTrace3d(endpoints.starts, columns, `${prefix} start`, style.startColor, style.startSymbol, `${prefix} S`, "top center", style),
    endpointTrace3d(endpoints.ends, columns, `${prefix} end`, style.endColor, style.endSymbol, `${prefix} E`, "bottom center", style),
  ];
}

function segmentEndpoints(rows, columns) {
  const starts = [];
  const ends = [];
  if (!rows.length) {
    return { starts, ends };
  }

  let currentSegment = plotSegmentId(rows[0]);
  let currentRows = [];
  const flush = () => {
    const validRows = currentRows.filter((row) => columns.every((column) => Number.isFinite(Number(row[column]))));
    if (validRows.length) {
      starts.push(validRows[0]);
      ends.push(validRows[validRows.length - 1]);
    }
  };

  for (const row of rows) {
    const segmentId = plotSegmentId(row);
    if (segmentId !== currentSegment) {
      flush();
      currentSegment = segmentId;
      currentRows = [];
    }
    currentRows.push(row);
  }
  flush();
  return { starts, ends };
}

function plotSegmentId(row) {
  return row.visual_segment_id ?? row.segment_id ?? 0;
}

function rowSegmentId(row, segmentField = "segment_id") {
  return row[segmentField] ?? row.segment_id ?? 0;
}

function endpointTrace3d(rows, columns, name, color, symbol, labelPrefix, textPosition, style = {}) {
  const markerSize = style.markerSize ?? 9;
  const markerLineWidth = style.markerLineWidth ?? 2;
  const textfont = style.textSize ? { size: style.textSize } : undefined;
  return {
    x: rows.map((row) => row[columns[0]]),
    y: rows.map((row) => row[columns[1]]),
    z: rows.map((row) => row[columns[2]]),
    mode: "markers+text",
    type: "scatter3d",
    name,
    text: rows.map((_, index) => `${labelPrefix}${index + 1}`),
    textposition: textPosition,
    textfont,
    marker: { size: markerSize, color, symbol, line: { color: "#0f172a", width: markerLineWidth } },
  };
}

export function segmentedValues(rows, columns, segmentField = null) {
  if (!rows.length) {
    return columns.map(() => []);
  }
  if (!segmentField) {
    return columns.map((column) => rows.map((row) => row[column]));
  }
  const outputs = columns.map(() => []);
  let currentSegment = rowSegmentId(rows[0], segmentField);
  for (const row of rows) {
    const segmentId = rowSegmentId(row, segmentField);
    if (segmentId !== currentSegment) {
      outputs.forEach((items) => items.push(null));
      currentSegment = segmentId;
    }
    columns.forEach((column, index) => outputs[index].push(row[column]));
  }
  return outputs;
}

export function unwrapDegrees(values) {
  const out = [];
  let previousRaw = null;
  let offset = 0;
  for (const value of values) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      out.push(value);
      previousRaw = null;
      offset = 0;
      continue;
    }
    const raw = Number(value);
    if (previousRaw !== null) {
      const delta = raw - previousRaw;
      if (delta > 180) {
        offset -= 360;
      } else if (delta < -180) {
        offset += 360;
      }
    }
    out.push(raw + offset);
    previousRaw = raw;
  }
  return out;
}

function layout(title, extra = {}) {
  return {
    title,
    height: 380,
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { family: "Inter, system-ui, sans-serif", color: "#334155" },
    colorway: ["#2563eb", "#16a34a", "#f97316", "#9333ea", "#0f766e"],
    margin: { l: 56, r: 26, t: 78, b: 50 },
    legend: { orientation: "h", y: 1.18, x: 0, font: { size: 10 } },
    xaxis: { gridcolor: "#e8eef7", zerolinecolor: "#d9e1ec", title: "" },
    yaxis: { gridcolor: "#e8eef7", zerolinecolor: "#d9e1ec", title: "" },
    ...extra,
  };
}

export function buildVisualizationFigureSpecs(report, options = {}) {
  return reportEntryMode(report) === "vloc"
    ? buildVlocVisualizationFigureSpecs(report, options)
    : buildVoVisualizationFigureSpecs(report, options);
}

function isExportFigure(options = {}) {
  return options.variant === "export";
}

function figureHeight(options, liveHeight, exportHeight) {
  return isExportFigure(options) ? exportHeight : liveHeight;
}

function visualizationFigureSpec(id, label, data, chartLayout, specOptions = {}) {
  const pickable = specOptions.pickable ?? true;
  return {
    id,
    label,
    data,
    layout: chartLayout,
    pickable,
    livePickable: specOptions.livePickable ?? pickable,
    compositeRows: specOptions.compositeRows,
    compositeSpec: specOptions.compositeSpec,
  };
}

function buildVlocVisualizationFigureSpecs(report, options = {}) {
  const details = report.vloc_details || {};
  const rows = details.comparison || [];
  const navStatus = details.nav_status || [];
  const vlocStatus = details.vloc_status || [];
  const figures = [];
  const [navN3d, navE3d, navD3d] = segmentedValues(rows, ["nav_n_m", "nav_e_m", "nav_d_m"], "visual_segment_id");
  const [vlocN3d, vlocE3d, vlocD3d] = segmentedValues(rows, ["vloc_n_m", "vloc_e_m", "vloc_d_m"], "visual_segment_id");
  figures.push(visualizationFigureSpec("trajectory3d", "3D 轨迹", [
    { x: navN3d, y: navE3d, z: navD3d, mode: "lines", type: "scatter3d", name: "nav" },
    { x: vlocN3d, y: vlocE3d, z: vlocD3d, mode: "lines", type: "scatter3d", name: "vloc" },
    ...segmentEndpointTraces3d(rows, ["vloc_n_m", "vloc_e_m", "vloc_d_m"], "vloc", {
      startColor: "#9333ea",
      endColor: "#ef4444",
      startSymbol: "diamond",
      endSymbol: "x",
      markerSize: 5,
      markerLineWidth: 1,
      textSize: 10,
    }),
  ], layout("3D 轨迹", { height: figureHeight(options, 380, 640), scene: { xaxis: { title: "north m" }, yaxis: { title: "east m" }, zaxis: { title: "down m" } } }), { pickable: false }));

  const [navN, navE, navTime] = segmentedValues(rows, ["nav_n_m", "nav_e_m", "timestamp"]);
  const [vlocN, vlocE, vlocTime] = segmentedValues(rows, ["vloc_n_m", "vloc_e_m", "timestamp"]);
  figures.push(visualizationFigureSpec("trajectoryXY", "俯视 NE 轨迹", [
    { x: navN, y: navE, customdata: navTime, mode: "lines", type: "scatter", name: "nav" },
    { x: vlocN, y: vlocE, customdata: vlocTime, mode: "lines", type: "scatter", name: "vloc" },
  ], layout("俯视 NE 轨迹", { height: figureHeight(options, 380, 560), xaxis: { title: "north m" }, yaxis: { title: "east m", scaleanchor: "x" } })));

  figures.push(multiFieldTimeFigure("errorDistance", "误差随路程变化", rows, [
    { field: "position_error_3d_m", name: "3D position error" },
    { field: "horizontal_position_error_m", name: "horizontal error" },
    { field: "vertical_position_error_abs_m", name: "vertical abs error" },
  ], { ...options, xField: "distance_m", xTitle: "distance m", yTitle: "error m" }));
  figures.push(multiFieldTimeFigure("heightComparison", "对地高随时间变化", rows, [
    { field: "nav_height_m", name: "nav height" },
    { field: "vloc_height_m", name: "vloc height" },
  ], { ...options, yTitle: "height m" }));
  figures.push(multiFieldTimeFigure("navStatusModes", "导航状态信息", navStatus, [
    { field: "flight_mode", name: "flight_mode" },
    { field: "navi_mode", name: "navi_mode" },
    { field: "rtk_yaw", name: "rtk_yaw" },
    { field: "rtk_alti", name: "rtk_alti" },
  ], { ...options, yTitle: "state" }));
  figures.push(singleCompositeFigure("navVelocity", "导航速度信息", navStatus, {
    title: "导航速度信息",
    rows: [
      { label: "vx", field: "vx", unit: "m/s" },
      { label: "vy", field: "vy", unit: "m/s" },
      { label: "vz", field: "vz", unit: "m/s" },
      { label: "velocity_norm", field: "velocity_norm", unit: "m/s" },
    ],
  }, options));
  figures.push(multiFieldTimeFigure("navResetCounts", "导航 reset 计数", navStatus, [
    { field: "position_reset_count", name: "position_reset_count" },
    { field: "altitude_reset_count", name: "altitude_reset_count" },
    { field: "heading_reset_count", name: "heading_reset_count" },
  ], { ...options, yTitle: "count" }));
  figures.push(singleCompositeFigure("vlocStatus", "VLOC 状态信息", vlocStatus, {
    title: "VLOC 状态信息",
    rows: [
      { label: "vloc_mode", field: "vloc_mode", unit: "value" },
      { label: "num_inliers", field: "num_inliers", unit: "value" },
      { label: "reset_count", field: "reset_count", unit: "value" },
    ],
  }, options));
  figures.push(pairCompositeFigure("positionCompareComposite", "NED 随时间变化", rows, {
    title: "NED 随时间变化",
    leftName: "nav",
    rightName: "vloc",
    rows: [
      { label: "N", left: "nav_n_m", right: "vloc_n_m", unit: "m" },
      { label: "E", left: "nav_e_m", right: "vloc_e_m", unit: "m" },
      { label: "D", left: "nav_d_m", right: "vloc_d_m", unit: "m" },
    ],
  }, options));
  figures.push(pairCompositeFigure("attitudeCompareComposite", "YPR 随时间变化", rows, {
    title: "YPR 随时间变化",
    leftName: "nav",
    rightName: "vloc",
    rows: [
      { label: "Yaw", left: "nav_yaw_deg", right: "vloc_yaw_deg", unit: "deg", unwrap: true },
      { label: "Pitch", left: "nav_pitch_deg", right: "vloc_pitch_deg", unit: "deg", unwrap: true },
      { label: "Roll", left: "nav_roll_deg", right: "vloc_roll_deg", unit: "deg", unwrap: true },
    ],
  }, options));
  figures.push(singleCompositeFigure("positionErrorComposite", "NED 误差随时间变化", rows, {
    title: "NED 误差随时间变化",
    rows: [
      { label: "N 误差", field: "position_error_n_m", unit: "m" },
      { label: "E 误差", field: "position_error_e_m", unit: "m" },
      { label: "D 误差", field: "position_error_d_m", unit: "m" },
    ],
  }, options));
  figures.push(singleCompositeFigure("attitudeErrorComposite", "YPR 误差随时间变化", rows, {
    title: "YPR 误差随时间变化",
    rows: [
      { label: "Yaw 误差", field: "attitude_error_yaw_deg", unit: "deg", unwrap: true },
      { label: "Pitch 误差", field: "attitude_error_pitch_deg", unit: "deg", unwrap: true },
      { label: "Roll 误差", field: "attitude_error_roll_deg", unit: "deg", unwrap: true },
    ],
  }, options));
  return figures;
}

function buildVoVisualizationFigureSpecs(report, options = {}) {
  const details = report.vo_details || {};
  const comparison = details.comparison || [];
  const rows = comparison.length ? comparison : (report.per_pose || []);
  const isComparisonRows = comparison.length > 0;
  const navStatus = details.nav_status || [];
  const voStatus = details.vo_status || [];
  const rpeRows = report.trajectory_exports?.rpe_per_frame || [];
  const scaleRows = report.trajectory_exports?.scale_per_frame || [];
  const navPositionFields = isComparisonRows ? ["nav_x_m", "nav_y_m", "nav_z_m"] : ["gt_x_m", "gt_y_m", "gt_z_m"];
  const voPositionFields = isComparisonRows ? ["vo_x_aligned_m", "vo_y_aligned_m", "vo_z_aligned_m"] : ["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"];
  const positionErrorFields = isComparisonRows ? ["position_error_x_m", "position_error_y_m", "position_error_z_m"] : ["x_error_m", "y_error_m", "z_error_m"];
  const positionErrorNormField = isComparisonRows ? "position_error_3d_m" : "error_m";
  const horizontalErrorField = isComparisonRows ? "horizontal_position_error_m" : "horizontal_error_m";
  const figures = [];
  const [gtX3d, gtY3d, gtZ3d] = segmentedValues(rows, navPositionFields, "visual_segment_id");
  const [estX3d, estY3d, estZ3d] = segmentedValues(rows, voPositionFields, "visual_segment_id");
  figures.push(visualizationFigureSpec("trajectory3d", "3D 轨迹", [
    { x: gtX3d, y: gtY3d, z: gtZ3d, mode: "lines", type: "scatter3d", name: "Ground truth" },
    { x: estX3d, y: estY3d, z: estZ3d, mode: "lines", type: "scatter3d", name: "VO aligned" },
    ...segmentEndpointTraces3d(rows, voPositionFields, "vo", {
      startColor: "#9333ea",
      endColor: "#ef4444",
      startSymbol: "diamond",
      endSymbol: "x",
      markerSize: 5,
      markerLineWidth: 1,
      textSize: 10,
    }),
  ], layout("3D 轨迹", { height: figureHeight(options, 380, 640), scene: { xaxis: { title: "x m" }, yaxis: { title: "y m" }, zaxis: { title: "z m" } } }), { pickable: false }));
  const [dist3d, err3d, errT] = segmentedValues(rows, ["distance_m", positionErrorNormField, "timestamp"]);
  const [distH, errH, errHT] = segmentedValues(rows, ["distance_m", horizontalErrorField, "timestamp"]);
  figures.push(visualizationFigureSpec("errorDistance", "ATE 绝对位姿误差", [
    { x: dist3d, y: err3d, customdata: errT, mode: "lines", type: "scatter", name: "3D error" },
    { x: distH, y: errH, customdata: errHT, mode: "lines", type: "scatter", name: "horizontal" },
  ], layout("ATE 绝对位姿误差", { height: figureHeight(options, 380, 560), xaxis: { title: "distance m" }, yaxis: { title: "error m" } })));
  figures.push(multiFieldTimeFigure("navStatusModes", "导航状态信息", navStatus, [
    { field: "flight_mode", name: "flight_mode" },
    { field: "navi_mode", name: "navi_mode" },
    { field: "rtk_yaw", name: "rtk_yaw" },
    { field: "rtk_alti", name: "rtk_alti" },
  ], { ...options, yTitle: "state" }));
  figures.push(singleCompositeFigure("navVelocity", "导航速度信息", navStatus, {
    title: "导航速度信息",
    rows: [
      { label: "vx", field: "vx", unit: "m/s" },
      { label: "vy", field: "vy", unit: "m/s" },
      { label: "vz", field: "vz", unit: "m/s" },
      { label: "velocity_norm", field: "velocity_norm", unit: "m/s" },
    ],
  }, options));
  figures.push(multiFieldTimeFigure("navResetCounts", "导航 reset 计数", navStatus, [
    { field: "position_reset_count", name: "position_reset_count" },
    { field: "altitude_reset_count", name: "altitude_reset_count" },
    { field: "heading_reset_count", name: "heading_reset_count" },
  ], { ...options, yTitle: "count" }));
  figures.push(singleCompositeFigure("voStatus", "VO 状态信息", voStatus, {
    title: "VO 状态信息",
    rows: [
      { label: "num_inliers", field: "num_inliers", unit: "value" },
      { label: "is_keyframe", field: "is_keyframe", unit: "value" },
      { label: "time_cost", field: "time_cost", unit: "ms" },
      { label: "reset_count", field: "reset_count", unit: "value" },
    ],
  }, options));
  figures.push(pairCompositeFigure("positionCompareComposite", "位置随时间变化", rows, {
    title: "位置随时间变化",
    leftName: "Ground truth",
    rightName: "VO aligned",
    rows: [
      { label: "X", left: navPositionFields[0], right: voPositionFields[0], unit: "m" },
      { label: "Y", left: navPositionFields[1], right: voPositionFields[1], unit: "m" },
      { label: "Z", left: navPositionFields[2], right: voPositionFields[2], unit: "m" },
    ],
  }, options));
  figures.push(pairCompositeFigure("attitudeCompareComposite", "姿态随时间变化", rows, {
    title: "姿态随时间变化",
    leftName: "Ground truth",
    rightName: "VO aligned",
    rows: [
      { label: "Yaw", left: isComparisonRows ? "nav_yaw_deg" : "gt_yaw_deg", right: isComparisonRows ? "vo_yaw_aligned_deg" : "est_yaw_aligned_deg", unit: "deg", unwrap: true },
      { label: "Pitch", left: isComparisonRows ? "nav_pitch_deg" : "gt_pitch_deg", right: isComparisonRows ? "vo_pitch_aligned_deg" : "est_pitch_aligned_deg", unit: "deg", unwrap: true },
      { label: "Roll", left: isComparisonRows ? "nav_roll_deg" : "gt_roll_deg", right: isComparisonRows ? "vo_roll_aligned_deg" : "est_roll_aligned_deg", unit: "deg", unwrap: true },
    ],
  }, options));
  figures.push(singleCompositeFigure("positionErrorComposite", "位置误差随时间变化", rows, {
    title: "位置误差随时间变化",
    rows: [
      { label: "X 误差", field: positionErrorFields[0], unit: "m" },
      { label: "Y 误差", field: positionErrorFields[1], unit: "m" },
      { label: "Z 误差", field: positionErrorFields[2], unit: "m" },
    ],
  }, options));
  figures.push(singleCompositeFigure("attitudeErrorComposite", "姿态误差随时间变化", rows, {
    title: "姿态误差随时间变化",
    rows: [
      { label: "Yaw 误差", field: isComparisonRows ? "attitude_error_yaw_deg" : "yaw_error_signed_deg", unit: "deg", unwrap: true },
      { label: "Pitch 误差", field: isComparisonRows ? "attitude_error_pitch_deg" : "pitch_error_signed_deg", unit: "deg", unwrap: true },
      { label: "Roll 误差", field: isComparisonRows ? "attitude_error_roll_deg" : "roll_error_signed_deg", unit: "deg", unwrap: true },
    ],
  }, options));
  figures.push(rpeTimeFigure("rpeTranslationTime", "RPE 平移误差随时间变化", rpeRows, {
    field: "rpe_translation_m",
    unit: "m",
    name: "rpe_translation_m",
  }, options));
  figures.push(rpeTimeFigure("rpeRotationTime", "RPE 旋转误差随时间变化", rpeRows, {
    field: "rpe_rotation_deg",
    unit: "deg",
    name: "rpe_rotation_deg",
  }, options));
  figures.push(scaleTimeFigure("scaleFrameTime", "局部 Sim3 尺度随时间变化", scaleRows, options));
  return figures;
}

function multiFieldTimeFigure(id, title, rows, specs, options = {}) {
  const xField = options.xField || "timestamp";
  const traces = specs.map((spec) => {
    const [xValues, yValues, timestamps] = segmentedValues(rows, [xField, spec.field, "timestamp"]);
    const displayY = spec.unwrap ? unwrapDegrees(yValues) : yValues;
    return { x: xValues, y: displayY, customdata: timestamps, mode: "lines", type: "scatter", name: spec.name || spec.field };
  });
  return visualizationFigureSpec(id, title, traces, layout(title, {
    height: figureHeight(options, 380, 560),
    xaxis: { title: options.xTitle || "timestamp s" },
    yaxis: { title: options.yTitle || "" },
  }));
}

function rpeTimeFigure(id, title, rows, spec, options = {}) {
  const cleanRows = rows.filter((row) => row.rpe_available !== false && Number.isFinite(Number(row[spec.field])));
  const [timestamps, values] = segmentedValues(cleanRows, ["timestamp", spec.field]);
  return visualizationFigureSpec(id, title, [
    { x: timestamps, y: values, customdata: timestamps, mode: "lines+markers", type: "scatter", name: spec.name },
  ], layout(title, { height: figureHeight(options, 380, 560), xaxis: { title: "timestamp s" }, yaxis: { title: spec.unit } }));
}

function scaleTimeFigure(id, title, rows, options = {}) {
  const cleanRows = rows.filter((row) => row.scale_available !== false && Number.isFinite(Number(row.local_sim3_scale)));
  const [timestamps, values] = segmentedValues(cleanRows, ["timestamp", "local_sim3_scale"]);
  return visualizationFigureSpec(id, title, [
    { x: timestamps, y: values, customdata: timestamps, mode: "lines+markers", type: "scatter", name: "local_sim3_scale" },
  ], layout(title, { height: figureHeight(options, 380, 560), xaxis: { title: "timestamp s" }, yaxis: { title: "scale" } }));
}

function pairCompositeFigure(id, label, rows, spec, options = {}) {
  const traces = [];
  const axisLayout = {};
  const rowCount = spec.rows.length;
  spec.rows.forEach((row, index) => {
    const [leftColor, rightColor] = compositePairColors(index);
    const axisId = index === 0 ? "" : String(index + 1);
    const xaxisName = `xaxis${axisId}`;
    const yaxisName = `yaxis${axisId}`;
    const traceXAxis = `x${axisId}`;
    const traceYAxis = `y${axisId}`;
    const top = 1 - (index / rowCount);
    const bottom = 1 - ((index + 1) / rowCount);
    axisLayout[xaxisName] = {
      title: index === rowCount - 1 ? "timestamp s" : "",
      domain: [0, 1],
      anchor: traceYAxis,
      matches: index === 0 ? undefined : "x",
      showticklabels: index === rowCount - 1,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
      showspikes: false,
    };
    axisLayout[yaxisName] = {
      title: row.unit,
      domain: [bottom + 0.02, top - 0.02],
      anchor: traceXAxis,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
    };
    const [tLeft, leftValues] = segmentedValues(rows, ["timestamp", row.left]);
    const [tRight, rightValues] = segmentedValues(rows, ["timestamp", row.right]);
    traces.push(
      { x: tLeft, y: row.unwrap ? unwrapDegrees(leftValues) : leftValues, customdata: tLeft, mode: "lines", type: "scatter", name: `${row.label} ${spec.leftName}`, legendgroup: `${row.label}-${spec.leftName}`, showlegend: true, hoverinfo: "none", line: { color: leftColor }, xaxis: traceXAxis, yaxis: traceYAxis },
      { x: tRight, y: row.unwrap ? unwrapDegrees(rightValues) : rightValues, customdata: tRight, mode: "lines", type: "scatter", name: `${row.label} ${spec.rightName}`, legendgroup: `${row.label}-${spec.rightName}`, showlegend: true, hoverinfo: "none", line: { color: rightColor }, xaxis: traceXAxis, yaxis: traceYAxis },
    );
  });
  return visualizationFigureSpec(id, label, traces, layout(spec.title, {
    height: 980,
    hovermode: "x unified",
    hoversubplots: "axis",
    hoverdistance: 20,
    spikedistance: -1,
    annotations: spec.rows.map((row, index) => ({
      text: row.label,
      x: 0,
      xref: "paper",
      xanchor: "left",
      y: 1 - (index / rowCount) - 0.015,
      yref: "paper",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 14, color: "#0f172a" },
    })),
    ...axisLayout,
  }), {
    compositeRows: isExportFigure(options) ? undefined : rows,
    compositeSpec: isExportFigure(options) ? undefined : spec,
  });
}

function singleCompositeFigure(id, label, rows, spec, options = {}) {
  const traces = [];
  const axisLayout = {};
  const rowCount = spec.rows.length;
  spec.rows.forEach((row, index) => {
    const axisId = index === 0 ? "" : String(index + 1);
    const xaxisName = `xaxis${axisId}`;
    const yaxisName = `yaxis${axisId}`;
    const traceXAxis = `x${axisId}`;
    const traceYAxis = `y${axisId}`;
    const top = 1 - (index / rowCount);
    const bottom = 1 - ((index + 1) / rowCount);
    axisLayout[xaxisName] = {
      title: index === rowCount - 1 ? "timestamp s" : "",
      domain: [0, 1],
      anchor: traceYAxis,
      matches: index === 0 ? undefined : "x",
      showticklabels: index === rowCount - 1,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
      showspikes: false,
    };
    axisLayout[yaxisName] = {
      title: row.unit,
      domain: [bottom + 0.02, top - 0.02],
      anchor: traceXAxis,
      gridcolor: "#e8eef7",
      zerolinecolor: "#d9e1ec",
    };
    const [timestamps, values] = segmentedValues(rows, ["timestamp", row.field]);
    traces.push({
      x: timestamps,
      y: row.unwrap ? unwrapDegrees(values) : values,
      customdata: timestamps,
      mode: "lines",
      type: "scatter",
      name: row.label,
      legendgroup: row.label,
      showlegend: false,
      hoverinfo: "none",
      xaxis: traceXAxis,
      yaxis: traceYAxis,
    });
  });
  return visualizationFigureSpec(id, label, traces, layout(spec.title, {
    height: rowCount === 4 ? 1120 : 980,
    hovermode: "x unified",
    hoversubplots: "axis",
    hoverdistance: 20,
    spikedistance: -1,
    annotations: spec.rows.map((row, index) => ({
      text: row.label,
      x: 0,
      xref: "paper",
      xanchor: "left",
      y: 1 - (index / rowCount) - 0.015,
      yref: "paper",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 14, color: "#0f172a" },
    })),
    ...axisLayout,
  }), {
    compositeRows: isExportFigure(options) ? undefined : rows,
    compositeSpec: isExportFigure(options) ? undefined : spec,
  });
}


