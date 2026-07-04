# static_web 模块

VO/VLOC 评估系统的浏览器端可视化界面。

## 快速上手

**必须先启动本地服务器才能使用评估功能。**

```bash
# 从仓库根目录启动本地服务器
cd vo-evaluation-system
python static_web/py/local_server.py --host 127.0.0.1 --port 8765
# 打开 http://127.0.0.1:8765/
```

页面加载时会检测服务器可达性（`/api/health`），成功后状态栏显示"服务器已连接"。

### CLI 报告生成

```bash
node static_web/cli/export_report_cli.js output.html < report.json
```

## 目录结构

| 子目录 | 职责 | 关键文件 |
|--------|------|----------|
| `css/` | 样式文件，按用途分离 | `style.css`（运行时 UI）、`report-export.css`（导出报告） |
| `js/` | 浏览器端 ES module 模块，按职责拆分 | `main.js`（入口）、`evaluation.js`、`entry-mode.js` 等 |
| `visualization/` | 图表规格和报告模板 | `figure_specs.js`、`report_templates.js` |
| `py/` | Python 本地服务器 | `local_server.py`（HTTP API + 静态文件服务） |
| `cli/` | Node.js CLI 工具 | `export_report_cli.js` |
| `vendor/` | 第三方库 | `plotly/` |

## 评估模式

| 模式 | 入口 | API 端点 |
|------|------|----------|
| 本地路径 | 填写 data_dir/log_dir 路径 | POST `/api/evaluate-paths` |
| 文件上传 | 选择 imu/vo/calib 文件 | POST `/api/evaluate-bundle` |

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
