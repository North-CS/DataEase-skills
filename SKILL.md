---
name: dataease
description: DataEase V2 智能平台技能，通过安全分级 CLI 探索数据并管理 DataEase。Use when Codex, OpenClaw or another Agent Skills-compatible tool needs to inspect or manage data sources, datasets, dashboards, DataV screens, data filling, organizations, users, roles, system settings, email, SSO, DingTalk, WeCom, Lark, scheduled reports or Webhooks; build and capture polished analytics; or diagnose connectivity, authentication, permissions and version compatibility on Windows, Linux or macOS.
---

# DataEase V2 智能平台技能

一站式完成 DataEase 数据探索、可视化构建、平台管理、认证集成与自动化，并把高风险操作约束在可审计的 dry-run、确认令牌和回读验证流程中。

## 核心能力

| 功能模块 | 命令族 | 风险范围 |
|---|---|---|
| 连接诊断与平台盘点 | `system`、`inventory` | L0 |
| 数据源、数据集与智能分析规划 | `datasource`、`dataset` | L0-L3 |
| 仪表板与 DataV 大屏创建、发布、截图 | `visual` | L0-L3 |
| 数据填报表单、任务与数据行 | `filling` | L0-L3 |
| 组织、用户与角色管理 | `admin organization-*`、`role-*`、`user-*` | L0-L3 |
| 系统设置、邮件、MFA、HMAC 与 SSO | `admin setting-*`、`sso-*` | L0-L3 |
| 钉钉、企微、飞书和 Larksuite | `admin integration-*` | L0-L3 |
| 定时报告与 Webhook | `report`、`webhook` | L0-L3 |

## 执行原则

1. 先检查实例、组织、版本、能力和目标资源，再设计或修改。
2. 范围明确的读取操作直接执行；任何写操作先生成 dry-run 计划。
3. 只执行用户确认的同一 `plan_id`。L3 必须同时提供计划返回的 `confirmation_token`。
4. 写入后回读目标；大屏和仪表板还要输出预览 URL 与截图/PDF。
5. 优先使用官方 API，其次使用明确匹配版本的适配器，最后才使用浏览器自动化，并在结果中说明适配器。

## 快速开始

复制 `.env.example` 为 `.env`。系统 API 优先使用 AK/SK，用户会话可使用用户名和密码。不得打印或提交 `.env`，也不得把密钥放进命令参数。

```bash
python -m venv .venv
python -m pip install -r requirements.txt
npm install
npx playwright install chromium
python scripts/dataease.py system doctor
```

使用当前虚拟环境的解释器：Windows 通常是 `python`，Linux/macOS 通常是 `python3`；跨平台脚本调用应优先使用 `python -m` 或当前解释器，不要写死系统路径。

默认代理模式为 `DATAEASE_PROXY_MODE=auto`：本机和私网 DataEase 地址绕过环境代理，公网地址保留代理。私有 CA 使用 `DATAEASE_CA_BUNDLE`；只在已知测试实例上使用 `--insecure`。

## 标准工作流

1. 首次连接运行 `python scripts/dataease.py system doctor` 和 `system capabilities`。
2. 只读取本次任务需要的参考：
   - 平台和数据能力：[references/platform.md](references/platform.md)
   - 大屏与仪表板设计：[references/visualization.md](references/visualization.md)
   - 命令和结果契约：[references/commands.md](references/commands.md)
   - DTO 规格示例：[references/specs.md](references/specs.md)
   - 风险、确认和回滚：[references/safety.md](references/safety.md)
   - 操作系统与 Agent 兼容性：[references/compatibility.md](references/compatibility.md)
   - 已验证范围和缺口：[references/validation.md](references/validation.md)
3. 读取目标组织、数据集和已有资源；名称不唯一时要求精确 ID。
4. 写操作先不加 `--apply`，向用户展示 `changes`、`risk`、`plan_id` 和回滚说明。
5. 用户确认后重复同一配置，并传入 `--apply --plan-id <id>`；L3 再传 `--confirm-token <token>`。
6. 回读并验证；目标、组织、版本、角色状态或请求载荷变化时废弃旧计划。

## 智能大屏与仪表板

先分析数据，再生成可视化方案：

```bash
python scripts/dataease.py dataset profile --dataset "销售数据"
python scripts/dataease.py dataset plan --dataset "销售数据" --title "销售经营分析" --busi-type dataV
```

审阅生成的 visual spec，校正业务口径后传给 `visual create --spec`。自动字段角色、聚合方式和 KPI 只是建议，不得把它们当作已经确认的业务定义。

## 安全边界

- 创建普通用户为 L1；创建带管理员角色的用户为 L3。
- 普通用户资料编辑为 L2；`roleIds` 发生变化立即升为 L3。
- `role-edit` 统一为 L3，防止角色定义或权限相关变更绕过确认。
- 删除、清空、启动/立即执行报告、认证/集成变更、禁用用户、数据源连接/结构变更和插件操作均为 L3。
- L3 没有回滚说明或明确的不可回滚确认时拒绝执行。
- DataEase 版本、目标快照、组织上下文、请求摘要和管理员角色状态均绑定计划；不允许复用、伪造或降级计划。
- DataEase X-Pack 功能取决于版本、授权和当前账号权限；`system capabilities` 未确认前不得宣称可用。

## 结果处理

统一 CLI 输出一个 JSON 文档，包含 `ok`、`operation`、`result`、`changes`、`artifacts`、`warnings` 和适用时的 `audit_id`。失败时返回脱敏的结构化错误并以非零状态退出。

在 Codex 中用绝对 Markdown 路径展示本地文件；OpenClaw 需要时使用 `MEDIA:<absolute_path>`；其他 Agent 按其宿主的附件协议处理。始终返回可用的 DataEase 预览 URL。报告收件人、Webhook 完整 URL、数据源密码、平台/SSO 密钥和用户敏感信息不得进入计划或公开结果。

## 兼容性

核心 CLI 使用 Python 3.10+，截图/PDF 额外使用 Node.js 18+、Playwright 和 Chromium。代码按 Windows、Linux、macOS 的路径与进程模型编写，但“可运行”和“已实测”必须区分；不得宣称所有 AI Agent 都原生支持。安装位置、宿主能力、已验证系统和适配方式见 [references/compatibility.md](references/compatibility.md)。

## 旧命令兼容

保留 `scripts/inspect_data.py`、`scripts/deploy.py`、`scripts/multi_deploy.py` 和 `scripts/capture_dashboard.py`，用于兼容既有调用参数与结果字段。新自动化优先使用 `scripts/dataease.py`，因为它提供能力检测、统一结果、安全计划、确认令牌和审计记录。
