// constants.js — 图表ID、图表选项、颜色常量、URL配置
// 所有图表配置和静态常量的单一来源

export const PYODIDE_VENDOR_PATH = "./vendor/pyodide/v0.26.4/full/";
export const PLOTLY_SCRIPT_URL = "./vendor/plotly/plotly-2.35.2.min.js";
export const APP_ASSET_VERSION = "20260704-dir-restructure";

export const chartIds = [
  "trajectory3d",
  "trajectoryXY",
  "errorDistance",
  "heightComparison",
  "navStatusModes",
  "navVelocity",
  "navResetCounts",
  "vlocStatus",
  "voStatus",
  "positionCompareComposite",
  "attitudeCompareComposite",
  "positionErrorComposite",
  "attitudeErrorComposite",
  "rpeTranslationTime",
  "rpeRotationTime",
  "scaleFrameTime",
];

export const VLOC_CHART_OPTIONS = [
  { id: "trajectory3d", label: "3D 轨迹" },
  { id: "trajectoryXY", label: "俯视 NE 轨迹" },
  { id: "errorDistance", label: "误差随路程变化" },
  { id: "heightComparison", label: "对地高随时间变化" },
  { id: "navStatusModes", label: "导航状态信息" },
  { id: "navVelocity", label: "导航速度信息" },
  { id: "navResetCounts", label: "导航 reset 计数" },
  { id: "vlocStatus", label: "VLOC 状态信息" },
  { id: "positionCompareComposite", label: "NED 随时间变化" },
  { id: "attitudeCompareComposite", label: "YPR 随时间变化" },
  { id: "positionErrorComposite", label: "NED 误差随时间变化" },
  { id: "attitudeErrorComposite", label: "YPR 误差随时间变化" },
];

export const VO_CHART_OPTIONS = [
  { id: "trajectory3d", label: "3D 轨迹" },
  { id: "errorDistance", label: "ATE 绝对位姿误差" },
  { id: "navStatusModes", label: "导航状态信息" },
  { id: "navVelocity", label: "导航速度信息" },
  { id: "navResetCounts", label: "导航 reset 计数" },
  { id: "voStatus", label: "VO 状态信息" },
  { id: "positionCompareComposite", label: "位置随时间变化" },
  { id: "attitudeCompareComposite", label: "姿态随时间变化" },
  { id: "positionErrorComposite", label: "位置误差随时间变化" },
  { id: "attitudeErrorComposite", label: "姿态误差随时间变化" },
  { id: "rpeTranslationTime", label: "RPE 平移误差" },
  { id: "rpeRotationTime", label: "RPE 旋转误差" },
  { id: "scaleFrameTime", label: "局部 Sim3 尺度" },
];

export const VLOC_VISIBLE_CHART_IDS = VLOC_CHART_OPTIONS.map((option) => option.id);
export const VO_VISIBLE_CHART_IDS = VO_CHART_OPTIONS.map((option) => option.id);
export const PICKABLE_VLOC_CHART_IDS = VLOC_VISIBLE_CHART_IDS.filter((id) => id !== "trajectory3d");
export const PICKABLE_VO_CHART_IDS = VO_VISIBLE_CHART_IDS.filter((id) => id !== "trajectory3d");

export const POINT_SELECTION_COLORS = [
  "#000000",
  "#ff00ff",
  "#ffd700",
  "#00ffff",
  "#ff1493",
  "#7fff00",
  "#8b4513",
  "#ff69b4",
  "#4b0082",
  "#00ff7f",
];
