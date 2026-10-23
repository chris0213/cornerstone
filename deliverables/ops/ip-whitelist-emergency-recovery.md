# IP 白名单应急恢复手册

> 适用范围：「基石」系统 安全设置 / IP 白名单功能（2026-10-23 阶段 2 加固后版本）
> 关联代码：[backend/src/utils/ip_whitelist.py](file:///Users/pancq/Desktop/trae/基石/backend/src/utils/ip_whitelist.py)、[backend/src/api/settings.py](file:///Users/pancq/Desktop/trae/基石/backend/src/api/settings.py)

---

## 一、三道安全防线（恢复前先了解）

| 防线 | 说明 | 对应急的意义 |
|------|------|-------------|
| 回环豁免 | `127.0.0.1`、`::1`、`localhost` 直连后端时**永远放行**，不受白名单约束 | **首选自救通道**：登录服务器本机即可管理 |
| 防自锁 | 保存时若操作者 IP 不在名单内，返回 409 `IP_WHITELIST_LOCKOUT`，需前端二次确认或 `force=true` 才能保存 | 正常情况下不会因误操作锁死 |
| XFF 防伪造 | 仅当 TCP 直连 IP 命中 `TRUSTED_PROXIES` 时才采信 `X-Forwarded-For`，否则一律用直连 IP | 伪造请求头无法绕过白名单 |

## 二、应急恢复方式（按优先级）

### 方式 1：本机回环自救（推荐，零配置）

白名单只拦远程访问。在**部署服务器本机**执行：

```bash
# 1. 用本机回环地址调用自救接口（该路径在白名单中间件中精确放行）
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<密码>"}'

# 2. 拿 token 清空白名单（也可改为写入正确网段）
curl -s -X PUT http://127.0.0.1:8000/api/v1/settings/security/ip-whitelist \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"value": ""}'
```

> 前端同理：在服务器本机打开浏览器访问 `http://127.0.0.1:8000`（或本机部署的前端指向本机后端），回环 IP 自动放行，可正常进入安全设置页面修改。

### 方式 2：应急开关（白名单完全失效时）

通过环境变量临时禁用白名单检查，**重启后端生效**：

```bash
# 值为 true/1/yes（不区分大小写）即禁用
IP_WHITELIST_DISABLED=true ./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

禁用后：
- 所有 IP 均可访问（HTTP 与 WebSocket 同时放开，`get_ws_user` 内的 `check_ws_ip_allowed` 同样读该开关）；
- 恢复后记得**移除该环境变量并重启**；
- 禁用状态只影响运行时检查，数据库中的名单数据不会被修改或删除。

> systemd 部署：`systemctl edit <服务名>` 添加 `Environment=IP_WHITELIST_DISABLED=true` 后 `systemctl restart`；Docker 部署：`-e IP_WHITELIST_DISABLED=true`。

### 方式 3：直接改数据库（前后端都不可用时的兜底）

白名单存储在 `settings` 表的 `security.ip_whitelist` 行（`value` 列，JSON 数组或纯文本行均可）：

```sql
-- 清空（恢复默认放行所有）
UPDATE settings SET value = '' WHERE key = 'security.ip_whitelist';

-- 或改为指定网段（JSON 数组格式示例）
UPDATE settings SET value = '["10.0.0.0/8", "192.168.1.0/24"]'
WHERE key = 'security.ip_whitelist';
```

修改后无需改库即可生效等待：进程内缓存 30 秒 TTL 自动过期；紧急时可重启后端立即生效。

> SQLite 库文件位置以部署配置为准（默认 `backend/data/` 下）；MySQL/PostgreSQL 按实际连接信息操作。

## 三、自救接口说明

白名单中间件放行路径已收窄为**精确**两个认证端点 + 白名单端点本身：

| 路径 | 放行方式 | 用途 |
|------|---------|------|
| `PUT /api/v1/settings/security/ip-whitelist` | 精确放行（无需登录） | 配合登录 token 修改名单 |
| `GET /api/v1/auth/ldap/enabled`、`POST /api/v1/auth/ldap/login` | 精确放行 | 登录页可用性探测与登录 |

> 注意：`PUT ip-whitelist` 虽然中间件放行，但**接口本身仍要求超管权限**（403 保护），并非无鉴权写入。

## 四、预防措施

1. **保存前预演**：安全设置页提供「预演」功能（`POST /api/v1/settings/security/preview`），保存前先验证关键 IP（办公网出口、跳板机）是否命中；
2. **当前 IP 一键加入**：页面顶部显示当前访问 IP，可一键加入名单，避免漏配自己的出口 IP；
3. **二次确认**：保存不含自己 IP 的名单时系统强制弹窗（409 `IP_WHITELIST_LOCKOUT`），确认了解风险后才允许 `force` 保存；
4. **代理场景**：若部署在 Nginx 等反代之后，务必设置 `TRUSTED_PROXIES=<代理IP>`，否则白名单看到的是代理 IP 而非真实客户端 IP；多个代理用逗号分隔，支持 CIDR；
5. **改动留痕**：每次保存均写入 `audit_logs`（动作 `ip_whitelist_create/update/clear`，含网段数、操作人、来源 IP、是否 force），锁死事故可据此回溯。
