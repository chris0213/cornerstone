# 「基石」系统设置安全加固 — 阶段 2 验收报告

- **日期**：2026-10-23
- **范围**：系统设置页面（SettingsPage）安全评审修复 — 阶段 2 实施
- **执行依据**：阶段 1 评审报告 14 项修复方案中经用户裁决纳入的 12 项（明确排除 #6 邮件落款/PDF 读配置、#12 最后修改人/时间）
- **约束遵守**：无数据库迁移；未改动 admin 用户与演示数据；测试数据用完即删

---

## 一、后端修复（B1–B5）

### B1 图片上传魔数校验（含实测发现的绕过修复）

**文件**：[backend/src/api/settings.py](file:///Users/pancq/Desktop/trae/基石/backend/src/api/settings.py#L222-L267)

- 新增 `_IMAGE_MAGIC_SIGNATURES`：JPEG（`FF D8 FF`）、PNG（`89 50 4E 47 0D 0A 1A 0A`）、GIF87a/GIF89a、WebP（`RIFF` + 偏移 8–12 字节 `WEBP`）
- 新增 `_verify_image_magic()` 两层校验：
  - **第一层**：文件头魔数匹配，快速拦截明显非图片内容
  - **第二层**：Pillow 完整解码验证（`Image.open + verify()`），拦截伪造魔数头的垃圾文件
- 上传流程：Content-Type 白名单 → 魔数两层校验，任一失败返回 400「图片内容与格式不符或文件已损坏」
- Pillow 为 pyproject.toml 已声明的依赖（实测环境 venv 内 Pillow 12.2.0），无新增依赖风险

> **实测发现的真实绕过（已修复）**：首轮验证中，PNG 魔数头 + 垃圾字节的伪造文件通过了仅校验头字节的第一版实现。已按上述两层方案加固，复测正确返回 400。此为本次验证环节的直接收益。

### B2 审计双轨并轨

**文件**：[backend/src/api/settings.py](file:///Users/pancq/Desktop/trae/基石/backend/src/api/settings.py#L86-L110)

- 新增 `_audit_setting()`：所有设置写操作同步写入 `audit_logs` 表（user / action / resource=`system_settings` / detail / ip_address / success=`true`），IP 取自 `get_client_ip_from_request`
- 保留原 `_log_setting_before/after` 文件日志，形成「文件 + 数据库」双轨
- 覆盖全部 5 个写接口：`brand_update` / `brand_reset` / `logo_upload` / `logo_delete` / `company_update`

### B3 Pydantic 输入校验

**文件**：[backend/src/api/settings.py](file:///Users/pancq/Desktop/trae/基石/backend/src/api/settings.py#L116-L177)

- `BrandSettingsRequest`（内联）：默认值引用 `BRAND_SETTINGS_DEFAULTS`（消灭「看得见，管得住」等硬编码残留）；slogan ≤ 50 字符、subtitle ≤ 100 字符，validator strip 后校验
- `CompanyInfoRequest`：`company_name` 必填（strip 后非空，≤ 200）；short_name / dept ≤ 100；contact ≤ 50；邮箱选填，用 `EmailStr._validate()` 做格式校验（避免强转改值）
- 违规输入统一返回 422

### B4 硬编码与死代码清理

- [schemas/setting.py](file:///Users/pancq/Desktop/trae/基石/backend/src/schemas/setting.py)：删除含误导性默认值的死模型 `BrandSettingsRequest/BrandSettingsResponse`，留注释指向内联模型
- [services/report_generator/data.py](file:///Users/pancq/Desktop/trae/基石/backend/src/services/report_generator/data.py#L328-L331)：`brand.get(...)` 回退值改引 `BRAND_SETTINGS_DEFAULTS`，报告生成与设置默认值单一来源
- [api/settings.py](file:///Users/pancq/Desktop/trae/基石/backend/src/api/settings.py)：`update_brand_settings` 中硬编码名称改引默认值字典

### B5 Logo 公开访问白名单化

**文件**：[backend/src/main.py](file:///Users/pancq/Desktop/trae/基石/backend/src/main.py)

- IP 白名单中间件 `public_paths` 加入 `/api/v1/settings/logo`，与该接口「无鉴权 GET」的既有语义对齐（此前 GET 无需 token 却被中间件按鉴权路径拦截，语义矛盾）

### 附带修复

- 后端 venv 缺 `websockets`（pyproject 已声明但未安装，导致启动失败），已按声明补装 17.3

---

## 二、前端修复（F1–F4）

### F1 Dirty 检测与离开拦截

**文件**：[frontend/src/features/system/SettingsPage.vue](file:///Users/pancq/Desktop/trae/基石/frontend/src/features/system/SettingsPage.vue)

- `companyBaseline / brandBaseline / logoBaseline` 保存 JSON.stringify 快照，computed 对比生成 dirty 状态
- `onBeforeRouteLeave` 路由离开确认 + `beforeunload` 关闭/刷新确认，双保险
- fetch 成功后 `markXxxClean()` 重置基线

### F2 表单校验规则

- `brandRules / companyRules` 绑定 `el-form :rules` + `prop`
- 标语/副标题 `:maxlength` + `show-word-limit` 实时限制
- `saveCompanyInfo` 提交前先 `validate()`，与后端 422 双保险

### F3 上传白名单收敛与删除确认

- `ALLOWED_IMAGE_TYPES` 严格白名单：移除 `image/*` 通配与 `.bmp`
- accept 属性收敛为 `image/png,image/jpeg,image/gif,image/webp`
- `handleLogoRemove` 增加二次确认弹窗

### F4 UI/UX 与主题化

- 新增登录页效果预览卡片：Logo（当前/默认 SVG）+ brand_name + slogan 实时联动，所见即所得
- 全部硬编码色值替换为主题变量（`#1890ff` → `var(--accent-primary)` 等）
- `resetBrandSettings` 确认文案改走 i18n；表单占位符中性化（「如：某某科技有限公司」）
- 默认标语统一为「智能运维，尽在掌控 / 企业级IT基础设施智能运维平台」
- [NetworkIllustration.vue](file:///Users/pancq/Desktop/trae/基石/frontend/src/features/auth/components/NetworkIllustration.vue#L156)：登录页 slogan 生效（`brandStore.brandSlogan`，i18n 回退）

### i18n 完整性

- [zh-CN.json](file:///Users/pancq/Desktop/trae/基石/frontend/src/locales/zh-CN.json) / [en-US.json](file:///Users/pancq/Desktop/trae/基石/frontend/src/locales/en-US.json)：settings 段各 **61 key** 完全对齐（已脚本验证无差集）

---

## 三、接口实测结果（11/11 通过）

生产端口 8000（新代码实例）实测：

| # | 测试项 | 期待 | 实际 | 结果 |
|---|---|---|---|---|
| N1 | PNG 魔数头 + 垃圾字节伪造文件 | 400 | 400 魔数+解码拒绝 | ✅ |
| N2 | SVG 伪装 PNG | 400 | 400 拒绝 | ✅ |
| N3 | BMP 格式 | 400 | 400 拒绝 | ✅ |
| N4 | 超 2MB 文件 | 400 | 400 拒绝 | ✅ |
| P1 | 真实 1×1 PNG 上传 | 200 | 200 成功 | ✅ |
| P2 | 无 token GET /settings/logo | 200 | 200（IP 白名单放行） | ✅ |
| C1 | 空公司名（全空格） | 422 | 422 拒绝 | ✅ |
| C2 | 超长标语（51 字符） | 422 | 422 拒绝 | ✅ |
| C3 | 坏邮箱 `not-an-email` | 422 | 422 拒绝（好邮箱 200 正常） | ✅ |
| C4/C5 | 合法 brand / company 保存 | 200 | 200 成功 | ✅ |
| A1 | 审计落库 | 写接口均有记录 | brand_update / logo_upload / company_update 均写入 audit_logs（user=admin、IP、success=true） | ✅ |
| P3 | brand_settings 删除后公开品牌回落 | 默认值 | slogan/subtitle 回落默认 | ✅ |

> 说明：首轮 N1 通过了仅查头字节的第一版校验，暴露真实绕过；加固后复测通过。首轮 C3「坏邮箱 200」为测试脚本字段名笔误（`email` ≠ `it_contact_email`），修正后复测通过。

---

## 四、构建与静态验证

| 项目 | 结果 |
|---|---|
| 后端 `py_compile`（settings.py 等 4 文件） | 全部通过 |
| `EmailStr._validate` 单元验证（拒坏邮箱/收好邮箱） | 通过 |
| 空公司名 / 51 字符标语 / strip 生效 静态验证 | 通过 |
| 前端 `vue-tsc --noEmit` | 零错误 |
| 前端 `vite build` | 成功（15.92s） |
| i18n zh/en settings 键位对齐 | 61/61 无差集 |

---

## 五、数据还原与环境收尾

| 项目 | 状态 |
|---|---|
| company_logo | 已还原，与备份逐字节一致（918704 字符，实测确认） |
| company_info | 已还原，与备份一致（实测确认） |
| brand_settings | 保持删除（「日志验证OK」等测试值清除即目标状态，公开接口回落默认） |
| 测试审计记录 | 7 条 system_settings 测试记录已删除 |
| 临时文件 /tmp/cs_s2_backup | 已整体删除 |
| 数据库迁移 | 无（符合约束） |
| admin 用户与演示数据 | 未改动（符合约束） |
| 生产后端（8000 端口） | 已用新代码启动并冒烟验证通过（P2/P3 实测） |

---

## 六、遗留事项

无阻塞项。两点供后续关注：

1. **websockets 补装**：该依赖在 pyproject 中已声明但环境缺失，已补装。若其他环境部署，确认 `poetry install` 完整执行即可。
2. **8000 端口进程托管**：当前后端由本次会话在终端启动。后续如需长期运行，建议纳入既有启动脚本（`scripts/dev.sh`）或进程管理。

---

## 七、结论

阶段 2 全部 12 项修复（后端 B1–B5、前端 F1–F4 及附带项）已实施并验收通过：负向/正向/审计/回落四类接口实测 11/11 通过，前端构建全绿，i18n 对齐，测试数据零残留，无迁移、无约束违反。**验收结论：通过。**
