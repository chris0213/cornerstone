#!/usr/bin/env bash
# =============================================================================
# 基石 Cornerstone — 本地常驻启动脚本（不用 Docker，直接跑本机进程）
#
# 用法：
#   ./scripts/local-stack-start.sh          拉起 Redis + 后端 + 前端（幂等）
#   ./scripts/local-stack-start.sh status   仅查看状态，不启动
#
# 停止：./scripts/local-stack-stop.sh
#
# 前置条件：
#   1. 后端虚拟环境：backend/.venv（存在 .venv/bin/python 即可，依赖已装）
#   2. 前端依赖：frontend/node_modules（含 vite）
#   3. Node.js：优先 $NODE_BIN，其次 PATH 里的 node。
#      本机无全局 node 时，脚本会兜底查找 AI 工具自带的 Node 运行时
#      （路径含随机 generation 目录，属临时路径，换机器请用 NODE_BIN 指定）
#   4. Redis 可执行文件：优先 $REDIS_SERVER_BIN，其次项目内本地编译产物
#      （2026-11-11/login-page-check/work/redis-7.4.2/src/redis-server），
#      最后尝试 PATH 里的 redis-server。也可 brew install redis 后用 PATH 方式。
#
# 可覆盖的环境变量：
#   REDIS_PORT(6379) BE_PORT(8000) FE_PORT(5174)
#   REDIS_SERVER_BIN NODE_BIN
#
# 产物目录（统一）：<项目根>/.local-stack/
#   logs/redis.log logs/backend.log logs/frontend.log
#   redis.pid backend.pid frontend.pid
#
# 幂等策略：
#   - 已由本脚本启动且存活的服务：跳过，不重复启动
#   - 端口被「非本脚本」的进程占用：只告警并跳过该项，绝不杀别人进程
# =============================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# 路径（全部基于脚本自身位置解析，不依赖当前工作目录）
# ---------------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.local-stack"
LOG_DIR="$RUN_DIR/logs"

# 端口：与 frontend/vite.config.ts 的 server.port / proxy.target 保持一致
REDIS_PORT="${REDIS_PORT:-6379}"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="${FE_PORT:-5174}"

# 后端虚拟环境解释器（同时用于后台进程脱离会话）
BE_PY="$BACKEND_DIR/.venv/bin/python"
BE_APP="src.main:app"

# 项目内本地编译的 Redis（相对项目根，不写死本机绝对路径）
LOCAL_REDIS_BIN="$ROOT_DIR/2026-11-11/login-page-check/work/redis-7.4.2/src/redis-server"

REDIS_PID_FILE="$RUN_DIR/redis.pid"
BE_PID_FILE="$RUN_DIR/backend.pid"
FE_PID_FILE="$RUN_DIR/frontend.pid"
REDIS_LOG="$LOG_DIR/redis.log"
BE_LOG="$LOG_DIR/backend.log"
FE_LOG="$LOG_DIR/frontend.log"

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_DIM=$'\033[2m';  C_BLD=$'\033[1m';  C_RST=$'\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_DIM=''; C_BLD=''; C_RST=''
fi
info()  { printf '%s[info]%s  %s\n' "$C_DIM" "$C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s  %s\n' "$C_GRN" "$C_RST" "$*"; }
skip()  { printf '%s[skip]%s  %s\n' "$C_YEL" "$C_RST" "$*"; }
warn()  { printf '%s[warn]%s  %s\n' "$C_YEL" "$C_RST" "$*"; }
err()   { printf '%s[fail]%s  %s\n' "$C_RED" "$C_RST" "$*" >&2; }
title() { printf '\n%s%s%s\n' "$C_BLD" "$*" "$C_RST"; }

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
port_pids() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1" (PID "$2")"; exit}'; }
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
read_pid() { [ -f "$1" ] && tr -d '[:space:]' < "$1"; }

