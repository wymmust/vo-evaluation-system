# 本地网页架构说明

## 整体架构

当前网页不是纯静态离线评估。浏览器负责交互、目录读取、图表渲染和导出交互；Python 评估逻辑运行在本机 `voeval server` HTTP 服务中。

```text
┌────────────────────────────────────────────────────────────────────┐
│ Browser                                                            │
│                                                                    │
│ voeval/visualization/index.html                                    │
│   ├─ js/main.js                         页面入口和事件装配          │
│   ├─ js/evaluation.js                   调用评估 API                │
│   ├─ js/file-bundle.js                  目录选择和固定文件读取      │
│   ├─ js/report-render.js                指标、图表、明细渲染        │
│   ├─ js/chart-render.js                 Plotly 图表渲染             │
│   ├─ js/point-selection.js              选点对比                    │
│   ├─ js/excel-export.js                 浏览器端 Excel 导出         │
│   └─ js/html-export.js                  浏览器端 HTML 快照组装      │
│                                                                    │
│                 fetch /api/evaluate-* /api/report-slice             │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────┐
│ voeval/server.py                                                    │
│                                                                    │
│ 1. 托管 voeval/visualization/                                      │
│ 2. 读取本地 data_dir/log_dir 或接收浏览器上传的文件文本             │
│ 3. 调用 voeval.io 解析固定格式                                      │
│ 4. 调用 voeval.core 执行评估                                        │
│ 5. 调用 voeval.reports 输出 JSON-safe report                        │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                    ▼
        voeval/io/            voeval/core/          voeval/reports/
        固定格式读取          评估计算核心          明细、导出、预览
```

## 文件职责

### Python 服务与评估层

| 文件 / 目录 | 职责 |
| --- | --- |
| `voeval/__main__.py` | 统一分发 `python -m voeval eval` 和 `python -m voeval server` |
| `voeval/cli.py` | CLI 评估入口：解析参数、加载 bundle、运行评估、保存 JSON/HTML |
| `voeval/server.py` | 本地 HTTP 服务：托管网页并提供评估 API |
| `voeval/io/` | 输入层：固定列定义、轨迹结构、SF bundle、标定和解析函数 |
| `voeval/core/` | 计算层：时间同步、插值、Sim3/Umeyama、误差、统计、分段和评估 pipeline |
| `voeval/reports/` | 报告层：VLOC/VO 明细、导出表、JSON/Excel/HTML、路径和预览工具 |

### 前端可视化层

| 文件 / 目录 | 职责 |
| --- | --- |
| `voeval/visualization/index.html` | 页面骨架：模式、目录输入、参数、指标、图表、导出按钮 |
| `voeval/visualization/js/main.js` | 前端入口，装配初始化和事件绑定 |
| `voeval/visualization/js/evaluation.js` | 构造配置并调用 `/api/evaluate-bundle` 或 `/api/evaluate-paths` |
| `voeval/visualization/js/file-bundle.js` | 从浏览器目录选择中读取 `imu.txt`、`vo.txt`、`vloc.txt`、`calib_raw.yaml`、`home_point.txt` |
| `voeval/visualization/js/report-render.js` | 渲染指标卡、图表目录、下载状态和消息 |
| `voeval/visualization/js/chart-render.js` | 按图表规格调用 Plotly |
| `voeval/visualization/js/point-selection.js` | 图表选点、清除和输出对比 |
| `voeval/visualization/js/excel-export.js` | 在浏览器端生成 Excel 工作簿 |
| `voeval/visualization/js/html-export.js` | 生成可下载的独立 HTML 报告 |
| `voeval/visualization/visualization/figure_specs.js` | VLOC/VO 图表规格 |
| `voeval/visualization/visualization/report_templates.js` | 离线 HTML 报告模板 |
| `voeval/visualization/vendor/plotly/` | 固定版本 Plotly |

## API

| Endpoint | 方法 | 用途 |
| --- | --- | --- |
| `/api/health` | GET | 前端启动时检查本机评估服务是否可用 |
| `/api/evaluate-bundle` | POST | 浏览器目录选择模式：提交文件文本给 Python 解析和评估 |
| `/api/evaluate-paths` | POST | 本地路径模式：提交 `data_dir` / `log_dir` 字符串，由 Python 读取磁盘文件 |
| `/api/report-slice?slice=...` | GET | 评估后按需获取完整 report、逐帧数据或导出表 |

## 运行流程

### 初始化

```text
1. 用户运行 python -m voeval server
2. voeval/server.py 托管 voeval/visualization/
3. 默认浏览器自动打开 http://127.0.0.1:8766/
4. js/main.js 初始化页面、图表目录、输入控件和导出按钮
5. 前端请求 /api/health，确认本机评估服务可用
```

### 目录选择评估

```text
用户选择 data_dir/log_dir
  │
  ▼
file-bundle.js 读取必需文件文本
  │
  ▼
evaluation.js POST /api/evaluate-bundle
  │
  ▼
voeval/server.py
  ├─ voeval.io.load_*_evaluation_bundle_from_text()
  ├─ voeval.core.evaluate_*_bundle()
  └─ voeval.reports.export.report_to_json()
  │
  ▼
report-render.js + chart-render.js 渲染指标和图表
```

### 本地路径评估

```text
用户填写 data_dir/log_dir 绝对路径
  │
  ▼
evaluation.js POST /api/evaluate-paths
  │
  ▼
voeval/server.py 读取本机目录
  ├─ data_dir/imu.txt
  ├─ VO: log_dir/vo.txt + log_dir/calib_raw.yaml
  └─ VLOC: log_dir/vloc.txt + log_dir/home_point.txt + log_dir/calib_raw.yaml
  │
  ▼
io -> core -> reports
```

### 导出

```text
JSON 指标       浏览器直接下载当前 light report 或完整 report
Excel           excel-export.js 从 trajectory_exports 生成工作簿
HTML 报告       html-export.js + report_templates.js 生成独立页面
完整数据切片    evaluation.js 按需请求 /api/report-slice
```

## 启动方式

```bash
python -m voeval server
```

运行后会自动打开默认浏览器。默认地址是 `http://127.0.0.1:8766/`；如果端口被占用，可以加 `--port 8767`。

不要直接双击 `index.html`，也不要只用普通静态文件服务器启动页面；这些方式没有评估 API，无法完成 VO/VLOC 计算。
