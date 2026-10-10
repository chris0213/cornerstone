#!/usr/bin/env bash
# =============================================================================
# 基石 Cornerstone — 本地开发服务启停脚本
#
# 用法：
#   ./scripts/dev.sh start   [backend|frontend]   启动（默认全部）
#   ./scripts/dev.sh stop    [backend|frontend]   停止（默认全部）
#   ./scripts/dev.sh restart [backend|frontend]   重启
#   ./scripts/dev.sh status                       查看端口 / 进程 / 健康状态
#   ./scripts/dev.sh logs    [backend|frontend]   实时跟踪日志（默认 backend）
#   ./scripts/dev.sh ports                        扫描常用端口占用，排查冲突
#   ./scripts/dev.sh docker-up | docker-down      Docker Compose 整栈启停
#   ./scripts/dev.sh help                         帮助
#
# 端口可用环境变量覆盖：
#   BE_PORT=8010 FE_PORT=5200 ./scripts/dev.sh start
#
# 安全约定（重要）：
#   1. 启动前做端口预检。端口若被「非本脚本启动」的进程占用，只报错退出，
#      绝不会替你杀掉别人的服务。
#   2. 停止时只杀本脚本记录在 .dev/*.pid 里的进程族，且会二次校验该进程族确实
#      在监听目标端口，避免 PID 复用误杀。
# =============================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.dev"
LOG_DIR="$RUN_DIR/logs"

# 默认端口：后端 8000 与 frontend/vite.config.ts 里 proxy.target 保持一致
#           （另一个项目 AI Native ESP 也通过 8000 调基石接口，不要随意改动）
#           前端 5174 与 vite.config.ts 的 server.port 一致
DEFAULT_BE_PORT=8000
DEFAULT_FE_PORT=5174

# 记住用户是否显式传了端口（显式传入优先级最高）
BE_PORT_ENV="${BE_PORT:-}"
FE_PORT_ENV="${FE_PORT:-}"
BE_PORT="$DEFAULT_BE_PORT"
FE_PORT="$DEFAULT_FE_PORT"

# 实际使用的端口会写进状态文件：端口可能是运行时自动避让出来的，
# 不持久化的话，下一次 stop / status 就找不到真正的服务了
BE_PORT_FILE="$RUN_DIR/backend.port"
FE_PORT_FILE="$RUN_DIR/frontend.port"

BE_PY="$BACKEND_DIR/.venv/bin/python"
BE_PID_FILE="$RUN_DIR/backend.pid"
FE_PID_FILE="$RUN_DIR/frontend.pid"
BE_LOG="$LOG_DIR/backend.log"
FE_LOG="$LOG_DIR/frontend.log"

BE_APP="src.main:app"        # 后端 ASGI 应用，需以 backend 为工作目录
NPM_BIN="${NPM_BIN:-npm}"    # 前端包管理器

# ports 命令扫描的常用端口（基础设施与其它业务，选端口时避开）
SCAN_PORTS="22 80 443 3000 3306 33060 5000 5173 5174 5175 5432 5433 6379 8000 8001 8002 8080 8888 9000"

# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_DIM=$'\033[2m';  C_BLD=$'\033[1m';  C_RST=$'\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_DIM=''; C_BLD=''; C_RST=''
fi

info()  { printf '%s[info]%s  %s\n' "$C_DIM" "$C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s  %s\n' "$C_GRN" "$C_RST" "$*"; }
warn()  { printf '%s[warn]%s  %s\n' "$C_YEL" "$C_RST" "$*"; }
err()   { printf '%s[fail]%s  %s\n' "$C_RED" "$C_RST" "$*" >&2; }
title() { printf '\n%s%s%s\n' "$C_BLD" "$*" "$C_RST"; }

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

# 监听指定端口的 PID 列表（去重）
port_pids() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u
}

# 占用端口的进程描述（命令名 + PID）
port_owner() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null \
    | awk 'NR>1 {print $1" (PID "$2")"; exit}'
}

pid_alive() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

read_pid() {
  if [ -f "$1" ]; then tr -d '[:space:]' < "$1"; fi
}

# 打印进程族：自身 + 所有后代
# uvicorn --reload 与 npm run dev 都是「父进程拉起子进程、子进程真正监听端口」，
# 因此校验端口归属时必须看整个进程族，不能只看记录的 PID。
pid_family() {
  local pid="$1" child
  [ -n "$pid" ] || return 0
  printf '%s\n' "$pid"
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    pid_family "$child"
  done
}