# 进程族（父 + 所有后代）：uvicorn/vite 可能由子进程真正监听端口
pid_family() {
  local pid="$1" child
  [ -n "$pid" ] || return 0
  printf '%s\n' "$pid"
  for child in $(pgrep -P "$pid" 2>/dev/null); do pid_family "$child"; done
}

port_belongs_to() {
  local port="$1" pid="$2" fam p
  [ -n "$pid" ] || return 1
  fam="$(pid_family "$pid")"
  [ -n "$fam" ] || return 1
  for p in $(port_pids "$port"); do
    printf '%s\n' "$fam" | grep -qx "$p" && return 0
  done
  return 1
}

wait_port_up() {
  local port="$1" i
  for i in $(seq 1 "${2:-20}"); do
    [ -n "$(port_pids "$port")" ] && return 0
    sleep 1
  done
  return 1
}

wait_http() {
  local url="$1" expect="${2:-200}" tries="${3:-30}" i code
  for i in $(seq 1 "$tries"); do
    code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || true)"
    [ "$code" = "$expect" ] && return 0
    sleep 1
  done
  return 1
}

# ---------------------------------------------------------------------------
# 脱离会话启动
# 普通 nohup 仍留在当前会话，终端/上层工具回收进程组时会一起带走。
# 这里用 fork + setsid 让服务脱离启动者生命周期，并拿到真实 PID。
# ---------------------------------------------------------------------------
DETACH_PY=""
detect_detach_py() {
  local c
  for c in "$BE_PY" "${DETACH_PYTHON:-}" python3 /usr/bin/python3; do
    if [ -n "$c" ] && [ -x "$c" ]; then DETACH_PY="$c"; return 0; fi
  done
  return 1
}

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

start_detached() {
  local pidfile="$1" workdir="$2" logfile="$3"; shift 3
  local pid=""
  if [ -n "$DETACH_PY" ]; then
    pid="$(launch_detached "$workdir" "$logfile" "$@" 2>>"$logfile")"
  fi
  if [ -z "$pid" ]; then
    ( cd "$workdir" || exit 1; exec nohup "$@" >> "$logfile" 2>&1 ) &
    pid=$!
  fi
  printf '%s\n' "$pid" > "$pidfile"
}

# ---------------------------------------------------------------------------
# 依赖探测
# ---------------------------------------------------------------------------
REDIS_BIN=""
detect_redis_bin() {
  local c
  for c in "${REDIS_SERVER_BIN:-}" "$LOCAL_REDIS_BIN" "$(command -v redis-server 2>/dev/null || true)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then REDIS_BIN="$c"; return 0; fi
  done
  return 1
}

