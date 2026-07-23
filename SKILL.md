---
name: dataease
description: DataEase V2 智能平台技能 — 数据探索、可视化构建、平台管理、认证集成与自动化。触发场景：DataEase 数据集/数据源管理、仪表板/DataV 大屏创建编辑、权限编排、资源备份迁移、插件驱动管理、用户角色安全、SSO 集成、定时报告、Webhook 配置。
---

# 🖥️ DataEase V2 智能平台技能

一站式 DataEase 自动化——从数据探索到可视化构建，从平台管理到认证集成。高风险操作约束在 dry-run、确认令牌和回读验证流程中。

---

## 🎯 核心能力

| 功能 | 命令族 | 风险 |
|------|--------|------|
| 🔍 连接诊断与平台盘点 | `system`、`inventory` | L0 |
| 📊 数据源、数据集、SQL/多表模型、计算字段与行列权限 | `datasource`、`dataset`、`model` | L0–L3 |
| 📈 仪表板与 DataV 创建、组件编辑、联动、主题、发布、截图 | `visual` | L0–L3 |
| 🔐 用户/角色到具体业务资源的权限编排 | `permission` | L0–L3 |
| 🔄 可移植备份、恢复、跨实例迁移与原生导出 | `transfer` | L0–L3 |
| 🧩 插件与数据库驱动检查、安装、升级、回滚 | `plugin`、`driver` | L0–L3 |
| 🧠 数据质量→指标→模型→大屏→权限→报告一站式编排 | `solution` | L0–L3 |
| 📋 数据填报表单、任务与数据行 | `filling` | L0–L3 |
| 👥 组织、用户、角色与权限矩阵 | `admin organization-*`、`role-*`、`user-*` | L0–L3 |
| ⚙️ 系统设置、邮件、MFA、HMAC 与 SSO | `admin setting-*`、`sso-*` | L0–L3 |
| 🔗 钉钉、企微、飞书和 Larksuite | `admin integration-*` | L0–L3 |
| 📬 定时报告与 Webhook | `report`、`webhook` | L0–L3 |

---

## 🔒 安全分级

| 级别 | 描述 | 行为要求 |
|------|------|----------|
| 🟢 **L0** | 只读操作：列表、查看、诊断、截图 | 直接执行 |
| 🟡 **L1** | 普通创建：仪表板、DataV、表单、用户、数据资源 | 先 dry-run，用 plan_id 确认后执行 |
| 🟠 **L2** | 编辑操作：可视化组件/字段/主题/筛选器修改、模型保存、发布、编辑用户资料（不改角色） | 展示 diff，用 plan_id 确认后执行 |
| 🔴 **L3** | 高危操作：权限变更、恢复/迁移、方案执行、插件/驱动、删除、清空、报告启动、角色编辑、管理员创建、认证变更、用户禁用、数据源连接变更 | 必须提供快照/回滚说明 + plan_id + confirmation_token |

> 计划 30 分钟过期。目标、组织、版本或资源状态变化时废弃旧计划，重新 dry-run。

---

## 🚀 快速开始

**1. 配置环境**

复制 `.env.example` 为 `.env`，填入 DataEase 实例凭据（AK/SK 优先，也支持用户名密码登录）。

**2. 安装依赖**

```bash
pip install -r requirements.txt    # Python 依赖
npm install                        # Node 依赖 + Chromium（截图用，可选）
```

如果 Chromium 安装超时（受限网络/沙箱），设置 `DATAEASE_SKIP_BROWSER_INSTALL=1` 跳过，事后可手动 `npx playwright install chromium`。

**3. 验证安装**

```bash
python scripts/dataease.py system doctor
```

代理：`DATAEASE_PROXY_MODE=auto` 下私网地址自动绕过代理，私有 CA 用 `DATAEASE_CA_BUNDLE`。

---

## 📋 执行原则

1. 🔍 **先探查再操作**：检查实例、组织、版本、能力和目标资源后，再设计或修改。
2. 🛡️ **读直接做，写先计划**：读取操作直接执行；写操作先生成 dry-run 计划展示 `changes`、`risk`、`plan_id`。
3. 🔑 **严格确认**：只执行用户确认的同一 `plan_id`，L3 操作需额外提供 `confirmation_token`。
4. ✅ **写后验证**：写入后回读、逐图真实数据请求、发布预览与浏览器渲染确认；大屏和仪表板输出预览 URL 与截图/PDF。创建后任一关键验证失败时自动补偿删除本次新资源，避免留下打不开的半成品。
5. 🎯 **API 优先**：优先官方 API → 版本适配器 → 浏览器自动化，降级时说明原因。
6. 🤖 **模型能力降级**：不把看图或复杂 JSON 推理作为创建前提。模型能力有限、无多模态或上下文较小时，优先使用 `visual autopilot`，依据机器可读 `quality.ready/score/failed_checks` 决定是否执行；截图仅作为可选增强。`quality.ready=false` 时不得执行创建；固定 DataV 空间不足时减少组件、提高目标分辨率或改用 dashboard，不得静默改变资源类型。