# 端口上的监听者是否属于给定进程族
port_belongs_to() {
  local port="$1" pid="$2" fam p
  [ -n "$pid" ] || return 1
  fam="$(pid_family "$pid")"
  [ -n "$fam" ] || return 1
  for p in $(port_pids "$port"); do
    if printf '%s\n' "$fam" | grep -qx "$p"; then
      return 0
    fi
  done
  return 1
}

# 递归杀进程树（先子后父）
kill_tree() {
  local pid="$1" sig="${2:-TERM}" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child" "$sig"
  done
  kill -"$sig" "$pid" 2>/dev/null || true
}

wait_port_free() {
  local port="$1" i
  for i in $(seq 1 "${2:-10}"); do
    [ -z "$(port_pids "$port")" ] && return 0
    sleep 1
  done
  [ -z "$(port_pids "$port")" ]
}

wait_http() {
  local url="$1" expect="${2:-200}" tries="${3:-30}" i code
  for i in $(seq 1 "$tries"); do
    # --noproxy '*' 避免环境里的 HTTP_PROXY 把本地请求劫走，造成健康检查误判
    code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || true)"
    [ "$code" = "$expect" ] && return 0
    sleep 1
  done
  return 1
}

ensure_dirs() { mkdir -p "$RUN_DIR" "$LOG_DIR"; }

# ---------------------------------------------------------------------------
# 脱离会话启动
#
# 用普通 nohup ... & 启动的进程仍留在当前会话里：终端一关、或被上层工具
# （AI 工具 / CI / 沙箱）按进程组回收，服务就会跟着没。这里统一用新会话
# （setsid）拉起，让服务脱离启动者的生命周期，并准确拿到真实 PID。
# ---------------------------------------------------------------------------
DETACH_PY=""
detect_detach_py() {
  local c
  for c in "${DETACH_PYTHON:-}" "$BE_PY" python3 /usr/bin/python3 /opt/homebrew/bin/python3; do
    if [ -n "$c" ] && [ -x "$c" ]; then DETACH_PY="$c"; return 0; fi
  done
  return 1
}

# 用法：launch_detached <工作目录> <日志文件> <命令...>，标准输出为子进程 PID
launch_detached() {
  local workdir="$1" logfile="$2"; shift 2
  "$DETACH_PY" - "$workdir" "$logfile" "$@" <<'PYEOF'
import os, sys
workdir, logfile = sys.argv[1], sys.argv[2]
cmd = sys.argv[3:]
pid = os.fork()
if pid == 0:
    try:
        os.setsid()
        os.chdir(workdir)
        out = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(out, 1)
        os.dup2(out, 2)
        os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
        os.execvp(cmd[0], cmd)
    except Exception:
        os._exit(127)
else:
    os.waitpid(pid, os.WNOHANG)
    print(pid)
PYEOF
}

# 启动一个后台服务：优先脱离会话，拿不到 python 时退回普通 nohup
start_detached() {
  local pidfile="$1" workdir="$2" logfile="$3"; shift 3
  local pid=""
  if [ -n "$DETACH_PY" ]; then
    pid="$(launch_detached "$workdir" "$logfile" "$@" 2>>"$logfile")"
  fi
  if [ -z "$pid" ]; then
    # 退回方案：普通终端里同样有效，只是不会脱离会话
    (
      cd "$workdir" || exit 1
      exec nohup "$@" >> "$logfile" 2>&1
    ) &
    pid=$!
  fi
  printf '%s\n' "$pid" > "$pidfile"
}

# 解析本次要使用的端口
#   start  : 环境变量 > 默认值（不读取上次状态，保证每次启动都从默认端口开始试）
#   其它   : 环境变量 > 上次实际使用的端口 > 默认值
resolve_ports() {
  local mode="${1:-stop}" saved
  if [ -n "$BE_PORT_ENV" ]; then
    BE_PORT="$BE_PORT_ENV"
  elif [ "$mode" != "start" ] && [ -f "$BE_PORT_FILE" ]; then
    saved="$(tr -d '[:space:]' < "$BE_PORT_FILE")"
    if [ -n "$saved" ]; then BE_PORT="$saved"; else BE_PORT="$DEFAULT_BE_PORT"; fi
  else
    BE_PORT="$DEFAULT_BE_PORT"
  fi

  if [ -n "$FE_PORT_ENV" ]; then
    FE_PORT="$FE_PORT_ENV"
  elif [ "$mode" != "start" ] && [ -f "$FE_PORT_FILE" ]; then
    saved="$(tr -d '[:space:]' < "$FE_PORT_FILE")"
    if [ -n "$saved" ]; then FE_PORT="$saved"; else FE_PORT="$DEFAULT_FE_PORT"; fi
  else
    FE_PORT="$DEFAULT_FE_PORT"
  fi
}

