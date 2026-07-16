# DataEase V2 智能平台 Skill

面向 AI Agent 的 DataEase V2 自动化能力包。它不仅能探索数据、创建仪表板和 DataV 大屏，也能在 dry-run、确认令牌、快照、回读和审计保护下管理数据源、数据集、数据填报、用户角色、系统设置、SSO、企业平台、定时报告与 Webhook。

## 核心能力

| 模块 | 能力 |
|---|---|
| 数据与分析 | 数据源/数据集盘点、字段分析、数据画像、智能可视化规划 |
| 仪表板与 DataV | 创建、发布、截图、PDF、主题与自动布局 |
| 数据填报 | 表单、任务和数据行的查询与安全变更 |
| 平台管理 | 组织、用户、角色、系统设置和邮件配置 |
| 认证与集成 | MFA、HMAC、LDAP、OIDC、CAS、OAuth2、SAML2、钉钉、企微、飞书 |
| 自动化 | 定时报告、执行日志、Webhook 和投递状态 |
| 安全治理 | L0-L3 风险分级、计划绑定、确认令牌、脱敏、快照、回滚说明和审计 |

## 安装

通过 Agent Skills CLI 从 GitHub 安装：

```bash
npx skills add North-CS/DataEase-skills --skill dataease --global
```

也可以克隆到目标 Agent 的 Skill 目录，例如 Codex：

```bash
git clone https://github.com/North-CS/DataEase-skills.git ~/.codex/skills/dataease
```

安装运行依赖：

```bash
python -m venv .venv
python -m pip install -r requirements.txt
npm install
npx playwright install chromium
```

截图/PDF 才需要 Node.js、Playwright 和 Chromium；纯 API 操作只需要 Python 3.10+。

## 配置

复制 `.env.example` 为 `.env`，只在本机填写凭据：

```dotenv
DATAEASE_BASE_URL=https://your-dataease.example.com
DATAEASE_API_PREFIX=/de2api
DATAEASE_ACCESS_KEY=your_access_key
DATAEASE_SECRET_KEY=your_secret_key
```

不要提交 `.env`，不要把 AK/SK 写入命令参数、Issue、截图或对话。生产环境优先使用宿主环境变量或密钥管理系统。

## 快速验证

```bash
python scripts/dataease.py system doctor
python scripts/dataease.py system capabilities
python scripts/dataease.py inventory scan
```

## 使用示例

在支持 Agent Skills 的客户端中直接使用自然语言：

```text
使用 $dataease 分析“销售数据”数据集，设计一个 1920×1080 的科技感 DataV 大屏。先生成方案，确认后再创建并截图。
```

也可以直接调用统一 CLI：

```bash
python scripts/dataease.py dataset profile --dataset "销售数据"
python scripts/dataease.py dataset plan --dataset "销售数据" --title "销售经营分析" --busi-type dataV
```

## 高风险操作

- L0：读取、盘点、诊断、截图，可直接执行。
- L1：普通创建，先 dry-run，再按 `plan_id` 执行。
- L2：普通更新或发布，展示变更后按计划执行。
- L3：权限、认证、集成、删除、清空、管理员创建等操作，必须提供计划返回的确认令牌。

角色编辑、用户角色变化和管理员用户创建均属于 L3。安全约束由 Python CLI 强制执行，不依赖 Agent 的文字提醒。

## 兼容性与文档

- Windows x64 已完成本地执行验证。
- Linux 和 macOS 按跨平台路径、进程与依赖模型实现，发布前应在目标宿主运行兼容性矩阵。
- Codex、Claude Code、Cursor、Gemini CLI、GitHub Copilot、Qwen Code、Qoder、OpenClaw 等可通过 Agent Skills 方式安装；无本地文件或 Shell 的平台需要封装 MCP/Tool。

详细说明：

- [Skill 主说明](SKILL.md)
- [命令参考](references/commands.md)
- [安全与确认](references/safety.md)
- [操作系统与 Agent 兼容性](references/compatibility.md)
- [验证状态](references/validation.md)

## 许可证

MIT
