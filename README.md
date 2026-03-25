# DataEase Skills

这个仓库提供一个可直接落地的 DataEase skill，实现以下能力：

- 查询组织列表
- 切换组织
- 查询指定组织下的仪表板或大屏列表
- 导出指定仪表板或大屏的截图或 PDF

核心实现位于 `scripts/capture_dashboard.py`，skill 行为定义位于 `SKILL.md`。

## 目录结构

```text
.
├── .env.example
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── api.md
│   └── resource_aliases.json
└── scripts/
    └── capture_dashboard.py
```

## 环境准备

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 填写真实配置：

```env
DATAEASE_BASE_URL=https://your-dataease.example.com
DATAEASE_ACCESS_KEY=
DATAEASE_SECRET_KEY=
```

配置优先级：

- 命令行参数
- 已导出的系统环境变量
- 仓库根目录 `.env`
- 脚本默认值

## CLI 用法

### 1. 查询组织列表

```bash
python3 scripts/capture_dashboard.py list-orgs
python3 scripts/capture_dashboard.py list-orgs --org-keyword 华东
```

### 2. 切换组织

```bash
python3 scripts/capture_dashboard.py switch-org --org-id 1225813472202330112
```

返回结果中会带上 `x_de_token`，后续可用于指定组织上下文。

### 3. 查询指定组织下的仪表板或大屏列表

已知组织 ID 时，可以直接传 `--org-id`，脚本会先切组织，再查资源：

```bash
python3 scripts/capture_dashboard.py list-resources --org-id 1225813472202330112 --busi-type dashboard
python3 scripts/capture_dashboard.py list-resources --org-id 1225813472202330112 --busi-type dataV
```

按名称过滤候选资源：

```bash
python3 scripts/capture_dashboard.py list-resources --org-id 1225813472202330112 --busi-type dashboard --resource-name 销售总览
```

如果你已经手动执行过 `switch-org`，也可以复用返回的 token：

```bash
python3 scripts/capture_dashboard.py list-resources --x-de-token <token> --busi-type dashboard
```

### 4. 导出截图或 PDF

导出 JPEG：

```bash
python3 scripts/capture_dashboard.py capture --org-id 1225813472202330112 --resource-name 销售总览 --busi-type dashboard
```

导出 PDF：

```bash
python3 scripts/capture_dashboard.py capture --org-id 1225813472202330112 --resource-name 门店运营监控 --busi-type dataV --result-format 1
```

自定义分辨率和额外等待时间：

```bash
python3 scripts/capture_dashboard.py capture --org-id 1225813472202330112 --resource-name 华东经营分析 --pixel 1920*1080 --ext-wait-time 5
```

也可以直接按资源 ID 导出：

```bash
python3 scripts/capture_dashboard.py capture --org-id 1225813472202330112 --resource-id 1234567890 --busi-type dashboard
```

导出文件默认保存到 `outputs/` 目录。

## Skill 用法

如果你的运行环境支持 skill manifest，可通过 `agents/openai.yaml` 暴露 skill。推荐的自然语言请求示例：

- 查询可用组织列表
- 切换到华东组织后，列出仪表板
- 查看“销售总览”看板
- 导出“门店运营监控”大屏为 pdf

skill 入口提示词定义在 `agents/openai.yaml`，详细行为规则定义在 `SKILL.md`。

## 说明

- 默认业务类型为 `dashboard`
- 默认分辨率为 `1920*1080`
- 默认 `extWaitTime=0`
- 默认 `resultFormat=0`，即 JPEG
- `resultFormat=1` 表示 PDF

## 验证

可以先做基础检查：

```bash
python3 -m py_compile scripts/capture_dashboard.py
python3 scripts/capture_dashboard.py --help
```
