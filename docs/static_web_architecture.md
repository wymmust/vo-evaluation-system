# 静态网页架构说明

## 整体架构

```text
┌─────────────────────────────────────────────────────────────────┐
│                        浏览器 (Browser)                          │
│                                                                  │
│  ┌──────────────┐   postMessage    ┌──────────────────────────┐  │
│  │   app.js     │ ◄──────────────► │       worker.js          │  │
│  │  (主线程)     │                  │    (Web Worker 线程)      │  │
│  │              │                  │                          │  │
│  │ • 用户交互    │                  │  ┌────────────────────┐  │  │
│  │ • DOM 操作   │                  │  │     Pyodide        │  │  │
│  │ • Plotly 渲染│                  │  │  (Python 运行时)    │  │  │
│  │ • 导出文件   │                  │  │                    │  │  │
│  │              │                  │  │  /vo_eval/         │  │  │
│  └──────┬───────┘                  │  │   ├ data_loader.py │  │  │
│         │                          │  │   ├ utils.py       │  │  │
│         │                          │  │   ├ report.py      │  │  │
│         │                          │  │   └ processing.py  │  │  │
│         │                          │  │                    │  │  │
│         │                          │  │  /browser_runner.py│  │  │
│         │                          │  └────────────────────┘  │  │
│         │                          └──────────────────────────┘  │
│         │                                                        │
│  ┌──────▼───────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │  index.html  │  │  figure_specs.js │  │  report_templates│   │
│  │  (页面结构)   │  │  (图表规格)       │  │  .js (报告模板)   │   │
│  └──────────────┘  └──────────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ fetch("../vo_eval/*.py")
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     HTTP 服务器 / 文件系统                        │
│                                                                  │
│   vo_eval/                    static_web/                        │
│   ├ data_loader.py            ├ index.html                       │
│   ├ utils.py                  ├ app.js                           │
│   ├ report.py                 ├ worker.js                        │
│   ├ processing.py             ├ style.css                        │
│   └ __init__.py               ├ py/browser_runner.py             │
│                               ├ visualization/                   │
│                               │  ├ figure_specs.js               │
│                               │  └ report_templates.js           │
│                               └ vendor/                          │
│                                  ├ pyodide/  (Python 运行时)      │
│                                  └ plotly/   (图表库)             │
└─────────────────────────────────────────────────────────────────┘
```

## 各文件职责

### HTML 层

| 文件 | 行数 | 职责 |
|------|------|------|
| `index.html` | 179 | 页面骨架：左侧控制面板（输入选择、参数设置、图表目录）+ 右侧内容区（指标卡片、图表网格、导出按钮）。加载 3 个 JS 文件 |

### JavaScript 层

| 文件 | 行数 | 职责 |
|------|------|------|
| `app.js` | 2641 | **核心控制器**：用户交互、文件读取、调用 worker 执行评估、接收结果、渲染指标卡片和图表、导出下载 |
| `worker.js` | 130 | **Pyodide 桥接**：在 Web Worker 中初始化 Python 运行时，fetch vo_eval 模块，暴露评估函数给主线程 |
| `figure_specs.js` | ~600 | **图表规格**：定义每种图表（3D 轨迹、误差曲线、状态信息等）的 Plotly 数据提取和布局规则 |
| `report_templates.js` | ~300 | **报告模板**：HTML 报告导出的模板生成 |

### Python 层

| 文件 | 职责 |
|------|------|
| `browser_runner.py` | **浏览器入口**：接收 JS 传入的文件文本，调用 vo_eval 解析和评估，返回 JSON 报告。支持 light/full 两种载荷模式 |
| `vo_eval/data_loader.py` | 数据加载：解析 imu.txt、vloc.txt、vo.txt、calib_raw.yaml、home_point.txt |
| `vo_eval/utils.py` | 数值工具：坐标转换、插值、对齐（Sim3）、旋转、统计 |
| `vo_eval/processing.py` | 评估流水线：编排 VLOC/VO 评估，生成 report dict |
| `vo_eval/report.py` | 报告导出：JSON、Excel、HTML 报告生成 |

### 静态资源

| 路径 | 内容 |
|------|------|
| `vendor/pyodide/v0.26.4/` | Pyodide Python 运行时（~20MB，含 numpy/pandas） |
| `vendor/plotly/plotly-2.35.2.min.js` | Plotly 图表库（~3.5MB） |

