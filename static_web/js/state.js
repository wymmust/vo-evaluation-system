// state.js — 全局状态对象
// 所有模块共享的状态中心，Worker 通信、评估报告、选点交互状态等

export const state = {
  serverReady: false,
  report: null,
  loadingStep: "",
  reportSource: "local_server",
  chartRenderToken: 0,
  activePointSelectionChartId: null,
  focusedPointSelectionId: null,
  pointSelectionSequence: 0,
  pointSelections: [],
  vlocSelectedChartIds: null,
  voSelectedChartIds: null,
};