# 端口预检：返回 0 可用 / 1 被外部进程占用，占用者写入 CONFLICT_OWNER
CONFLICT_OWNER=""
check_port_conflict() {
  local port="$1" pidfile="$2" mypid
  CONFLICT_OWNER=""
  [ -z "$(port_pids "$port")" ] && return 0
  mypid="$(read_pid "$pidfile")"
  if [ -n "$mypid" ] && pid_alive "$mypid" && port_belongs_to "$port" "$mypid"; then
    return 0
  fi
  CONFLICT_OWNER="$(port_owner "$port")"
  return 1
}

# 等待端口出现监听者
wait_port_up() {
  local port="$1" i
  for i in $(seq 1 "${2:-20}"); do
    [ -n "$(port_pids "$port")" ] && return 0
    sleep 1
  done
  return 1
}

# ---------------------------------------------------------------------------
# 依赖预检
# ---------------------------------------------------------------------------
preflight_deps_backend() {
  if [ ! -x "$BE_PY" ]; then
    err "找不到后端虚拟环境解释器：$BE_PY"
    info "请先创建：cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    return 1
  fi
  return 0
}

preflight_deps_frontend() {
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    err "前端依赖未安装：$FRONTEND_DIR/node_modules 不存在"
    info "请先执行：cd frontend && npm install"
    return 1
  fi
  if ! command -v "$NPM_BIN" >/dev/null 2>&1; then
    err "找不到 $NPM_BIN，请确认 Node.js 已安装并在 PATH 中"
    info "若使用非默认 Node，可指定：NPM_BIN=/path/to/npm ./scripts/dev.sh start"
    return 1
  fi
  return 0
}

# Redis 仅提示不阻断（本地开发用 SQLite，Redis 多用于缓存）
warn_if_redis_down() {
  local env_file="$BACKEND_DIR/.env" url port
  [ -f "$env_file" ] || return 0
  url="$(grep -E '^REDIS_URL=' "$env_file" 2>/dev/null | head -1 | cut -d= -f2-)"
  [ -z "$url" ] && return 0
  port="$(printf '%s' "$url" | sed -n 's|.*:\([0-9]\{2,\}\)/.*|\1|p')"
  [ -z "$port" ] && port=6379
  if [ -z "$(port_pids "$port")" ]; then
    warn "Redis 端口 $port 无监听（$url），缓存相关功能可能不可用，接口本身仍可启动"
  fi
}

# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------
start_backend() {
  title "启动后端 (uvicorn :$BE_PORT)"
  preflight_deps_backend || return 1

  if ! check_port_conflict "$BE_PORT" "$BE_PID_FILE"; then
    err "端口 $BE_PORT 已被占用：$CONFLICT_OWNER"
    info "本脚本不会替你终止它。可选做法："
    info "  1) 换端口启动：BE_PORT=8010 ./scripts/dev.sh start"
    info "     注意：后端换端口后，需同步 frontend/vite.config.ts 里 proxy['/api'].target"
    info "  2) 手动停掉占用者，或执行 ./scripts/dev.sh ports 查看占用详情"
    return 1
  fi

  local pid
  pid="$(read_pid "$BE_PID_FILE")"
  if [ -n "$pid" ] && pid_alive "$pid"; then
    ok "后端已在运行 (PID $pid)，跳过"
    return 0
  fi

  ensure_dirs
  : >> "$BE_LOG"
  start_detached "$BE_PID_FILE" "$BACKEND_DIR" "$BE_LOG" \
    "$BE_PY" -m uvicorn "$BE_APP" --host 0.0.0.0 --port "$BE_PORT" --reload

  pid="$(read_pid "$BE_PID_FILE")"
  sleep 1
  if ! pid_alive "$pid"; then
    err "后端启动失败，最近日志："
    tail -n 20 "$BE_LOG" >&2
    rm -f "$BE_PID_FILE" "$BE_PORT_FILE"
    return 1
  fi
  printf '%s\n' "$BE_PORT" > "$BE_PORT_FILE"
  wait_port_up "$BE_PORT" 25 || true

  if wait_http "http://localhost:$BE_PORT/docs" 200 30; then
    ok "后端已就绪  http://localhost:$BE_PORT/docs  (PID $pid)"
  else
    warn "后端进程已起 (PID $pid) 但 /docs 未就绪，请查看日志：$BE_LOG"
  fi
  warn_if_redis_down
  return 0
}

