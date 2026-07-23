# 智能设计灵感

## 使用原则

把公开模板与优秀案例当作设计研究样本，不当作可复制成品。规划器必须：

1. 先依据数据字段、业务目标和屏幕类型选择信息，再选择风格。
2. 只提炼信息层级、构图、图表组合、配色角色和交互密度。
3. 不复制模板的具体坐标、标题、图片、图标、数据或品牌素材。
4. 不通过随机堆叠制造差异；同一输入保持可复现，不同业务语义允许不同原型。
5. 地图、漏斗、仪表盘等专业图表必须有字段语义支撑。
6. 装饰不得降低文字对比度、遮挡数据或挤占核心分析区域。

代码入口为 `scripts/dataease_skill/design_inspiration.py`。输出中的
`design_inspiration` 说明所选设计语法、选择依据和原则；
`layout_strategy` 说明布局原型与稳定变体。

## 内置设计语法

| 设计语法 | 适用场景 | 构图倾向 | 默认视觉倾向 |
|---|---|---|---|
| `executive-overview` | 经营、领导、年度总览 | KPI → 趋势/结构 → 明细 | 克制、结论优先 |
| `retail-operations` | 零售、电商、门店、供应链 | KPI → 趋势/排行 → 地域/构成 | 活跃但限制装饰色 |
| `financial-control` | 财务、预算、成本、资金 | KPI → 趋势/差异 → 审计明细 | 克制、差异优先 |
| `marketing-growth` | 营销、获客、渠道、转化 | KPI → 趋势/漏斗 → 渠道排行 | 高辨识但不喧宾夺主 |
| `project-delivery` | 项目、研发、任务、交付 | 进度/风险 → 趋势 → 责任明细 | 清晰的状态语义 |
| `operations-command` | 运维、安全、设备、工厂 | 状态/KPI → 主趋势 → 告警明细 | 深色指挥中心 |
| `geo-command` | 城市、区域、交通、环保 | KPI → 地图焦点 → 趋势/排行 | 地域态势风格 |
| `public-service` | 政务、民生、医疗 | 服务结果 → 趋势/比较 → 追溯 | 稳重、高可读 |
| `analytical-workbench` | 无明确行业或探索分析 | KPI → 比较/趋势 → 筛选/明细 | 中性分析工作台 |

选择不是只看标题：规划器同时检查是否实际存在地域、时间、排行等可用分析角色。
标题和字段证据冲突时，以字段可表达性为硬约束。例如标题包含“全国”，但没有可靠地域字段，
不得为了模仿大屏案例强行生成地图。

## 研究来源与提炼边界

- [DataEase V2 模板市场](https://templates.dataease.cn/store/apps?de-version=V2)：用于观察
  DataEase 可落地的行业分类、仪表板/数据大屏差异和常见页面层级。不得把市场素材打包进 Skill。
- [Microsoft Power BI dashboard design tips](https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards-design-tips)：
  用于校验受众导向、单屏聚焦、图表可读性和避免滥用圆形图等通用原则。
- [阿里云 DataV 数字大屏设计思路](https://help.aliyun.com/zh/datav/datav-6-0/getting-started/introduction-to-data-dashboard-design)：
  用于提炼先梳理数据内容再选组件、线框规划和限制颜色类别等大屏原则。
- [Dashboard Design Patterns 研究](https://arxiv.org/abs/2205.00757)：
  支持以可复用设计模式辅助仪表板创作，而不是固定复制一套布局。
- [MultiVision 研究](https://arxiv.org/abs/2107.07823)：
  支持数据列与多视图共同推荐、用户输入与自动推荐相结合的混合式思路。
- [Tableau Accelerators](https://www.tableau.com/solutions/exchange/accelerators)：
  用于观察销售、财务、项目管理等跨部门分析的业务问题组织方式，不复制其工作簿。
- [Tableau Visual Best Practices](https://help.tableau.com/current/blueprint/en-us/bp_visual_best_practices.htm)：
  用于提炼受众、上下文、Z 型阅读路径、留白、设备尺寸和可发现交互。
- [Grafana dashboard gallery](https://grafana.com/grafana/dashboards/) 与
  [dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/)：
  用于提炼运维监控的服务层级、时间范围、变量、告警与排障阅读路径。
- [IBM Carbon 数据可视化配色](https://v10.carbondesignsystem.com/data-visualization/color-palettes/)：
  用于区分类别色、顺序色和告警色，并约束相邻颜色可辨识度与无障碍。
- [Financial Times Visual Vocabulary](https://github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary)：
  用于按变化、排行、分布、相关性、流动等分析关系选择图表语法。

外部页面会更新，以上内容是原则性基线，不是对市场模板的永久镜像或完整清单。

规划结果还会返回 `design_dimensions`，包括受众模式、观看距离、信息密度、阅读路径、
图表角色组合、配色语义和交互策略。规划器组合“业务语法 + 数据关系 + 屏幕类型 +
复杂度”，因此不同行业可以共享有效原则，同一行业也不会被锁死在一张固定模板上。

## 质量门槛

- 核心指标位于阅读路径前部。
- 图表种类由分析任务决定，不以“丰富”为由重复表达同一信息。
- 趋势图获得足够横向空间，明细表横跨底部或进入下钻页。
- 查询区不覆盖图表，级联只建立在可信层级上。
- 正文文字达到 WCAG AA 普通文本对比度。
- 返回原创模式声明：`template_copying=false`、`external_assets_embedded=false`。
