# 基石 M3（AI 助手 / 巡检 AI 研判 / 自适应告警）运维说明

**日期**：2026-09-07（2026-09-08 补充：第 2.2 / 2.3 节新增 UI 入口）
**适用范围**：本次上线的 3 项能力 + 3 个新增迁移
**前置原则**：三项能力**默认均不改变任何现有行为**，需显式开启才生效。

---

## 一、上线内容总览

| 能力 | 默认状态 | 生效前提 | 影响面 | 回滚难度 |
|---|---|---|---|---|
| AI 运维助手（前端顶栏） | **已启用**（UI 可见） | 系统已配置 AI | 仅前端交互，无 schema 变更 | 低（回滚前端） |
| 巡检 AI 二次研判 | **关闭** | settings 开关 + AI 已配置 | 每次巡检多一次 LLM 调用 | 低（UI 开关 / 改 settings） |
| 自适应告警 / 突变检测 | **关闭**（detection_mode=static） | 单条规则显式切 anomaly | 新增 metric_samples 写入 | 中（含 schema） |

### 迁移清单（容器启动时 `alembic upgrade head` 自动执行）

| 顺序 | revision | 内容 | 破坏性 |
|---|---|---|---|
| 1 | `8c7cdaf81911` | `inspection_results` 加 `ai_summary`（可空 JSON） | 无（仅加列） |
| 2 | `edccf922899a` | `alert_records.device_id` 改为可空 | 放宽约束，无破坏 |
| 3 | `7d0e8fb1d835` | `alert_rules` 加 4 列 + 新建 `metric_samples` 表 | 无（仅加列/加表） |

链路：`7767ffc9a3bb` → `2733fdbc9397` → `8c7cdaf81911` → `edccf922899a` → `7d0e8fb1d835`（单一 head，无分叉）

---

## 二、启用方式

### 1. AI 运维助手（无需额外操作）

顶栏蓝色「AI 运维助手」按钮，点击打开右侧抽屉；原 `⌘K` 全局搜索保留。
支持自然语言查询指标 / 电路 / 设备 / 告警，例如：
- 「上周核心电路丢包 Top5 有哪些」
- 「还有哪些告警未恢复」

**依赖**：系统设置 → AI 设置 中已配置 provider / api_key / model。未配置时提问会返回失败提示，属正常。

### 2. 巡检 AI 二次研判

**首选（UI，需超管权限）**：系统设置 → AI 设置 → 页面顶部「巡检 AI 二次研判」卡片 → 打开开关 → 自动保存。
对应接口：`GET / PUT /api/v1/settings/ai-inspection`，请求与响应均为 `{"enabled": true|false}`。
开关状态与写入 settings 表的效果完全等价，且变更会记录审计日志（关键字：`更新巡检AI二次研判开关`）。

**备用（直接写库，UI 不可达时使用）**：

```sql
INSERT INTO settings (key, value)
VALUES ('ai_inspection_settings', '{"enabled": true}')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```

- 结果写入 `inspection_results.ai_summary`，可通过
  `GET /api/v1/inspection/results/{result_id}` 查看。
- **成本提示**：每次巡检（快速 + 全量）结束时会调用一次 LLM，注意 token 消耗与响应耗时。
- 关闭：把 value 改为 `{"enabled": false}`，或删除该行。缺省即视为关闭。

### 3. 自适应告警 / 突变检测（按规则粒度开启）

**首选（UI）**：系统设置 → AI 设置 → 页面顶部「自适应告警基线」卡片。
表格列出全部告警规则，「检测模式」列下拉切换「静态阈值 / 自适应基线」，改完点该行「保存」。
- 条件类型不是 `latency` / `packet_loss` 的规则，下拉**禁用**并提示「仅支持延迟与丢包规则」——这是后端限制，不是 UI bug。
- 三个参数输入框在「静态阈值」模式下禁用；切到「自适应基线」后自动填入默认值（60 / 3.0 / 0.5）。
- 每行独立保存，未点保存的改动不会提交。

**等价 API**：

```http
PUT /api/v1/alerts/rules/{rule_id}
Content-Type: application/json

{
  "detection_mode": "anomaly",
  "baseline_window": 50,
  "baseline_sensitivity": 3.0,
  "mutation_threshold": 0.5
}
```

参数说明：

| 参数 | 默认 | 说明 |
|---|---|---|
| `baseline_window` | 50 | 参与统计的最近样本数，实际取值会被限制在 10–500 |
| `baseline_sensitivity` | 3.0 | z-score 阈值，越大越迟钝 |
| `mutation_threshold` | 0.5 | 相对变化率阈值（0.5 = 偏离基线均值 50%） |

判定逻辑（任一命中即告警）：
1. z-score：`|当前值 - 均值| / 阻尼后标准差 > baseline_sensitivity`
2. 变化率：`|当前值 - 均值| / max(|均值|, 1.0) > mutation_threshold`

