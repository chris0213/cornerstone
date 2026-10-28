# 基石 Cornerstone

> 企业级IT基础设施智能运维平台 — 站点 / 专线 / IP / 设备 / 备份 / 拓扑 / 预警 / AI 一体化管理。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5-42b883)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688)](https://fastapi.tiangolo.com/)

> ⚠️ **安全提醒**：首次部署后请立即修改默认管理员密码（`INITIAL_ADMIN_PASSWORD`），并将 `SECRET_KEY` 替换为随机字符串。生产环境推荐使用 PostgreSQL。

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [功能模块](#功能模块)
- [项目结构](#项目结构)
- [认证与权限](#认证与权限)
- [国际化](#国际化)
- [AI 能力](#ai-能力)
- [部署](#部署)
- [License](#license)

---

## 项目简介

**基石** 是一款面向中大型网络运维团队的企业级IT基础设施智能运维平台，提供从站点、专线、IP、设备到配置备份与拓扑监控的全链路资源台账管理能力，并集成基于大语言模型的智能搜索、备份分析与异常预测。

适用场景：
- 多分支站点的网络资源台账管理
- 运营商专线 / MPLS / SD-WAN 合同到期跟踪
- 子网与 IP 地址生命周期管理
- 网络设备配置自动备份与版本对比
- AI 辅助的故障排查与运维问答

## 核心特性

| 特性 | 说明 |
|------|------|
| 🏢 站点台账 | 多站点统一管理，运行状态监控、Zabbix 一键跳转 |
| 🔌 专线管理 | 合同到期预警、带宽 / 费用追踪、变更历史、故障记录（Incident）、钉钉/企微/飞书/邮件通知 |
| 🌐 IPAM | 子网 / IP 双层管理，CIDR 自动规范化，IP 自动发现扫描（TCP/ICMP/ARP），使用率可视化、冲突拦截 |
| 💻 设备台账 | 凭证加密存储、保修预警、LLDP / MAC 链路自动发现、机柜 U 位管理 |
| 💾 配置备份 | Netmiko 驱动的多厂商配置采集，定时任务、版本 Diff 对比、AI 配置审计 |
| 🗺️ 拓扑可视化 | 站点 / 设备双视图，基于 G6 5.x 的交互式拓扑，支持 PNG/JPG/PDF 导出 |
| 📊 运维 / 管理双看板 | 运维视图（设备在线、事件时间线、子网使用率、设备品牌分布、快捷操作）+ 管理视图（网络可用性、专线费用拆分、风险看板、故障汇总），按角色与权限呈现 |
| 🚨 预警中心 | 规则预警 + AI 异常检测双引擎，自适应告警基线（z-score + 突变检测）、告警静默、故障升级与自动恢复 |
| 🩺 智能巡检 | 快速 / 全量扫描、设备指纹变更检测、AI 二次研判结论写入巡检结果 |
| 📈 运营月报 | 自动生成 PDF 月报，支持定时推送到邮箱 / 钉钉 / 企微 / 飞书，签名直链免登录下载 |
| 📚 知识库 | Markdown + 可视化表格双模式编辑，分类 / 标签 / 全文检索，多格式导入导出，AI 助手 RAG 检索增强 |
| 🔄 变更管理 | 专线与配置备份变更的时间线 / 表格双视图，多维度筛选，CSV 导出 |
| 🤖 AI 助手 | 自然语言查询（知识库 RAG 增强）、备份配置审计、智能预测，聊天记录可审计 |
| 🔐 安全与合规 | JWT + RBAC 细粒度权限，OAuth2 / SAML SSO / LDAP，图形验证码 + 账号锁定，IP 白名单，全程审计日志 |
| 🌍 国际化 | 中英双语运行时切换 |
| 🎨 品牌定制 | 系统名称、标语、Logo 可配置，支持白标部署 |

## 技术栈

**前端**
- Vue 3.5 + TypeScript + Vite 5
- Element Plus（UI）/ ECharts（图表）/ AntV G6（拓扑）
- Pinia（状态）/ Vue Router / vue-i18n

**后端**
- FastAPI 0.104 + Python 3.11+
- SQLAlchemy 2.0（异步） + Alembic
- PostgreSQL（生产） / SQLite（开发）
- Redis（缓存，可选）
- Netmiko / Paramiko（设备连接）
- APScheduler（定时任务）
- ldap3（LDAP 认证）

**AI**
- 兼容 OpenAI / DeepSeek / 通义千问 / Claude / 本地 Ollama

## 快速开始

### 前置要求

- Node.js ≥ 22（前端构建）
- Python ≥ 3.11
- (可选) PostgreSQL ≥ 14、Redis ≥ 6

### 本地开发

> **注意**：后端默认端口 `8000`，前端默认端口 `5174`。如需修改请编辑 `scripts/dev.sh`（支持 `BE_PORT` / `FE_PORT` 环境变量覆盖）与 `frontend/vite.config.ts`。

```bash
# 1. 克隆仓库
git clone https://github.com/chris0213/cornerstone.git
cd cornerstone

# 2. 启动后端（新终端）
cd backend
cp .env.example .env      # 编辑 .env：至少修改 SECRET_KEY（≥32 字符，启动强制校验）、INITIAL_ADMIN_PASSWORD
python3.11 -m venv .venv  # 推荐使用与 Docker 一致的 3.11
source .venv/bin/activate # Windows: .venv\Scripts\activate
pip install poetry
poetry install            # 或: pip install -e . (需确保 pyproject.toml 依赖解析成功)

#   2a. 建表（唯一权威方式，禁止使用 Base.metadata.create_all）
alembic upgrade head
#   2b. 初始化种子数据（权限/角色/admin账号 + 演示数据）
python init_db.py
#   2c. 启动后端
uvicorn src.main:app --reload --port 8000

# 3. 启动前端（新终端）
cd ../frontend
npm install
npm run dev               # 开发服务器 http://localhost:5174
```

> 💡 也可以使用一键脚本 `./scripts/dev.sh start|stop|restart|status|logs`（自动完成端口预检、进程管理、日志聚合）。

访问：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5174 |
| 后端 API | http://localhost:8000 |
| API Swagger | http://localhost:8000/docs（仅 `DEBUG=true` 时开启，生产环境自动关闭） |

默认账号：`admin` / `INITIAL_ADMIN_PASSWORD` 中配置的密码。

---

### 🐳 Docker Compose 部署（生产推荐）

#### 架构说明

```
用户浏览器 → [宿主机 HTTP_PORT] → cornerstone-frontend (Nginx)
                                    ├─ 静态资源: /usr/share/nginx/html
                                    └─ /api/* 反代 → cornerstone-backend:8000 (容器内部)
cornerstone-postgres (PostgreSQL 16)
cornerstone-redis    (Redis 7, AOF持久化)
```

> **重要**：前端容器内的 Nginx 已正确配置 `X-Real-IP` 与 `X-Forwarded-For` 头，后端登录接口会优先读取这些头获取真实客户端 IP（详见「部署后验证 → 真实IP透传」一节）。

#### 部署步骤

```bash
# 1. 克隆仓库
git clone https://github.com/chris0213/cornerstone.git
cd cornerstone

# 2. 配置环境变量（至少修改带 change-me 的项）
cp .env.docker.example .env
vim .env
# 必填项:
#   POSTGRES_PASSWORD       数据库密码（强密码）
#   SECRET_KEY              JWT 签名密钥: `openssl rand -hex 32`（启动时强制校验 ≥32 字符，弱密钥拒绝启动）
#   INITIAL_ADMIN_PASSWORD  首次启动时 admin 账号的初始密码
#   REDIS_PASSWORD          Redis 访问密码: `openssl rand -hex 16`
#                           ⚠ 变更后必须 docker compose up -d 整栈重建——
#                           只重启 backend 会导致新旧 Redis 密码不一致（验证码等接口报 NOAUTH）
#   CORS_ORIGINS            改为你的域名或服务器公网IP，如 http://1.2.3.4,https://itsm.example.com
#   HTTP_PORT               宿主机暴露端口（默认80，若被占用可改为8080/8089）

# 3. 构建并启动（首次约 3~5 分钟）
docker compose up -d --build

# 4. 等待启动完成 + 健康检查
sleep 10
docker compose ps
# STATUS 全部显示 healthy 才算启动完成
```

启动流程（容器内自动执行，无需手动干预）：

```
cornerstone-backend 容器启动
  ├─ 等待 postgres 容器 ready (最多 60 秒)
  ├─ 执行 `alembic upgrade head`   ← 建表 / schema 迁移（唯一权威方式）
  ├─ 执行 `python init_db.py`      ← 初始化权限、角色、admin 账号、演示数据
  └─ 启动 uvicorn :8000
```

访问 `http://<服务器IP或域名>:<HTTP_PORT>`，使用 `admin` + `INITIAL_ADMIN_PASSWORD` 登录。

#### 常用运维命令

```bash
# ---- 日志 ----
docker compose logs -f backend    # 后端日志
docker compose logs -f frontend   # 前端 Nginx 访问/错误日志
docker compose logs -f --tail 200 # 所有服务近 200 行

# ---- 升级部署（代码有更新时）----
# ⚠️ 重要：如果服务器本地有未提交的改动（如 docker-entrypoint.sh 被本地修改），
#         git pull 会失败。解决方法：先丢弃本地改动，再拉取。
git status                         # 检查是否有本地修改
git checkout -- backend/docker-entrypoint.sh backend/src/ frontend/   # 丢弃冲突文件的本地改动
git pull origin main
docker compose build --no-cache backend frontend   # 无缓存重建，避免旧代码残留
docker compose up -d --force-recreate backend frontend # 强制重建容器

# ---- 启停 ----
docker compose stop                # 停止（保留容器）
docker compose start               # 再次启动
docker compose down                # 销毁容器（数据卷保留在 postgres_data / redis_data 中，下次启动数据不丢）

# ---- 数据备份 ----
# PostgreSQL 数据库（建议生产每日定时执行）
docker exec cornerstone-postgres pg_dump -U cornerstone cornerstone | gzip > cornerstone_db_$(date +%Y%m%d).sql.gz
# 备份文件（含配置备份）：备份任务输出到 backend_backups 卷，可通过以下方式查看
docker run --rm -v cornerstone_backend_backups:/data alpine ls -la /data
```

#### 部署后验证

```bash
# 1. 基础健康检查
curl -I http://<服务器IP>/healthz      # 前端 Nginx 健康检查 → 200
curl -s http://<服务器IP>/api/v1/auth/captcha | head -c 100   # API 连通性（返回二进制验证码图片）

# 2. 获取登录 Token 并调用业务接口（替换密码）
TOKEN=$(curl -s -X POST http://<服务器IP>/api/v1/auth/token \
  -d "username=admin&password=<你的ADMIN密码>" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
echo "Token 前30位: ${TOKEN:0:30}"
curl -s http://<服务器IP>/api/v1/logs/ -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(f'审计日志条数: {len(data)}')
print('最近3条:', [{'id':d['id'],'user':d['user'],'ip':d.get('ipAddress')} for d in data[:3]])
"

# 3. ✅ 真实 IP 透传验证（关键）
#    模拟外面有一层反代/CDN，带 X-Forwarded-For 头访问，
#    然后看审计日志里是否记录了模拟的真实IP而不是127.0.0.1
curl -s -X POST http://<服务器IP>/api/v1/auth/token \
  -H "X-Forwarded-For: 203.0.113.25, 10.0.0.1" \
  -d "username=admin&password=<你的ADMIN密码>" > /dev/null
#    再调用上面的审计日志接口，最新一条的 ip 字段应为 203.0.113.25
```

#### Nginx 配置验证与查看（frontend 容器内）

```bash
# 查看运行中的 Nginx 配置文件（项目自带 /etc/nginx/conf.d/cornerstone.conf）
docker exec cornerstone-frontend cat /etc/nginx/conf.d/cornerstone.conf

# 实时查看 Nginx access log（第一列就是客户端IP，用于核对来源IP透传）
docker logs -f cornerstone-frontend

# 进入容器重载配置（修改配置后使用）
docker exec cornerstone-frontend nginx -t   # 语法检查
docker exec cornerstone-frontend nginx -s reload
```

> 💡 项目自带的 Nginx 配置已包含 IP 透传（`frontend/nginx.conf` L46-47）。
> 如果你的架构是 **「宿主机 Nginx → cornerstone-frontend:Nginx」** 双层反代，**外层宿主机 Nginx 必须再加一次透传头**，否则最内层拿到的是外层 Nginx IP 而不是真实用户 IP。外层配置模板：
>
> ```nginx
> server {
>     listen 443 ssl http2;
>     server_name itsm.example.com;
>     ssl_certificate     /etc/ssl/certs/itsm.example.com.pem;
>     ssl_certificate_key /etc/ssl/private/itsm.example.com.key;
>
>     location / {
>         proxy_pass http://127.0.0.1:<HTTP_PORT>;   # HTTP_PORT 对应 .env 中的值
>         proxy_set_header Host              $host;
>         proxy_set_header X-Real-IP         $remote_addr;
>         proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
>         proxy_set_header X-Forwarded-Proto $scheme;
>         proxy_read_timeout 300s;
>     }
> }
> ```

#### 常见问题排查

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| cornerstone-backend 无限重启 `restarting` | 旧 Postgres 数据卷残留旧 schema，缺列导致崩溃 | 见项目 memory 中「服务器旧 postgres volume 残留恢复流程」 |
| 登录后审计日志「来源IP」显示 `127.0.0.1` 或服务器内网IP | 外层反代（宿主机 Nginx/CDN/负载均衡）未加 X-Forwarded-For 头 | 见上方「双层反代」配置模板 |
| 前端登录按钮无反应，控制台 `/captcha` ERR_ABORTED | 后端进程已退出 | `docker compose logs backend` 查看崩溃原因，`docker compose restart backend` |
| `docker compose pull/push` 失败报 `local changes` | 服务器上有未提交的文件被改（如 entrypoint） | `git checkout -- <冲突文件>` 后再 pull |
| PDF 报告里中文为方框 □ | 字体文件损坏/被 Docker volume 覆盖 | 不要将字体目录挂到 volume，字体文件必须放在容器内非 volume 目录 |
| 全新部署登录报 500 / auth 接口 500 | SECRET_KEY 为空或 PostgreSQL 未完成迁移 | 检查 `.env` 三项必填；`docker exec cornerstone-backend alembic current` 确认 migration 已到 head |
| 升级后 backend 起不来、日志报 `SECRET_KEY 必须设置且至少 32 个字符` | 旧版本 `.env` 的 SECRET_KEY 长度不足（新版启动强制校验） | `sed -i "s\|^SECRET_KEY=.*\|SECRET_KEY=$(openssl rand -hex 32)\|" .env` 后 `docker compose up -d backend`；⚠ 换密钥会使所有登录态失效 |
| 部署/改密后验证码接口 500、日志有 Redis `NOAUTH` | 只重建了 backend，Redis 容器还是旧配置（密码不一致） | `docker compose up -d --build` **整栈重建**，勿只 restart/重建单个容器 |
| 升级后首页时间线接口 500 | 后端镜像未更新到最新（旧镜像的时间绑定与 PG 类型不兼容） | `git pull && docker compose up -d --build backend`，确认 `docker compose ps` 的 Created 时间 |
| 管理页面标题重复（显示两次「运营月报」等） | 代码版本过旧（旧版本在页面内部再渲染了标题） | 升级到 main 分支最新 commit c8e4504 之后 |

---

## 功能模块

### 1. 仪表盘

**运维视图**（运维工程师首页）：

![运维视图](docs/images/readme/dashboard-engineer.png)

**管理视图**（IT负责人首页）：

![管理视图](docs/images/readme/dashboard-manager.png)

- **运维视图**：站点 / 设备在线 / IP 占用 / 备份 状态卡片（含数据更新时间）、事件时间线（状态变化驱动、可切换范围）、子网使用率、设备品牌分布、快捷操作（按权限显隐）
- **管理视图**：IT负责人专属看板 - 网络可用性（区分探测全失败/未探测）、专线月租费用（拆分合同内/已到期未续约）、未解决故障、即将到期事项（两级预警）、IT风险看板（含已逾期未续约置顶，可点击跳转）、专线费用趋势图、设备生命周期分布、本月故障汇总、运营月报
- **super_admin**：支持在两个视图之间自由切换，菜单按权限自动过滤

### 2. 站点管理

站点列表（位置、联系人、专线数、状态）、告警高亮、Zabbix 跳转、电话一键复制、CSV 导入导出。

### 3. 专线管理

合同到期预警、带宽 / 费用、运行状态、变更历史、详情页。

**专线到期告警**：系统每天自动检查30天内即将到期的专线，根据剩余天数自动判断告警级别（critical/warning/info），并通过钉钉、企业微信、飞书或邮件发送告警通知。用户确认告警后7天内不再重复发送。

![专线管理](docs/images/readme/circuits.png)

### 4. IPAM

子网展示、IP 分配 / 回收、使用率色块、冲突拦截、CSV 导入；支持按子网启用 **IP 自动发现扫描**（TCP 端口探测为主、ICMP/ARP 兜底），扫描结果自动入库并可在 IP 矩阵中查看在线状态。

![IP管理](docs/images/readme/ipam.png)

### 5. 设备台账

设备列表、管理 IP、凭证加密、保修预警、LLDP 链路自动发现；内置**机柜视图**（U 位分布、容量概览、设备上下架时间线）。

![设备台账](docs/images/readme/devices.png)

### 6. 配置备份

备份历史、手动 / 定时备份任务、配置查看 / 下载、最近版本 Diff、AI 配置审计。

![配置备份](docs/images/readme/backups.png)

### 7. 拓扑可视化

基于 AntV G6 的交互式拓扑可视化，支持多种布局、导出图片/PDF：

![网络拓扑](docs/images/readme/topology.png)

- **站点拓扑**：基于专线关系的全局站点视图
- **设备拓扑**：基于 LLDP 数据的物理链路视图
- **导出功能**：支持将拓扑图导出为 PNG、JPG、PDF 格式文件

### 8. 预警中心

![预警中心](docs/images/readme/alerts.png)

**规则预警**：IP / 专线 / 设备到期、备份失败、子网容量。

**AI 智能检测**：设备状态异常、专线连通性、备份成功率趋势、IP 池耗尽预测。

**自适应告警基线**：延迟 / 丢包类指标可从固定阈值切换为动态基线（z-score 离群判定 + 突变检测），减少误报；支持按规则静默告警。

### 9. 智能巡检

定期对设备 / 专线 / 子网进行健康检查并生成巡检报告；开启 AI 二次研判后，巡检发现的异常会调用大模型复核，结论写入巡检结果供运营报告引用。

### 10. 运营月报

一键生成 PDF 格式月度运营报告，包含封面设计、执行摘要、关键指标（网络可用性、专线费用、故障次数）、费用构成条形图、故障记录明细、下月重点关注事项；支持定时生成并推送，聊天渠道附带签名直链可免登录直接下载。

### 11. 知识库

面向运维团队的文档沉淀：Markdown 源码 + 可视化表格双模式编辑、实时预览，分类 / 标签 / 全文检索，支持 `.md` / `.docx` / `.xlsx` 等多格式导入导出；AI 助手回答操作类问题时优先检索已发布文章并注明来源。

![知识库](docs/images/readme/knowledge.png)

### 12. 变更管理

聚合专线字段变更与配置备份变更两类数据：时间线 / 表格双视图、按操作人 / 时间 / 对象多维度筛选、统计卡片与 CSV 导出，可与 IPAM / 专线详情互相跳转。

![变更管理](docs/images/readme/changes.png)

### 13. 系统管理

- **品牌设置**：系统中文名称、英文名称、标语、副标题可配置，适用于二次部署或品牌定制场景
- 用户 / 角色 / 权限管理（RBAC）
- **通知管理**：支持钉钉、企业微信、飞书机器人 Webhook 配置，以及邮件服务器配置。配置后自动接收专线到期、设备故障等告警通知
- 认证集成（OAuth2 / SAML SSO / LDAP）
- 日志设置（审计 / 登录日志保留策略、自动清理）
- AI 设置（模型 API Key 配置）
- 审计日志查询
- 安全设置（IP 白名单、会话策略）

![系统管理](docs/images/readme/system.png)

## 项目结构

```
cornerstone/
├── backend/                      # FastAPI 后端
│   ├── src/
│   │   ├── api/                  # API 路由
│   │   ├── models/               # SQLAlchemy ORM
│   │   ├── schemas/              # Pydantic Schema
│   │   ├── services/             # 业务服务（AI / 采集 / 监控）
│   │   ├── tasks/                # 定时任务
│   │   ├── utils/                # 工具
│   │   └── main.py               # 应用入口
│   ├── alembic/                  # 数据库迁移
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                     # Vue 3 前端
│   ├── src/
│   │   ├── api/                  # Axios 封装
│   │   ├── app/                  # 路由
│   │   ├── components/           # 通用组件
│   │   ├── features/             # 业务模块
│   │   ├── i18n/                 # 国际化
│   │   ├── locales/              # 中英文翻译
│   │   ├── store/                # Pinia
│   │   └── App.vue
│   └── package.json
├── docs/                         # 文档
├── LICENSE
└── README.md
```

## 认证与权限

- **认证**：JWT Bearer Token（默认 8 小时过期，可刷新）
- **登录**：用户名密码 + 图形验证码 / OAuth2 / SAML / LDAP
- **权限**：RBAC，按资源 + 操作（如 `sites:read`、`devices:write`）
- **审计**：所有写操作自动记录到 `audit_logs`

内置角色：

| 角色 | 权限范围 | 首页视图 |
|------|----------|---------|
| `super_admin` | 全部权限 | 可切换运维/管理视图 |
| `engineer` | IT运维工程师（所有业务模块读写） | 运维视图（操作型） |
| `viewer` | **IT负责人**（管理看板 + 专线/预警/日志只读） | 管理视图（统计型） |

**IT负责人（viewer）权限说明**：
- 仅查看管理层关心的数据，不接触技术运维细节
- 站点管理：隐藏专线数、操作按钮
- 设备台账：隐藏序列号、位置、管理IP、操作按钮
- 预警中心：仅显示合同到期、保修到期、专线故障三个Tab
- 审计日志：仅显示登录日志和高危操作

## 国际化

支持简体中文（`zh-CN`）与英文（`en-US`），可在导航栏右上角切换，选择后写入 `localStorage`。

翻译文件：[frontend/src/locales/](frontend/src/locales/)

## AI 能力

在「系统管理 → AI 设置」配置模型 API Key 后启用（API Key 加密存储、仅超管可管理；支持 OpenAI 兼容 / DeepSeek / 通义千问 / Claude / 本地 Ollama）：

| 能力 | 入口 | 说明 |
|------|------|------|
| 全局自然语言搜索 | 顶部 ⌘K | 「上海有哪些设备离线？」，操作类问题优先检索知识库并注明来源 |
| 配置备份审计 | 备份详情 | AI 检查配置安全风险（敏感信息外发防护） |
| 巡检 AI 二次研判 | 智能巡检 | 巡检异常自动复核，结论写入巡检结果 |
| 智能预测 | 预警中心 | 趋势预测 / 根因分析 |
| 智能问答 | 各模块 | 上下文感知的运维问答 |
| AI 聊天日志 | 系统管理 | 对话元数据可审计（模型 / 耗时 / 状态） |

## 部署

推荐生产环境使用 Docker Compose：

```bash
cp .env.docker.example .env
# 修改 .env 中的 POSTGRES_PASSWORD / SECRET_KEY / INITIAL_ADMIN_PASSWORD / CORS_ORIGINS
docker compose up -d --build
```

## License

[MIT License](LICENSE)