---

## 📊 可视化构建

### 支持的图表类型

| 类型 | 模板 | plan 自动识别 |
|------|------|---------------|
| 📊 柱状图 | `bar` | 有维度 + 指标（默认） |
| 📈 折线图 | `line` | 有日期字段 |
| 🥧 饼图 | `pie` | 有维度 + 单个指标 |
| 📋 明细表 | `table_info` | 始终生成 |
| 📉 K 线图 | `candle` | OHLC 四价 (open/high/low/close) |
| ⚡ 仪表盘 | `gauge` | 当前值/得分 (current/value/score) |
| 🌊 瀑布图 | `waterfall` | 金额/盈亏 (amount/revenue/cost/profit) |

### 智能规划

先探查数据，再自动生成可视化方案：

```bash
# 数据探查
python scripts/dataease.py dataset profile --dataset "销售数据"
python scripts/dataease.py dataset preview --dataset "销售数据"

# 智能图表与布局规划
python scripts/dataease.py dataset plan --dataset "销售数据" --title "销售经营分析" --busi-type dataV
python scripts/dataease.py dataset plan --dataset "销售" --dataset "目标" --dataset "库存" --title "经营驾驶舱" --busi-type dataV

# 一站式方案执行
python scripts/dataease.py solution plan --spec sales-solution.json

# 无多模态/弱模型推荐入口：无需手写 visual spec
python scripts/dataease.py visual autopilot --dataset "销售数据" --title "销售驾驶舱" --busi-type dataV --complexity standard
```

规划器自动识别组件角色，并从经营总览、零售运营、运维指挥、地域态势、公共服务和分析工作台等设计语法中选择原型：KPI 置顶、重点趋势或地图获得主视觉、构成/排行作为证据、明细用于追溯。它只提炼 DataEase 官方模板市场与公开优秀案例的设计原则，不复制具体模板、素材或固定坐标。选择依据会写入 `design_inspiration`，详细边界和来源见 `references/design-inspiration.md`。生成的 visual spec 审阅确认后用 `visual create --spec` 执行。

`visual autopilot` 提供确定性的端到端规划入口。`compact` 最多 6 个组件，`standard` 最多 10 个，`rich` 最多 16 个，并始终尽量保留明细表。dry-run 返回完整计划、主题候选、纯文本质量评分与 `model_compatibility`；无多模态模型只需检查 `quality.ready=true` 后沿用 `plan_id` 执行。

Visual spec 可选传入 `canvas.width/height/screen_adaptor/typography`、`theme` 与 `interactions`。主题可使用内置名称或自定义对象；企业 Logo/背景图只在本地取色，文字对比度不足时自动修正。创建 dry-run 会输出三套 SVG 主题预览。`constraint-v3` 根据每个组件的标题宽度、字段数、类别/系列/图例/行数、图表渲染特性和目标设备计算最小/理想尺寸，统一求解 Dashboard 与 DataV 布局、检测碰撞，再独立调整标题、指标、图例、坐标轴、标签和表格字号；缺少值域统计时降级使用字段元数据估算。显式用户约束优先于自动建议。规划器还可创建日期/分类查询组件、同数据集筛选级联、同维度图表联动、层级下钻和 URL 跳转。`filter_cascades` 可显式声明顺序；省略时自动识别并按语义层级排列明确的地域、商品和组织字段，不依赖数据集字段顺序。修改已有查询组件时使用 `visual patch` 的 `cascade_updates`，禁止直接写入裸 `cascade` JSON。跨数据集同名字段只作为候选关系，不自动建立级联或联动。主题、布局和排版字段见 `references/visualization.md`。

内置主题为 `business-light`、`minimal-light`、`neon-dark`、`deep-ocean`、`dark-gold`、`tech-blue`、`chinese-red`、`government-blue`、`medical-health`、`energy-green`、`retail-vibrant`。它们同时作用于画布、组件背景、边框、文字和主色；也可通过主题对象或 `DATAEASE_BACKGROUND_IMAGE` 使用本地 Logo/背景图。

### 完整图表类型

| 分类 | 支持的图表 |
|------|-----------|
| 🔢 指标 | `indicator`、`gauge` |
| 📈 趋势 | `line`、`area`、`area-stack`、`candle` |
| 📊 柱形 | `bar`、`bar-stack`、`percentage-bar-stack`、`bar-group`、`bar-horizontal`、`bar-stack-horizontal`、`waterfall` |
| 🥧 构成 | `pie`、`pie-donut`、`pie-rose`、`pie-donut-rose`、`radar`、`treemap`、`word-cloud` |
| 📋 表格 | `table_info`/`table-info`、`table-normal`、`table-pivot`、`t-heatmap` |
| 🗺️ 地图 | `map`、`bubble-map`、`flow-map`、`heat-map`、`symbolic-map` |
| 🔗 关系 | `scatter`、`funnel` |

