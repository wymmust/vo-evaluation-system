// labels.js — 中文 UI 文案集中管理
// FR-008: 所有硬编码中文文案的单一来源，其他模块通过 import LABELS 引用

export const LABELS = {
  // 评估状态
  runtime_ready: "运行环境已就绪",
  server_connected: "服务器已连接",
  server_disconnected: "未连接到评估服务器，请先运行 voeval server",
  server_checking: "检测服务器连接...",

  // 评估按钮
  button_run: "运行评估",
  button_busy: "计算中...",
  button_evaluation_failed_prefix: "评估失败：",

  // 评估错误消息
  error_local_file_protocol: "当前页面是直接打开的本地 index.html。请进入项目根目录后运行 voeval server；公网部署时也必须通过 http/https URL 访问。",
  error_local_fetch_failed: "无法读取静态资源",
  error_local_fetch_status: "无法读取静态资源",
  error_fetch_generic: "浏览器无法获取运行资源。请确认页面是通过 http/https 打开的、静态服务器没有停止。",
  error_local_path_evaluation_failed_prefix: "本地路径评估失败：",
  error_local_path_no_server: "当前页面不是通过 voeval server 启动，不能直接读取本地路径。请在仓库根目录运行 voeval server。",
  error_export_json_prefix: "导出 JSON 失败：",
  error_export_html_prefix: "导出 HTML 失败：",
  error_cannot_fetch_prefix: "无法读取本地资源",

  // 入口模式标题
  summary_title_vloc: "VLOC 运行结果",
  summary_title_vo: "VO 运行结果",
  summary_kicker_vloc: "VLOC Evaluation Summary",
  summary_kicker_vo: "VO Evaluation Summary",
  visual_title_vloc: "VLOC 可视化",
  visual_title_vo: "VO 可视化",
  visual_kicker_vloc: "Navigation & Estimation",
  visual_kicker_vo: "Trajectory & Drift",

  // 入口模式提示
  entry_hint_vloc: "当前模式会读取",
  entry_hint_vo: "当前模式会读取",

  // 评估切换
  mode_switched_prefix: "已切换到",
  mode_switched_suffix: "评估，请重新导入目录并运行评估。",

  // 选点交互
  point_selection_pick_title: "选取当前图的点",
  point_selection_pick_aria: "选取当前图的点",
  point_selection_clear_title: "清除当前图的点",
  point_selection_clear_aria: "清除当前图的点",
  point_selection_label_prefix: "选点",
  point_selection_hit_label_prefix: "选点命中",
  point_selection_table_header_trace: "线",
  point_selection_table_header_point: "点",
  point_selection_table_header_timestamp: "时间戳",
  point_selection_table_header_value: "值",
  point_selection_output_title: "输出对比",
  point_selection_output_hint: "选取图中点后，这里按图表汇总点所在曲线、点标记、时间戳和值。",
  point_selection_clear_all: "清除所有点",

  // 消息
  discontinuity_detected_prefix: "检测到",
  discontinuity_detected_break_suffix: "个大跳变/时间间隔",
  discontinuity_vo_timestamps_suffix: "；当前仍按全部 VO 时间戳统一评估，不会因此丢弃匹配点。",
  discontinuity_policy_suffix: "；当前策略",
  interpolation_dropped_prefix: "当前将 GT 插值到 VO 时间戳；因超出 GT 时间范围或插值间隔过大丢弃了部分 VO 点",

  // HTML 导出报告
  html_report_title_vloc: "VLOC 评估结果",
  html_report_title_vo: "VO 评估结果",
  html_report_summary_title_vloc: "VLOC 运行结果",
  html_report_summary_title_vo: "VO 运行结果",
  html_report_kicker_vloc: "VLOC Offline Visualization",
  html_report_kicker_vo: "VO Offline Visualization",
  html_report_offline_hint: "离线可视化快照。保留页面上的指标卡、图表目录、图表交互和选点记录；不包含上传与重新评估功能。",
  html_report_chart_directory_title: "图表目录",
  html_report_chart_directory_hint: "选择右侧展示的图表；导出的报告默认全开。",
  html_report_point_output_title: "输出对比",
  html_report_point_output_hint: "选取图中点后，这里按图表汇总点所在曲线、点标记、时间戳和值。",
  html_report_select_all: "全选",
  html_report_clear_charts: "清除",
  html_report_select_point: "选点",
  html_report_clear_point: "清除",
  html_report_no_charts: "当前报告没有可导出的图表数据。",
  html_report_selectable_label: "Selectable chart",
  html_report_chart_label: "Chart",
  html_report_composite_timestamp_prefix: "当前时间戳",
  html_report_composite_range_prefix: "选区",
  html_report_no_data: "没有可用数据",

  // Composite overlay
  composite_timestamp_prefix: "当前时间戳",
  composite_no_data: "没有可用数据",
};
