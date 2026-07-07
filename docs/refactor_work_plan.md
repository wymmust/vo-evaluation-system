# 目录结构重构工作计划

## 目标

将当前平铺结构重构为按评估流程分层的三层架构，CLI 和 Web 作为并列入口统一在 `python -m voeval {eval|server}` 下。

## 最终目录结构

```
vo-evaluation-system/                  # git 仓库根目录
├── voeval/                            # Python 包
│   ├── __init__.py                    # 公开 API 导出
│   ├── __main__.py                    # 统一入口：python -m voeval {eval|server}
│   ├── cli.py                         # eval 子命令实现
│   ├── server.py                      # server 子命令实现
│   │
│   ├── io/                            # ── 数据输入层 ──
│   │   ├── __init__.py
│   │   ├── formats.py                 # EvaluationFormatSpec, 列定义
│   │   ├── trajectory.py              # Trajectory + 解析
│   │   ├── bundle.py                  # SfVoBundle/SfVlocBundle + 目录加载
│   │   ├── calibration.py             # Calibration 解析
│   │   ├── parsers.py                 # parse_imu/vloc/vo_fixed 等
│   │
│   ├── core/                          # ── 评估计算核心 ──
│   │   ├── __init__.py
│   │   ├── pipeline.py                # evaluate_trajectories / evaluate_vo/vloc_bundle
│   │   ├── config.py                  # EvaluationConfig
│   │   ├── alignment.py               # Sim3/Umeyama 对齐
│   │   ├── errors.py                  # ATE/RPE 误差计算
│   │   ├── interpolation.py           # 时间同步 + 轨迹插值
│   │   ├── geometry.py                # NED/旋转/四元数/欧拉角
│   │   ├── statistics.py              # describe + RPE/scale dataframe
│   │   ├── segments.py                # 断点检测 + 连续段分割
│   │
│   ├── reports/                       # ── 报告可视化与下载层 ──
│   │   ├── __init__.py
│   │   ├── summary.py                 # 指标文本格式化
│   │   ├── detail.py                  # VLOC/VO detail report 构造
│   │   ├── comparison.py              # 逐帧对比表
│   │   ├── export.py                  # JSON/Excel/TUM 导出
│   │   ├── paths.py                   # 文件名工具 + 输出路径构造
│   │   ├── preview.py                 # Node.js HTML 导出 + 浏览器预览
│   │   ├── html.py                    # 纯 Python HTML 报告（备用）
│   │   ├── charts.py                  # Plotly Python 图表定义（备用）
│   │
│   ├── visualization/                 # ── 共享可视化资源 ──（无 __init__.py）
│       ├── index.html
│       ├── js/                        # JS 模块
│       │   ├── main.js                # 浏览器入口
│       │   ├── html-export.js         # HTML 报告组装（CLI 和浏览器共用）
│       │   ├── evaluation.js, state.js, constants.js, ...
│       ├── visualization/             # 图表规格和模板
│       │   ├── figure_specs.js
│       │   ├── report_templates.js
│       ├── css/
│       │   ├── style.css
│       │   ├── report-export.css
│       ├── cli/
│       │   ├── export_report_cli.js   # Node.js 离线导出
│       ├── vendor/
│       │   ├── plotly/
│       ├── package.json
│
├── tests/
├── docs/
├── README.md
├── CODEBUDDY.md
├── requirements.txt
```

## 调用方式

```bash
python -m voeval eval --mode sf_vo --data_dir ... --log_dir ...   # CLI 评估
python -m voeval server                                              # Web 服务，自动打开浏览器
```

## 分阶段计划

每阶段完成后独立提交，`pytest` 全绿再进入下一阶段。

---

### 阶段一：创建 voeval 包骨架 + 公开 API 重导出

- 创建 `voeval/` 目录，含 `__init__.py`、`__main__.py`（暂空壳）
- 创建 `voeval/io/`、`voeval/core/`、`voeval/reports/` 三个子包及各自的 `__init__.py`
- 所有 `__init__.py` 从新分层模块导出公开 API，入口统一到 `voeval`
- 验证：`pytest` 全绿，`python -m voeval eval/server --help` 可用