规划器默认生成指标卡、折线/面积趋势、柱形比较、横向排行、环形构成、地图和明细表；多指标、层级、阶段、文本和多维字段满足条件时，进一步选择散点、雷达、矩形树图、漏斗、词云、气泡地图和透视表。每个数据集最多规划 12 个画像组件，专业图表只在语义匹配时选择。以上是当前适配的常用集合，不代表 DataEase 产品内置的全部图表。未知类型会在创建前被拒绝。

---

## 🛡️ 安全边界

| 操作类型 | 风险 | 特殊约束 |
|----------|------|----------|
| 👤 创建普通用户 | L1 | 仅使用 DataEase 系统初始密码，拒绝自定义密码字段 |
| 👑 创建管理员用户 | L3 | role 为 root=true, readonly=false 时自动升级 |
| ✏️ 编辑用户资料 | L2 | roleIds 变化时立即升为 L3 |
| 🎭 角色编辑 | L3 | 只编辑名称/描述用 `role-edit`，修改权限矩阵用 `role-permission-set` |
| 🔑 权限编排 | L3 | `permission apply` 绑定 user/role 身份与资源范围，逐条校验 |
| 📐 行列权限 | L3 | `model permission-*` 变更数据暴露范围 |
| 🎨 可视化编辑 | L2 | `visual patch`、`model save` |
| 🔄 跨实例迁移 | L3 | 绑定源/目标实例、组织、版本、bundle 摘要和 ID 映射 |
| 🧩 插件/驱动变更 | L3 | 绑定精确包 SHA-256，回滚需自行保留已知安全版本 |
| 🗑️ 删除/清空 | L3 | 无回滚说明时拒绝执行 |
| 🔗 认证/集成变更 | L3 | 含 SSO、企业集成配置 |
| 📬 报告启动/创建 | L3 | — |
| ⏱️ 填报任务 | L2–L3 | 启停为 L2；立即执行和删除为 L3；停止只取消后续调度，不删除任务 |
| 🚫 禁用用户 | L3 | — |
| 🔌 数据源连接/结构变更 | L3 | — |
| 🧪 版本适配 | 动态 | 高于 `2.10.25` 默认只读；`DATAEASE_ALLOW_UNVERIFIED_VERSION=true` 仅在隔离兼容性测试中使用 |

> ⚠️ X-Pack 功能取决于版本、授权和账号权限。`system capabilities` 未确认前不得宣称可用。

数据填报表单可通过 `datasource`、`tableName`、`useExistsTable` 绑定数据库表；任务可配置一次性或周期计划，并支持查看、启动、停止、立即执行和删除。创建前先用 `filling datasources`、`datasource tables` 和 `filling task-info` 读取版本原生 DTO。字段与命令见 `references/specs.md` 和 `references/commands.md`。

创建用户时不得向 `user-create` 传入 `password`、`pwd`、`newPwd` 或同类字段。DataEase 创建 DTO 只应用系统初始密码；Skill 必须拒绝自定义密码字段，并在结果中报告 `password_mode=system_initial_password`，不得宣称自定义密码已经生效。

---

## 📋 标准工作流

1. 首次连接运行 `system doctor` 和 `system capabilities`。
2. 读取目标组织、数据集和已有资源；名称不唯一时要求精确 ID。
3. 按需查阅参考文档：`references/platform.md`、`references/visualization.md`、`references/design-inspiration.md`、`references/advanced.md`、`references/commands.md`、`references/safety.md`。
4. 写操作先不加 `--apply`，展示 `changes`、`risk`、`plan_id` 和回滚说明。
5. 用户确认后传入 `--apply --plan-id <id>`，L3 追加 `--confirm-token <token>`。
6. 回读验证，状态变化时废弃旧计划。

组织上下文：在 `.env` 设 `DATAEASE_ORG_ID`，或用 `--org-id` 参数。禁止打印或持久化组织 Token。

---

## 📦 结果输出

统一 CLI 输出 JSON：

```json
{"ok": true, "operation": "...", "result": {...}, "changes": [...], "artifacts": [...], "warnings": [...]}
```

列表命令返回 `{total_count: N, items: [...]}`，`--summary` 可附加按类型/路径的分组统计。

输出文件直接展示给用户；始终附带 DataEase 预览 URL。报告收件人、Webhook URL、数据源密码、SSO 密钥等敏感信息禁止出现在计划或公开结果中。

---

## 🔗 兼容性

- Python 3.10+（核心 CLI）
- Node.js 18+、Playwright + Chromium（截图/PDF，可选）
- 代码适配 Windows / Linux / macOS，但「可运行」≠「已实测」

详细兼容性见 `references/compatibility.md`。

---

## 📚 旧命令兼容

保留 `scripts/inspect_data.py`、`scripts/deploy.py`、`scripts/multi_deploy.py`、`scripts/capture_dashboard.py`，向后兼容既有调用参数。新自动化优先使用 `scripts/dataease.py`（能力检测、统一结果、安全计划、确认令牌、审计记录）。
