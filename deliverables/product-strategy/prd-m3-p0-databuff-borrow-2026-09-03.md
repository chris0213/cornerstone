# M3 P0 详细设计：AI 入口前置 + 自适应告警 + 巡检自发现

**日期**：2026-09-03
**类型**：功能规格书 / 详细设计（PRD 级）
**归属里程碑**：M3 集成与智能（基石 Cornerstone）
**来源**：基于 Databuff 借鉴分析（competitive-analysis-databuff-borrow-2026-09-03.md）的 P0 三项
**参与成员**：竞析（对标）、路径（归位）、方向明（主理人综合，基于代码勘察）

---

## 📌 TL;DR

- 把 Databuff 借鉴清单中价值最高、且能直接补已知短板的三项，落到**基于真实代码的实现设计**。
- **P0-1 AI 入口前置 + 智能问数**：纯前端 + 复用已有 `/ai/search`，**零 schema 变更、零风险**，可立即启动。
- **P0-2 自适应告警 + 突变检测**：需 alembic 加列/加表（向后兼容），**中风险**，灰度谨慎。
- **P0-3 巡检免阈值自发现**：Phase A 仅后端调 LLM + 可空字段（低风险）；Phase B 需历史表（与 P0-2 共享，P1）。
- 升级安全铁律：所有 schema 变更只走 alembic（加列/加表，全可空），老逻辑不动；新能力默认关闭，按规则/角色灰度。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 推荐方案 | P0-1 立即做（前端）；P0-3 Phase A 紧随（后端 LLM 研判）；P0-2 排后（alembic，谨慎灰度） |
| 优先级 | P0（3 项均 P0，按风险排序实施） |
| 预期影响 | 降 AI 使用门槛、减误报漏报、提排障效率 |
| 资源需求 | 复用可插拔 LLM（ai_client）；P0-2 需历史指标采集 |
| 风险等级 | P0-1 低 / P0-3-A 低 / P0-2 中 |

---

## 代码现状基线（勘察结论）

| 模块 | 关键文件 | 现状要点 |
|------|---------|---------|
| 告警 | `backend/src/api/alerts.py`、`services/alert_service.py`（`evaluate_rules:30`→`_check_condition:155`）、`models/alert.py` | `AlertRule` 仅 `threshold` 静态值；`_check_condition` 只做静态比较；monitor 周期评估已具备；critical 已调 `_perform_ai_analysis:210` 做根因 |
| 巡检 | `backend/src/api/inspection.py`、`services/inspector.py`（`run_inspection:483`→`process_alerts:420`）、`models/inspection.py`、`tasks/inspection_scheduler.py` | 预设规则（离线/新设备/指纹变更/CPU>80% 硬编码）；`inspector` 当前**未引用** `ai_client` |
| AI/LLM | `backend/src/services/ai_client.py`（`call_ai:110`，多 provider）、`api/ai.py`（`/ai/search` 意图+SQL、`/ai/summary|trend|root-cause`、`/ai/config*`） | 可插拔 LLM 已就绪；问数端点已实现 |
| 前端 AI 入口 | `frontend/src/components/GlobalSearch.vue`（⌘K→`/ai/search`）、`lib/shortcuts.ts`、`App.vue`、`lib/ai.ts`（`useAIPrediction`） | 能力散落于命令面板与详情页；**无统一 AI 助手入口** |

---

## P0-1：AI 入口前置 + 智能问数

**目标**：让一线运维用自然语言直接查「指标 / 电路 / 设备 / 告警」，入口从"埋藏的 ⌘K + 散落详情页"提升为常驻、显眼的 AI 助手入口。

**用户故事**：
- 作为网络/容量运维，我希望在顶栏一点就能用中文问"上周核心电路丢包 Top5"，而不用在看板间翻找。
- 作为值班，我希望输入"还有哪些未恢复告警"立即得到清单。

**设计**：
- 前端：`App.vue` 顶栏新增常驻「AI 助手」入口（按钮 + 侧边抽屉/面板），打开即对话式问数，底层复用 `/ai/search`；保留 ⌘K 快捷触发，二者统一走 `GlobalSearch` + `lib/ai.ts`。
- 后端：确认/扩展 `/ai/search` 的意图解析（`ai_search.py`）覆盖**指标 / 电路 / 设备 / 告警**四类对象的查询语义；若未覆盖则扩展其意图词典与 SQL 生成。
- 多轮对话（会话上下文）列为 P1（需会话表，非本期强需）。

**升级安全**：纯前端 + 复用已有端点，**零 schema 变更、零风险**；灰度靠前端 feature flag（先对内部/特定角色可见）。

**验收标准**：
- 顶栏可见常驻入口；⌘K 仍可触发。
- "上周核心电路丢包 Top5""展示 XX 设备 CPU 趋势""未恢复告警有哪些"均能返回正确结果。

**工作量**：前端 2–3d；后端意图扩展 1–2d。
**依赖**：可插拔 LLM（已就绪）。

---

## P0-2：自适应告警 + 突变检测

**目标**：告警从纯静态阈值 → 支持突变检测 / 动态基线 / 事件回看，降低误报与漏报。