---

### 阶段二：拆分 utils.py + processing.py → core/ ⚠️高风险

- `utils.py`(61KB, 46函数) 拆为 7 个主题子模块：
  - `alignment.py`：Sim3/Umeyama 对齐系列函数
  - `errors.py`：ATE/RPE 误差计算函数
  - `interpolation.py`：时间同步 + 轨迹插值系列函数
  - `geometry.py`：NED/geodetic/旋转/四元数系列函数
  - `statistics.py`：describe + RPE/scale dataframe
  - `segments.py`：断点检测 + 连续段分割
  - `config.py`：EvaluationConfig + normalized 函数
- `processing.py` 核心编排迁入 `core/pipeline.py`
- `core/__init__.py` 从各子模块重导出
- 更新所有 import 引用（data_loader/report/server 等）
- 删除原 `utils.py` 和 `processing.py`
- 验证：`pytest` 全绿

---

### 阶段三：拆分 data_loader.py → io/

- 拆为 5 个子模块：`formats.py`/`trajectory.py`/`bundle.py`/`calibration.py`/`parsers.py`
- `io/__init__.py` 重导出
- 更新所有 import 引用
- 删除原 `data_loader.py`
- 验证：`pytest` 全绿

---

### 阶段四：拆分 report.py + 迁入 html_report/chart_specs + 提取 __main__ 辅助函数 → reports/

- `report.py`(25KB) 拆为：`detail.py`/`comparison.py`/`export.py`
- `html_report.py` → `reports/html.py`，`chart_specs.py` → `reports/charts.py`
- 从 `__main__.py` 提取：`paths.py`（文件名+路径工具）+ `preview.py`（Node.js导出+浏览器预览）+ `summary.py`（指标文本格式化）
- `reports/__init__.py` 重导出
- 更新所有 import 引用
- 删除原 `report.py`、`html_report.py`、`chart_specs.py`
- 验证：`pytest` 全绿

---

### 阶段五：瘦身 CLI + 创建统一入口

- `voeval/__main__.py`：子命令分发器（eval/server）
- `voeval/cli.py`：eval 子命令实现（参数解析 → 调用 io 加载 → 调用 core 计算 → 调用 reports 输出）
- 删除旧 CLI 入口文件
- 验证：`python -m voeval eval --mode sf_vo ... -p` 正常工作

---

### 阶段六：迁移可视化资源 + 创建 server.py ⚠️中风险

- 旧可视化资源目录下的 js/css/vendor/cli/visualization/index.html/package.json → `voeval/visualization/`
- 旧本地服务入口的业务逻辑迁入 `voeval/server.py`
- 更新路径引用：
  - `server.py`：`STATIC_ROOT` 指向 `voeval/visualization/`
  - `reports/preview.py`：`export_report_cli.js` 路径指向 `voeval/visualization/cli/`
  - `export_report_cli.js`：`staticWebDir` 计算 + JS 模块 import 路径
  - `index.html`：`<script>` 引用路径
- 删除旧可视化资源目录
- 验证：`pytest` 全绿 + `python -m voeval server` 启动正常 + 浏览器访问正常 + HTML 导出正常

---

### 阶段七：包名替换 + 收尾

- 全局替换旧包名 → `voeval`（import 语句、文档、测试）
- 更新 `voeval/__init__.py` 公开 API 导出（从 io/core/reports 子模块重导出）
- 更新 `tests/` 所有 import 路径
- 更新 `CODEBUDDY.md`：架构描述、命令示例
- 更新 `README.md`：指标与代码总表
- 更新 `docs/` 所有文档路径引用
- 扫描旧包名和旧资源目录路径关键词，确保零残留
- 删除旧包目录
- 验证：`pytest` 全绿 + `python -m voeval eval/server` 完整回归测试