stop_backend() {
  title "停止后端 (:$BE_PORT)"
  local pid
  pid="$(read_pid "$BE_PID_FILE")"

  if [ -z "$pid" ] || ! pid_alive "$pid"; then
    if [ -n "$(port_pids "$BE_PORT")" ]; then
      warn "端口 $BE_PORT 仍有进程监听（$(port_owner "$BE_PORT")），但不是本脚本启动的，未做处理"
    else
      ok "后端未在运行"
    fi
    rm -f "$BE_PID_FILE" "$BE_PORT_FILE"
    return 0
  fi

  if ! port_belongs_to "$BE_PORT" "$pid"; then
    warn "PID $pid 及其子进程未监听 $BE_PORT，可能已不是本脚本的后端，跳过终止"
    rm -f "$BE_PID_FILE" "$BE_PORT_FILE"
    return 0
  fi

  kill_tree "$pid" TERM
  if wait_port_free "$BE_PORT" 10; then
    ok "后端已停止"
  else
    warn "优雅退出超时，强制结束"
    kill_tree "$pid" KILL
    sleep 1
    ok "后端已强制停止"
  fi
  rm -f "$BE_PID_FILE" "$BE_PORT_FILE"
  return 0
}

# ---------------------------------------------------------------------------
# 前端
# ---------------------------------------------------------------------------
# 从 FE_PORT 起向上找空闲端口，最多找 10 个
pick_fe_port() {
  local p="$FE_PORT" i
  for i in $(seq 1 10); do
    if [ -z "$(port_pids "$p")" ]; then
      printf '%s' "$p"
      return 0
    fi
    p=$((p + 1))
  done
  return 1
}

start_frontend() {
  preflight_deps_frontend || return 1

  # 前端端口可自动避让：vite 的 /api 代理是按路径转发的，换端口不影响接口
  if ! check_port_conflict "$FE_PORT" "$FE_PID_FILE"; then
    local alt
    alt="$(pick_fe_port)" || alt=""
    if [ -z "$alt" ]; then
      err "端口 $FE_PORT 及其后 10 个端口均被占用，放弃启动"
      return 1
    fi
    warn "端口 $FE_PORT 已被占用：$CONFLICT_OWNER"
    warn "自动改用空闲端口 $alt（不会终止占用者）"
    FE_PORT="$alt"
  fi

  title "启动前端 (vite :$FE_PORT)"

  local pid
  pid="$(read_pid "$FE_PID_FILE")"
  if [ -n "$pid" ] && pid_alive "$pid"; then
    ok "前端已在运行 (PID $pid)，跳过"
    return 0
  fi

  ensure_dirs
  : >> "$FE_LOG"
  start_detached "$FE_PID_FILE" "$FRONTEND_DIR" "$FE_LOG" \
    "$NPM_BIN" run dev -- --port "$FE_PORT" --strictPort

  pid="$(read_pid "$FE_PID_FILE")"
  sleep 2
  if ! pid_alive "$pid"; then
    err "前端启动失败，最近日志："
    tail -n 20 "$FE_LOG" >&2
    rm -f "$FE_PID_FILE" "$FE_PORT_FILE"
    return 1
  fi
  # vite 首次启动要预构建依赖，冷启动可能长达 40s 以上，等待预算给足
  printf '%s\n' "$FE_PORT" > "$FE_PORT_FILE"
  wait_port_up "$FE_PORT" 45 || true

  if wait_http "http://localhost:$FE_PORT/" 200 40; then
    ok "前端已就绪  http://localhost:$FE_PORT/  (PID $pid)"
  else
    warn "前端进程已起 (PID $pid) 但首页未就绪，请查看日志：$FE_LOG"
  fi

  if [ -n "$(port_pids "$BE_PORT")" ]; then
    info "接口代理：http://localhost:$FE_PORT/api  ->  http://localhost:$BE_PORT"
  else
    warn "后端端口 $BE_PORT 无监听，前端 /api 请求会失败，请先启动后端"
  fi
  return 0
}

