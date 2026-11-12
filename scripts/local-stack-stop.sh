#!/usr/bin/env bash
# =============================================================================
# 基石 Cornerstone — 本地常驻停止脚本
#
# 用法：
#   ./scripts/local-stack-stop.sh            按 PID 停掉 Redis + 后端 + 前端
#   ./scripts/local-stack-stop.sh status     仅查看状态
#
# 前置条件：无。脚本只处理 .local-stack/*.pid 里记录、且确实在监听对应端口的进程；
#           端口若被其他进程占用，只提示不终止。
#
# 可覆盖的环境变量：REDIS_PORT(6379) BE_PORT(8000) FE_PORT(5174)
# =============================================================================

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.local-stack"
LOG_DIR="$RUN_DIR/logs"

REDIS_PORT="${REDIS_PORT:-6379}"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="${FE_PORT:-5174}"

REDIS_PID_FILE="$RUN_DIR/redis.pid"
BE_PID_FILE="$RUN_DIR/backend.pid"
FE_PID_FILE="$RUN_DIR/frontend.pid"

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

port_pids() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1" (PID "$2")"; exit}'; }
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
read_pid() { [ -f "$1" ] && tr -d '[:space:]' < "$1"; }

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

kill_tree() {
  local pid="$1" sig="${2:-TERM}" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child" "$sig"; done
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

# stop_one <名称> <端口> <pidfile>
stop_one() {
  local name="$1" port="$2" pidfile="$3" pid
  pid="$(read_pid "$pidfile")"

  if [ -z "$pid" ] || ! pid_alive "$pid"; then
    if [ -n "$(port_pids "$port")" ]; then
      warn "${name}：端口 $port 有进程在监听（$(port_owner "$port")），但不属于本脚本，未处理"
    else
      ok "${name}：未在运行"
    fi
    rm -f "$pidfile"
    return 0
  fi

  if ! port_belongs_to "$port" "$pid"; then
    warn "${name}：PID $pid 未监听端口 $port（可能已退出），跳过终止"
    rm -f "$pidfile"
    return 0
  fi

  kill_tree "$pid" TERM
  if wait_port_free "$port" 10; then
    ok "${name}：已停止 (PID $pid)"
  else
    warn "${name}：优雅退出超时，强制结束"
    kill_tree "$pid" KILL
    sleep 1
    if wait_port_free "$port" 3; then
      ok "${name}：已强制停止"
    else
      err "${name}：端口 $port 仍被占用，请手动检查"
      return 1
    fi
  fi
  rm -f "$pidfile"
  return 0
}

show_status() {
  title "服务状态"
  printf '  %-10s %-6s %-16s %s\n' "服务" "端口" "本脚本进程" "端口占用"
  local name port pidfile pid
  for spec in "Redis:$REDIS_PORT:$REDIS_PID_FILE" "backend:$BE_PORT:$BE_PID_FILE" "frontend:$FE_PORT:$FE_PID_FILE"; do
    name="${spec%%:*}"; spec="${spec#*:}"; port="${spec%%:*}"; pidfile="${spec#*:}"
    pid="$(read_pid "$pidfile")"
    if pid_alive "$pid" && port_belongs_to "$port" "$pid"; then
      printf '  %-10s %-6s %-16s %s\n' "$name" "$port" "运行中 (PID $pid)" "-"
    else
      printf '  %-10s %-6s %-16s %s\n' "$name" "$port" "未运行" "$(port_owner "$port" || true)"
    fi
  done
  echo
  info "日志目录：$LOG_DIR"
}

main() {
  local cmd="${1:-stop}"
  case "$cmd" in
    stop)
      local rc=0
      # 先停前端，再停后端，最后 Redis
      stop_one "前端" "$FE_PORT" "$FE_PID_FILE" || rc=1
      stop_one "后端" "$BE_PORT" "$BE_PID_FILE" || rc=1
      stop_one "Redis" "$REDIS_PORT" "$REDIS_PID_FILE" || rc=1
      echo
      [ "$rc" -eq 0 ] && ok "收尾完成" || warn "部分服务未正常停止，见上方提示"
      return "$rc"
      ;;
    status) show_status ;;
    help|-h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) err "未知命令：$cmd（可用：stop | status | help）"; return 1 ;;
  esac
}

main "$@"
