# static_web 模块

VO/VLOC 评估系统的浏览器端可视化界面。

## 快速上手

### 浏览器 Pyodide 评估

```bash
# 从仓库根目录启动静态服务器
cd vo-evaluation-system
python3 -m http.server 8765
# 打开 http://localhost:8765/static_web/
```

**注意**: 必须通过 HTTP 访问，不能直接打开本地 `index.html`。

### 本地 HTTP API 评估

```bash
python static_web/py/local_server.py --host 127.0.0.1 --port 8766
# 打开 http://127.0.0.1:8766/
```

### CLI 报告生成

```bash
node static_web/cli/export_report_cli.js output.html < report.json
```

## 目录结构

| 子目录 | 职责 | 关键文件 |
|--------|------|----------|
| `css/` | 样式文件，按用途分离 | `style.css`（运行时 UI）、`report-export.css`（导出报告） |
| `js/` | 浏览器端 ES module 模块，按职责拆分 | `main.js`（入口）、`worker-client.js`、`evaluation.js` 等 |
| `worker/` | Pyodide Web Worker | `worker.js` |
| `visualization/` | 图表规格和报告模板 | `figure_specs.js`、`report_templates.js` |
| `py/` | Python 文件 | `browser_runner.py`、`local_server.py`、`vo_eval`（符号链接） |
| `cli/` | Node.js CLI 工具 | `export_report_cli.js` |
| `vendor/` | 第三方库（不变） | `plotly/`、`pyodide/` |

## 架构详情

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 模块依赖方向

所有 JS 模块通过 ES module `import/export` 组织依赖，方向为：

```
main.js → 功能模块 → 基础模块 → visualization
         ↓              ↓
    state/constants  dom-refs/utils/labels
```

无 globalThis 耦合，无跨模块隐式依赖。