## 数据流

### 初始化阶段

```text
1. 浏览器加载 index.html
2. index.html 加载 Plotly CDN → vendor/plotly/
3. app.js 创建 Web Worker → worker.js
4. worker.js 加载 Pyodide → vendor/pyodide/
5. worker.js fetch("../vo_eval/*.py") → 获取 4 个 Python 模块源码
6. worker.js 将源码写入 Pyodide 虚拟文件系统 /vo_eval/
7. worker.js 导入 browser_runner.py，暴露 3 个函数给主线程
8. app.js 收到 init 完成信号，启用"运行评估"按钮
```

### 评估阶段

```text
用户操作                              app.js                           worker.js                       Python
────────                              ──────                           ─────────                       ──────
点击"选择目录" ──────────► 读取目录中必需文件 ─┐
                                               │
点击"运行评估" ──────────► buildBundlePayload() │
                                               │
                          postMessage("evaluate", payload)
                                               │───────────────────────► evaluateBundle()
                                               │                         │
                                               │                         ├─ entryMode == "vloc" ?
                                               │                         │   evaluate_vloc_bundle_json_light()
                                               │                         │     │
                                               │                         │     ├─ parse_imu_fixed()
                                               │                         │     ├─ parse_vloc_fixed()
                                               │                         │     ├─ parse_home_point_fixed()
                                               │                         │     ├─ parse_calib_raw_fixed()
                                               │                         │     └─ evaluate_vloc_bundle() → report
                                               │                         │
                                               │                         └─ entryMode == "vo" ?
                                               │                             evaluate_vo_bundle_json_light()
                                               │                               │
                                               │                               ├─ parse_imu_fixed()
                                               │                               ├─ parse_vo_fixed()
                                               │                               ├─ parse_calib_raw_fixed()
                                               │                               └─ evaluate_vo_bundle() → report
                                               │
                          postMessage({ok, result: JSON})
                          ◄────────────────────────
                          │
                          ├─ renderMetrics()       → 指标卡片
                          ├─ buildFigureSpecs()    → 图表规格
                          └─ Plotly.newPlot()      → 渲染图表
```

### 导出阶段

```text
用户点击"下载 Excel"
       │
       ▼
app.js: buildTrajectoryWorkbook()
       │
       ├─ 从 report 提取 trajectory_exports 中的 DataFrame
       ├─ 生成 XML (xlsx 格式)
       ├─ CRC32 + ZIP 打包
       └─ downloadBytes("trajectory.xlsx", bytes)

用户点击"下载 HTML 报告"
       │
       ▼
app.js: postMessage("slice", "full_report") → worker.js
       │                                        │
       │   ◄── get_report_slice_json("full_report")  ← Python
       │
       ▼
report_templates.js: 生成 HTML 报告字符串
       │
       └─ downloadText("report.html", html)
```

## 关键设计决策

### 1. Web Worker 隔离

Python 评估在 Web Worker 中运行，不阻塞主线程 UI。通过 `postMessage` 通信，使用请求 ID 匹配响应。

### 2. Light/Full 分层载荷

首次评估返回 **light report**（排除 `per_pose`、`segment_records`、`trajectory_exports` 等大数据），
用于渲染可见图表。导出时按需请求 **full report slices**，避免首次渲染时传输大量数据。

### 3. 两种输入模式

- **文件上传模式**：用户通过 `<input type="file" webkitdirectory>` 选择目录，JS 读取文件内容传给 Python
- **本地路径模式**：用户输入本地路径，JS 请求 `local_server.py` 读取文件（需要 HTTP 服务）

### 4. 图表目录可配置

每种评估模式（VLOC/VO）有独立的图表列表，用户可选择显示哪些图表。图表规格由 `figure_specs.js` 定义。

### 5. 跨图表点选联动

用户可以在任意图表上点击数据点，选中信息汇总到左侧"输出对比"面板，支持跨图表对比。

## 启动方式

| 方式 | 命令 | 适用场景 |
|------|------|---------|
| 静态预览 | `cd 项目根目录 && python3 -m http.server 8765` → 打开 `localhost:8765/static_web/` | 本地预览，仅文件上传 |
| 本地路径 | `python3 static_web/local_server.py --port 8766` → 打开 `127.0.0.1:8766` | 支持本地路径输入 |
| 公网部署 | 上传 `vo_eval/` + `static_web/` 到静态托管 | 远程访问 |
