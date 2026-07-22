# 🖥️ DataEase V2 智能平台 Skill

面向 AI Agent 的 DataEase V2 自动化能力包。覆盖数据探索、可视化构建、平台管理、认证集成全链路，高风险操作约束在 dry-run、确认令牌和回读验证流程中。

---

## 🎯 核心能力

| 模块 | 能力 |
|------|------|
| 🔍 数据与分析 | 数据源/数据集盘点、SQL/多表模型、计算字段、参数、行列权限、数据画像、多数据集规划 |
| 📈 仪表板与 DataV | 创建、组件级编辑、筛选联动、主题布局、发布、截图、PDF |
| 🔐 权限与迁移 | 用户/角色资源授权、可移植备份/恢复、跨环境 ID 映射和迁移 |
| 🧩 扩展与编排 | 插件/数据库驱动生命周期，质量→指标→模型→大屏→权限→报告一站式流水线 |
| 📋 数据填报 | 表单、任务和数据行的查询与安全变更 |
| 👥 平台管理 | 组织、用户、角色、权限矩阵、系统设置和邮件配置 |
| 🔗 认证与集成 | MFA、HMAC、LDAP、OIDC、CAS、OAuth2、SAML2、钉钉、企微、飞书 |
| 📬 自动化 | 定时报告、执行日志、Webhook 和投递状态 |
| 🛡️ 安全治理 | L0–L3 风险分级、计划绑定、确认令牌、脱敏、快照、回滚说明和审计 |

---

## 🚀 安装

克隆到本地 Skill 目录：

```bash
git clone https://github.com/North-CS/DataEase-skills.git <skills-dir>/dataease
```

安装依赖：

```bash
pip install -r requirements.txt    # Python 依赖（必需）
npm install                        # Node 依赖 + Chromium（截图用，可选）
```

截图/PDF 才需要 Node.js、Playwright 和 Chromium；纯 API 操作只需 Python 3.10+。如果 Chromium 安装超时，设 `DATAEASE_SKIP_BROWSER_INSTALL=1` 跳过，事后可 `npx playwright install chromium` 补装。

---

## ⚙️ 配置

复制 `.env.example` 为 `.env`：

```dotenv
DATAEASE_BASE_URL=https://your-dataease.example.com
DATAEASE_ACCESS_KEY=your_access_key
DATAEASE_SECRET_KEY=your_secret_key
```

禁止提交 `.env`，禁止把 AK/SK 写入命令参数、Issue、截图或对话。

---

## ✅ 快速验证

```bash
python scripts/dataease.py system doctor
python scripts/dataease.py system capabilities
python scripts/dataease.py inventory scan
```

---

## 💡 使用示例

自然语言交互（在支持的 Agent 中）：

```text
分析"销售数据"数据集，设计一个 1920×1080 的科技感 DataV 大屏。先生成方案，确认后再创建并截图。
```

直接调用 CLI：

```bash
# 数据探查
python scripts/dataease.py dataset profile --dataset "销售数据"
python scripts/dataease.py dataset preview --dataset "销售数据"

# 智能图表与布局规划
python scripts/dataease.py dataset plan --dataset "销售数据" --title "销售经营分析" --busi-type dataV
python scripts/dataease.py dataset plan --dataset "销售" --dataset "目标" --dataset "库存" --title "经营驾驶舱" --busi-type dataV

# 一站式方案
python scripts/dataease.py solution plan --spec sales-solution.json
```

---

## 🔒 安全分级

| 级别 | 描述 | 行为要求 |
|------|------|----------|
| 🟢 **L0** | 只读：列表、查看、诊断、截图 | 直接执行 |
| 🟡 **L1** | 普通创建：仪表板、DataV、表单、用户 | 先 dry-run，按 `plan_id` 确认后执行 |
| 🟠 **L2** | 编辑操作：可视化/字段/主题修改、模型保存、发布 | 展示 diff，按 `plan_id` 确认后执行 |
| 🔴 **L3** | 高危：权限变更、删除、迁移、插件/驱动、管理员创建、认证变更 | 需 `plan_id` + `confirmation_token` + 回滚说明 |

角色编辑、权限矩阵变化、用户角色变化和管理员创建均属 L3。安全约束由 Python CLI 强制执行。

---

## 🔗 兼容性

- Python 3.10+（核心 CLI）
- Node.js 18+（截图/PDF，可选）
- Windows x64 已完成本地验证；Linux / macOS 按跨平台模型实现

---

## 📚 文档

- [Skill 主说明](SKILL.md)
- [命令参考](references/commands.md)
- [高级平台编排](references/advanced.md)
- [安全与确认](references/safety.md)
- [操作系统与 Agent 兼容性](references/compatibility.md)
- [验证状态](references/validation.md)

---

## 📄 许可证

MIT