stop_frontend() {
  title "停止前端 (:$FE_PORT)"
  local pid
  pid="$(read_pid "$FE_PID_FILE")"

  if [ -z "$pid" ] || ! pid_alive "$pid"; then
    if [ -n "$(port_pids "$FE_PORT")" ]; then
      warn "端口 $FE_PORT 仍有进程监听（$(port_owner "$FE_PORT")），但不是本脚本启动的，未做处理"
    else
      ok "前端未在运行"
    fi
    rm -f "$FE_PID_FILE" "$FE_PORT_FILE"
    return 0
  fi

  if ! port_belongs_to "$FE_PORT" "$pid"; then
    warn "PID $pid 及其子进程未监听 $FE_PORT，可能已不是本脚本的前端，跳过终止"
    rm -f "$FE_PID_FILE" "$FE_PORT_FILE"
    return 0
  fi

  kill_tree "$pid" TERM
  if wait_port_free "$FE_PORT" 10; then
    ok "前端已停止"
  else
    warn "优雅退出超时，强制结束"
    kill_tree "$pid" KILL
    sleep 1
    ok "前端已强制停止"
  fi
  rm -f "$FE_PID_FILE" "$FE_PORT_FILE"
  return 0
}

# ---------------------------------------------------------------------------
# status / logs / ports
# ---------------------------------------------------------------------------
show_status() {
  local name="$1" port="$2" pidfile="$3" log="$4" health="$5"
  local pid pids owner
  pid="$(read_pid "$pidfile")"
  pids="$(port_pids "$port")"
  owner="$(port_owner "$port")"

  printf '%s%s%s  端口 %s\n' "$C_BLD" "$name" "$C_RST" "$port"
  if [ -n "$pid" ] && pid_alive "$pid"; then
    printf '   本脚本实例 : %s运行中 (PID %s)%s\n' "$C_GRN" "$pid" "$C_RST"
  else
    printf '   本脚本实例 : %s未运行%s\n' "$C_DIM" "$C_RST"
  fi

  if [ -n "$pids" ]; then
    printf '   端口占用   : %s%s%s\n' "$C_YEL" "${owner:-未知进程}" "$C_RST"
    local code
    code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 2 "$health" 2>/dev/null || echo '-')"
    if [ "$code" = "200" ]; then
      printf '   健康检查   : %s200 OK%s  (%s)\n' "$C_GRN" "$C_RST" "$health"
    else
      printf '   健康检查   : %sHTTP %s%s  (%s)\n' "$C_YEL" "$code" "$C_RST" "$health"
    fi
  else
    printf '   端口占用   : %s空闲%s\n' "$C_DIM" "$C_RST"
  fi
  printf '   日志文件   : %s\n' "$log"
}

cmd_status() {
  title "服务状态"
  show_status "后端 backend" "$BE_PORT" "$BE_PID_FILE" "$BE_LOG" "http://localhost:$BE_PORT/docs"
  echo
  show_status "前端 frontend" "$FE_PORT" "$FE_PID_FILE" "$FE_LOG" "http://localhost:$FE_PORT/"
  echo
  info "若「端口占用」有值但「本脚本实例」为未运行，说明是外部进程占用，脚本不会动它。"
  if [ "$BE_PORT" != "$DEFAULT_BE_PORT" ] || [ "$FE_PORT" != "$DEFAULT_FE_PORT" ]; then
    info "注意：上次运行做过端口避让（后端 $BE_PORT / 前端 $FE_PORT），"
    info "      与默认端口（后端 $DEFAULT_BE_PORT / 前端 $DEFAULT_FE_PORT）不一致。"
  fi
}

cmd_logs() {
  local target="${1:-backend}"
  case "$target" in
    backend)  [ -f "$BE_LOG" ] || { err "暂无日志 $BE_LOG"; return 1; }; tail -f "$BE_LOG" ;;
    frontend) [ -f "$FE_LOG" ] || { err "暂无日志 $FE_LOG"; return 1; }; tail -f "$FE_LOG" ;;
    *) err "用法：dev.sh logs [backend|frontend]"; return 1 ;;
  esac
}

