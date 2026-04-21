# DataEase V2 全能技能

一站式 DataEase 自动化解决方案，融合图表部署与资源管理能力。

## 🎯 功能特性

| 功能 | 命令 | 说明 |
|------|------|------|
| 📊 数据探索 | `inspect_data.py` | 查询数据集、字段信息 |
| 📈 图表部署 | `deploy.py` | 创建图表并自动截图 |
| 📋 多图看板 | `multi_deploy.py` | 创建多图表仪表板 |
| 🏢 组织管理 | `capture_dashboard.py` | 查询/切换组织 |
| 📑 资源列表 | `capture_dashboard.py` | 列出仪表板/大屏 |
| 📸 截图导出 | `capture_dashboard.py` | 导出截图或PDF |

## 🚀 快速开始

### 1. 安装依赖

```bash
npm install
npx playwright install chromium
```

### 2. 配置环境

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
DATAEASE_BASE_URL=https://your-dataease.example.com
DATAEASE_API_PREFIX=/de2api
DATAEASE_ACCESS_KEY=your_access_key
DATAEASE_SECRET_KEY=your_secret_key
DATAEASE_USERNAME=admin
DATAEASE_PASSWORD=your_password
DATAEASE_LOGIN_ORIGIN=0
```

**认证方式（二选一）：**
- AK/SK：配置 `ACCESS_KEY` + `SECRET_KEY`
- 密码登录：配置 `USERNAME` + `PASSWORD`

### 3. 使用示例

```bash
# 查询数据集
python3 scripts/inspect_data.py --list-datasets

# 查询字段
python3 scripts/inspect_data.py --dataset "销售数据"

# 创建图表（自动截图）
python3 scripts/deploy.py bar '各产品销售额' '销售数据' '产品' '实际销售'

# 创建多图表看板
python3 scripts/multi_deploy.py '销售分析' '[{"type":"bar","title":"销售","dataset_name":"销售数据","x_axis":["产品"],"y_axis":["销售额"]}]'

# 查询组织
python3 scripts/capture_dashboard.py list-orgs

# 导出截图
python3 scripts/capture_dashboard.py capture --resource-id <ID> --busi-type dashboard --output-dir ./output

# 导出 PDF
python3 scripts/capture_dashboard.py capture --resource-id <ID> --busi-type dashboard --result-format 1 --output-dir ./output
```

## 📁 目录结构

```
dataease-v2-chart-skill/
├── SKILL.md              # 技能文档（Agent 读取）
├── README.md             # 本文档
├── .env.example          # 环境变量模板
├── package.json          # Node 依赖
├── scripts/
│   ├── inspect_data.py   # 数据探索
│   ├── deploy.py         # 图表部署
│   ├── multi_deploy.py   # 多图表部署
│   ├── engine.py         # 图表引擎
│   ├── client.py         # API 客户端
│   ├── capture_dashboard.py  # 截图/资源管理
│   └── browser_capture.mjs   # 浏览器截图
├── templates/            # 图表模板
├── references/           # API 参考
└── agents/               # Agent 配置
```

## 📊 支持的图表类型

- `bar` - 柱状图
- `line` - 折线图
- `pie` - 饼图
- `table_info` - 明细表

## 📸 截图参数

- `--pixel`: 分辨率，默认 `1920*1080`，可设 `2560*1440`
- `--ext-wait-time`: 额外等待秒数
- `--result-format`: `0`=JPEG, `1`=PDF

## 📝 许可证

MIT