**设计**：
- **模型扩展（alembic 迁移，全可空、向后兼容）**：
  - `AlertRule` 增加 `detection_mode`(static|anomaly)、`baseline_window`、`baseline_sensitivity`、`mutation_threshold`（均默认/可空，老规则保持 static）。
  - 新增可选历史表 `MetricSample`（`device_id, metric, ts, value`）用于滚动基线/突变计算；仅采集必要指标，避免全量。
- **评估**：`_check_condition` 增加 `anomaly` 分支（滚动均值 ±k·std 或环比突变超阈值）；`static` 分支完全不变 → 老规则零影响。
- **事件回看**：基于 `MetricSample` + 已有 `AlertRecord` 提供历史曲线与告警时间轴查询端点。

**升级安全**：alembic 仅**加列/加表（可空）**，老数据兼容；`evaluate_rules` 老逻辑不动；新分支独立；`detection_mode` 默认 `static`，新能力默认关闭，按规则/角色逐步开启。必须走 alembic，容器启动顺序不变。

**验收标准**：
- 新建 anomaly 规则后，指标突变可触发告警而静态阈值不触发；老静态规则照常工作；历史回看可查。

**工作量**：后端 4–6d（含迁移、采集器、评估分支、回看端点）。
**依赖**：`MetricSample` 采集（接 monitor 轮询或独立采集任务）；告警通知链路复用。

---

## P0-3：巡检免阈值自发现

**目标**：巡检从预设规则（离线/新设备/指纹/CPU>80%）→ 增加「AI 自动发现异常」，减少漏报（尤其非阈值类异常）。

**设计（分阶段）**：
- **Phase A（零 schema，低风险）**：在 `process_alerts` 或 `run_inspection` 末尾，对本次巡检结果（SNMP 指标、指纹、拓扑）调用 `ai_client.call_ai` 做"是否异常/可疑"的二次研判，输出结构化异常摘要与建议；结果写入 `InspectionDeviceResult` 现有文本字段，或新增**可空 JSON 字段**（alembic 可空）。默认开关关闭。
- **Phase B（需历史，P1）**：横向设备基线对比（同类设备指标分布）、时间序列突变，复用 P0-2 的 `MetricSample` 历史表。

**升级安全**：Phase A 纯调 LLM + 可选可空字段，`inspector` 原有逻辑不变；feature flag 默认关。Phase B 走 alembic（共享表）。

**验收标准**：开启后，巡检对"非阈值类异常"（指标偏离同类设备、行为异常）也能产出提示；关闭时与现状完全一致。

**工作量**：Phase A 后端 2–3d；Phase B 复用 P0-2 历史表后实施。
**依赖**：`ai_client` 已就绪；Phase B 依赖 P0-2 的 `MetricSample`。

---

## MVP 切片（按风险排序，建议实施顺序）

| 顺序 | 项 | 风险 | 原因 |
|------|------|------|------|
| 1 | P0-1 AI 入口前置 | 低 | 纯前端 + 复用端点，零 schema 变更 |
| 2 | P0-3 Phase A 巡检 AI 研判 | 低 | 后端调 LLM + 可空字段，inspector 逻辑不变 |
| 3 | P0-2 自适应告警 | 中 | 需 alembic 加表/加列，灰度谨慎 |

---

## ✅ 行动清单

| # | 行动 | 负责方 | 时间窗 | 优先级 |
|---|------|--------|--------|--------|
| 1 | 前端常驻 AI 助手入口 + 复用 /ai/search | 前端 | 本周 | P0 |
| 2 | 扩展 /ai/search 意图覆盖 指标/电路/设备/告警 | 后端 | 本周 | P0 |
| 3 | 巡检末尾接入 ai_client 二次研判（Phase A，flag 默认关） | 后端 | 下周 | P0 |
| 4 | AlertRule 加列 + MetricSample 表（alembic，可空） | 后端 | 下周 | P0 |
| 5 | _check_condition 增加 anomaly 分支 + 事件回看端点 | 后端 | 下周 | P0 |
| 6 | 三项灰度开关 + 内部角色先行验证 | 全栈 | 随实施 | P0 |

---

## ⚠️ Non-goals（本期不做）

- 不建设故障预测能力（M4 静默异常清理≈降噪，避免重复造轮子）。
- 不引入应用层 Trace / QPS / JVM 指标。
- 多智能体编排/数字专家（M5）、MCP 开放接口（M6）不在本期。
- 多轮对话会话上下文（需会话表）列为 P1，不阻塞 P0-1。

---

## 📚 数据来源 & 成员产出索引

- 竞析：可借鉴功能清单与优先级（competitive-analysis-databuff-borrow-2026-09-03.md）。
- 路径：路线图归位与范围护栏（同文档第 5 节）。
- 代码勘察：alerts / inspection / ai_client / 前端 AI 入口真实路径与函数定位（见「代码现状基线」）。
- 未单独拉取：数析（指标评审）、瑞思（用户研究）——本设计为对标后的落地细化，相关维度以勘察与前期审计替代。

---

> 本报告由产品战略团队 AI 协作生成，重要决策请由产品负责人审定。