cmd_ports() {
  title "端口占用扫描"
  printf '  %-8s %-8s %s\n' "端口" "状态" "占用者"
  local p owner
  for p in $(printf '%s' "$SCAN_PORTS" | tr ' ' '\n' | sort -n | uniq); do
    owner="$(port_owner "$p")"
    if [ -n "$owner" ]; then
      printf '  %-8s %-8s %s\n' "$p" "占用" "$owner"
    else
      printf '  %-8s %-8s %s\n' "$p" "空闲" "-"
    fi
  done
  echo
  info "当前脚本使用：后端 $BE_PORT / 前端 $FE_PORT"
  info "换端口启动：BE_PORT=xxxx FE_PORT=yyyy ./scripts/dev.sh start"
}

# ---------------------------------------------------------------------------
# Docker Compose（可选）
# ---------------------------------------------------------------------------
cmd_docker_up() {
  title "Docker Compose 启动"
  if ! command -v docker >/dev/null 2>&1; then
    err "未找到 docker 命令"
    return 1
  fi
  if [ ! -f "$ROOT_DIR/.env" ]; then
    warn "未找到 $ROOT_DIR/.env，请先：cp .env.docker.example .env 并填写密码与 SECRET_KEY"
    return 1
  fi
  local http_port="${HTTP_PORT:-80}"
  if [ -n "$(port_pids "$http_port")" ]; then
    err "端口 $http_port 已被占用：$(port_owner "$http_port")"
    info "可换端口：HTTP_PORT=8080 ./scripts/dev.sh docker-up"
    return 1
  fi
  if [ -n "$(port_pids 8000)" ]; then
    err "端口 8000 已被占用（compose 会把后端映射到此端口）：$(port_owner 8000)"
    info "请先停止占用者：lsof -nP -iTCP:8000 -sTCP:LISTEN"
    return 1
  fi
  ( cd "$ROOT_DIR" && docker compose up -d --build )
}

cmd_docker_down() {
  title "Docker Compose 停止"
  ( cd "$ROOT_DIR" && docker compose down )
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
基石 Cornerstone — 本地开发服务启停脚本

  ./scripts/dev.sh start   [backend|frontend]   启动（默认全部）
  ./scripts/dev.sh stop    [backend|frontend]   停止（默认全部）
  ./scripts/dev.sh restart [backend|frontend]   重启
  ./scripts/dev.sh status                       查看端口 / 进程 / 健康状态
  ./scripts/dev.sh logs    [backend|frontend]   实时跟踪日志（默认 backend）
  ./scripts/dev.sh ports                        扫描常用端口占用，排查冲突
  ./scripts/dev.sh docker-up | docker-down      Docker Compose 整栈启停
  ./scripts/dev.sh help                         本帮助

端口覆盖：BE_PORT=8010 FE_PORT=5200 ./scripts/dev.sh start

默认端口：后端 8000（对应 vite proxy.target）、前端 5174（对应 vite server.port）
状态与日志目录：.dev/（PID 文件与 nohup 日志）
EOF
}

main() {
  local cmd="${1:-help}"
  shift || true
  local target="${1:-all}"
  local rc=0
  detect_detach_py || true

  case "$cmd" in
    start)
      resolve_ports "start"
      case "$target" in
        all)      start_backend || rc=1; start_frontend || rc=1 ;;
        backend)  start_backend || rc=1 ;;
        frontend) start_frontend || rc=1 ;;
        *) err "未知服务：$target（可选 backend / frontend / all）"; return 1 ;;
      esac
      [ "$rc" -eq 0 ] && echo && ok "完成。查看状态：./scripts/dev.sh status"
      ;;

    stop)
      resolve_ports "stop"
      case "$target" in
        all)      stop_backend; stop_frontend ;;
        backend)  stop_backend ;;
        frontend) stop_frontend ;;
        *) err "未知服务：$target（可选 backend / frontend / all）"; return 1 ;;
      esac
      ;;

    restart)
      resolve_ports "stop"
      case "$target" in
        all)      stop_backend; stop_frontend; start_backend || rc=1; start_frontend || rc=1 ;;
        backend)  stop_backend; start_backend || rc=1 ;;
        frontend) stop_frontend; start_frontend || rc=1 ;;
        *) err "未知服务：$target（可选 backend / frontend / all）"; return 1 ;;
      esac
      ;;

    status)      resolve_ports "stop"; cmd_status ;;
    logs)        cmd_logs "${1:-backend}" ;;
    ports)       resolve_ports "stop"; cmd_ports ;;
    docker-up)   cmd_docker_up ;;
    docker-down) cmd_docker_down ;;
    help|-h|--help) usage ;;
    *)
      err "未知命令：$cmd"
      echo
      usage
      return 1 ;;
  esac
  return "$rc"
}

main "$@"