NODE_BIN=""
detect_node_bin() {
  local c
  # 1) 显式指定 2) PATH
  for c in "${NODE_BIN:-}" "$(command -v node 2>/dev/null || true)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then NODE_BIN="$c"; return 0; fi
  done
  # 3) 兜底：AI 工具自带的 Node 运行时（临时路径，仅供本机无全局 node 时使用）
  for c in "/Users/pancq/Library/Application Support/Codex/artifact-sessions/runtime-generations/"*/runtime/bin/node; do
    if [ -x "$c" ]; then NODE_BIN="$c"; return 0; fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
redis_ping() {
  "$DETACH_PY" - "$1" <<'PYEOF' 2>/dev/null
import socket, sys
port = int(sys.argv[1])
try:
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    s.sendall(b"PING\r\n")
    print(s.recv(64).decode(errors="ignore").strip())
except Exception:
    pass
PYEOF
}

start_redis() {
  title "Redis (:$REDIS_PORT)"
  if ! detect_redis_bin; then
    err "找不到 redis-server 可执行文件"
    info "可用 REDIS_SERVER_BIN=/path/to/redis-server 指定，或 brew install redis"
    return 1
  fi

  local pid
  pid="$(read_pid "$REDIS_PID_FILE")"
  if pid_alive "$pid" && port_belongs_to "$REDIS_PORT" "$pid"; then
    skip "Redis 已在运行 (PID $pid)"
    return 0
  fi
  rm -f "$REDIS_PID_FILE"

  if [ -n "$(port_pids "$REDIS_PORT")" ]; then
    skip "端口 $REDIS_PORT 已被其他进程占用（$(port_owner "$REDIS_PORT")），不重复启动，也不会终止它"
    return 0
  fi

  # 关闭落盘：Redis 在本项目只承担验证码/短期缓存，无需持久化
  start_detached "$REDIS_PID_FILE" "$RUN_DIR" "$REDIS_LOG" \
    "$REDIS_BIN" --port "$REDIS_PORT" --bind 127.0.0.1 \
    --dir "$RUN_DIR" --appendonly no --save ""

  pid="$(read_pid "$REDIS_PID_FILE")"
  sleep 1
  if ! pid_alive "$pid"; then
    err "Redis 启动失败，最近日志："
    tail -n 15 "$REDIS_LOG" >&2
    rm -f "$REDIS_PID_FILE"
    return 1
  fi
  if wait_port_up "$REDIS_PORT" 15; then
    local pong
    pong="$(redis_ping "$REDIS_PORT")"
    if [ "$pong" = "+PONG" ]; then
      ok "Redis 已就绪 127.0.0.1:$REDIS_PORT  (PID $pid)"
    else
      warn "Redis 端口已监听但 PING 无响应，请查看 $REDIS_LOG"
    fi
  else
    warn "Redis 进程已起 (PID $pid) 但端口未监听，请查看 $REDIS_LOG"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------
start_backend() {
  title "后端 uvicorn (:$BE_PORT)"

  if [ ! -x "$BE_PY" ]; then
    err "找不到后端虚拟环境解释器：$BE_PY"
    info "请先创建：cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ."
    return 1
  fi

  local pid
  pid="$(read_pid "$BE_PID_FILE")"
  if pid_alive "$pid" && port_belongs_to "$BE_PORT" "$pid"; then
    skip "后端已在运行 (PID $pid)"
    return 0
  fi
  rm -f "$BE_PID_FILE"

  if [ -n "$(port_pids "$BE_PORT")" ]; then
    skip "端口 $BE_PORT 已被其他进程占用（$(port_owner "$BE_PORT")），不重复启动，也不会终止它"
    return 0
  fi

  start_detached "$BE_PID_FILE" "$BACKEND_DIR" "$BE_LOG" \
    "$BE_PY" -m uvicorn "$BE_APP" --host 127.0.0.1 --port "$BE_PORT"

  pid="$(read_pid "$BE_PID_FILE")"
  sleep 2
  if ! pid_alive "$pid"; then
    err "后端启动失败，最近日志："
    tail -n 25 "$BE_LOG" >&2
    rm -f "$BE_PID_FILE"
    return 1
  fi
  wait_port_up "$BE_PORT" 30 || true
  if wait_http "http://127.0.0.1:$BE_PORT/docs" 200 30; then
    ok "后端已就绪 http://127.0.0.1:$BE_PORT/docs  (PID $pid)"
  else
    warn "后端进程已起 (PID $pid) 但 /docs 未就绪，请查看 $BE_LOG"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# 前端
# ---------------------------------------------------------------------------
start_frontend() {
  title "前端 Vite (:$FE_PORT)"

  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    err "前端依赖未安装：$FRONTEND_DIR/node_modules 不存在"
    info "请先执行：cd frontend && npm install"
    return 1
  fi
  if ! detect_node_bin; then
    err "找不到 node，可用 NODE_BIN=/path/to/node 指定"
    return 1
  fi

  local pid
  pid="$(read_pid "$FE_PID_FILE")"
  if pid_alive "$pid" && port_belongs_to "$FE_PORT" "$pid"; then
    skip "前端已在运行 (PID $pid)"
    return 0
  fi
  rm -f "$FE_PID_FILE"

  if [ -n "$(port_pids "$FE_PORT")" ]; then
    skip "端口 $FE_PORT 已被其他进程占用（$(port_owner "$FE_PORT")），不重复启动，也不会终止它"
    return 0
  fi

  # 直接用 node 跑 vite 入口：本机可能没有 npm，但 node + node_modules 足够
  start_detached "$FE_PID_FILE" "$FRONTEND_DIR" "$FE_LOG" \
    "$NODE_BIN" node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$FE_PORT" --strictPort

  pid="$(read_pid "$FE_PID_FILE")"
  sleep 2
  if ! pid_alive "$pid"; then
    err "前端启动失败，最近日志："
    tail -n 25 "$FE_LOG" >&2
    rm -f "$FE_PID_FILE"
    return 1
  fi
  # vite 冷启动需要预构建依赖，等待预算放宽到 60s
  wait_port_up "$FE_PORT" 60 || true
  if wait_http "http://127.0.0.1:$FE_PORT/login" 200 60; then
    ok "前端已就绪 http://127.0.0.1:$FE_PORT/login  (PID $pid)"
  else
    warn "前端进程已起 (PID $pid) 但 /login 未就绪，请查看 $FE_LOG"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# 状态汇总
# ---------------------------------------------------------------------------
row() {
  local name="$1" port="$2" pidfile="$3" log="$4" health="$5" probe="${6:-http}"
  local pid pids owner state health_disp
  pid="$(read_pid "$pidfile")"
  pids="$(port_pids "$port")"
  owner="$(port_owner "$port")"

  if pid_alive "$pid" && port_belongs_to "$port" "$pid"; then
    state="${C_GRN}运行中${C_RST}  PID $pid"
  elif [ -n "$pids" ]; then
    state="${C_YEL}外部占用${C_RST}  $owner"
  else
    state="${C_RED}未运行${C_RST}"
  fi

  # Redis 不是 HTTP 服务，用 PING 探活；其余用 HTTP 状态码
  if [ "$probe" = "redis" ]; then
    health_disp="$(redis_ping "$port")"
  else
    health_disp="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 2 "$health" 2>/dev/null)"
  fi
  [ -n "$health_disp" ] || health_disp="-"

  printf '  %-10s %-6s %-28s %-12s %s\n' "$name" "$port" "$(printf '%b' "$state")" "$health_disp" "$log"
}

show_summary() {
  title "服务状态"
  printf '  %-10s %-6s %-28s %-12s %s\n' "服务" "端口" "状态" "健康检查" "日志"
  row "Redis" "$REDIS_PORT" "$REDIS_PID_FILE" "$REDIS_LOG" "" "redis"
  row "backend" "$BE_PORT" "$BE_PID_FILE" "$BE_LOG" "http://127.0.0.1:$BE_PORT/docs"
  row "frontend" "$FE_PORT" "$FE_PID_FILE" "$FE_LOG" "http://127.0.0.1:$FE_PORT/login"
  echo
  info "访问地址：登录页 http://127.0.0.1:$FE_PORT/login"
  info "接口地址：http://127.0.0.1:$BE_PORT/docs"
  info "日志目录：$LOG_DIR"
  info "PID 目录：$RUN_DIR"
  info "停止服务：$ROOT_DIR/scripts/local-stack-stop.sh"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
  local cmd="${1:-start}"
  detect_detach_py || { err "找不到可用的 python 解释器，无法后台启动（可设 DETACH_PYTHON）"; return 1; }
  mkdir -p "$LOG_DIR"

  case "$cmd" in
    start)
      local rc=0
      start_redis || rc=1
      start_backend || rc=1
      start_frontend || rc=1
      show_summary
      [ "$rc" -eq 0 ] || err "有服务启动失败，请按上面的日志路径排查"
      return "$rc"
      ;;
    status) show_summary ;;
    help|-h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      ;;
    *) err "未知命令：$cmd（可用：start | status | help）"; return 1 ;;
  esac
}

main "$@"