**重要：冷启动保护** —— 样本数 < 10 时**一律不告警**。
开启后需等待监控轮询积累至少 10 个采样点才会开始判定，请预留观察时间，不要误判为「功能没生效」。

采样写入规则：
- **仅当存在任一 `detection_mode='anomaly'` 的启用规则时**才写入 `metric_samples`；全部为 static 时零写入。
- 保留 7 天，每小时最多清理一次过期数据（限频执行，避免高频 DELETE 冲击生产库）。

事件回看：
```http
GET /api/v1/alerts/records/{record_id}/history?limit=200
```
返回该告警对应指标的采样序列、基线统计（均值/标准差）与告警快照。

---

## 三、灰度建议（强烈建议按此顺序）

1. 选 **1 条非关键、非 critical** 的规则（建议先 latency，后 packet_loss）。
2. 切换为 `anomaly`，观察 **24–48 小时**，确认无误报。
3. 确认后逐步扩大到更多规则。
4. 巡检 AI 研判建议先对**单次手动巡检**验证效果，再放开定时巡检。

---

## 四、回滚

### 方案 A：仅关闭能力（不动 schema，推荐优先）

最快路径：系统设置 → AI 设置 → 关掉「巡检 AI 二次研判」开关；「自适应告警基线」表格里把所有规则切回「静态阈值」并逐行保存。
等价 SQL 如下（UI 不可达时使用）：

```sql
-- 关闭巡检 AI 研判
UPDATE settings SET value = '{"enabled": false}' WHERE key = 'ai_inspection_settings';

-- 关闭自适应告警（把所有规则切回静态阈值）
UPDATE alert_rules SET detection_mode = 'static' WHERE detection_mode = 'anomaly';

-- 可选：清空采样数据
-- TRUNCATE metric_samples;
```

AI 运维助手为纯前端能力，回滚前端版本即可。

### 方案 B：完整回滚（含 schema），**必须按逆序执行**

```bash
# 1) 撤销 7d0e8fb1d835（删除 metric_samples 表与 4 个新增列）
alembic downgrade edccf922899a

# 2) 撤销 edccf922899a（device_id 恢复 NOT NULL）
alembic downgrade 8c7cdaf81911

# 3) 撤销 8c7cdaf81911（删除 ai_summary 列）
alembic downgrade 2733fdbc9397
```

⚠️ **第 2 步有前置条件**：若 `alert_records` 中已存在 `device_id` 为 NULL 的行（巡检「发现未登记设备」告警产生），迁移会**主动抛错拒绝回滚**，以防 `ALTER ... SET NOT NULL` 半途失败。请先核对并清理：

```sql
SELECT COUNT(*) FROM alert_records WHERE device_id IS NULL;
-- 确认这些记录为巡检新设备告警、可以丢弃后：
DELETE FROM alert_records WHERE device_id IS NULL;
```

---

## 五、观察与排障

| 现象 | 排查方向 |
|---|---|
| 表 `metric_samples` 增长过快 | `SELECT count(*) FROM metric_samples;`；估算 = 设备数 × 2 指标 × 轮询频率。确认是否误开了大量 anomaly 规则 |
| 自适应告警不触发 | ① `detection_mode='anomaly'`？② `condition_type` 是否为 latency/packet_loss（status 类型不支持）？③ 样本是否 ≥10？ |
| 巡检无 `ai_summary` | ① settings 开关是否 true？② AI 是否已配置？③ 后端日志搜索 `[巡检AI二次研判]` |
| 事件回看为空 | 静态阈值规则本就不产生采样点，属预期；需开启 anomaly 后才有数据 |
| 告警文案异常 | 自适应模式的文案为「显著偏离历史基线」，含均值/标准差/变化率，与静态阈值文案不同，属预期 |
| AI 设置页顶部卡片空白 / 加载失败 | 两个接口均需**超管**权限，非超管账号不显示数据；打开浏览器 Network 看 `/api/v1/settings/ai-inspection` 与 `/api/v1/alerts/rules` 的响应码 |
| UI 保存成功但规则未生效 | 确认点了该行「保存」按钮（改动不会自动提交）；`SELECT detection_mode FROM alert_rules WHERE id={rule_id};` 核对 |

---

## 六、已知边界

- `status` 类型的告警规则**不支持**自适应检测（无连续数值），会走原有静态逻辑。
- 巡检产生的「发现未登记设备」告警 `device_id` 为 NULL；若前端或报表直接访问关联设备属性，需能处理空值（API 层已确认安全，仅序列化为 null）。
- AI 研判为「异常二次研判」，**不做故障预测**（与既有降噪/静默异常清理分工，避免重复建设）。
- 采样数据仅用于滚动基线，不是完整的时序数据库，不建议作为容量趋势分析的唯一数据源。

---

> 本说明对应代码变更：P0-1 前端 AI 助手、P0-3A 巡检 AI 二次研判、P0-2 自适应告警，以及 `Alert` NameError 完整修复。
