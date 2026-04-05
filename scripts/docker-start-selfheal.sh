#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose-dev.yaml"
PROJECT_NAME="deer-flow-dev"

# Keep compose env interpolation stable and reduce noisy warnings.
export DEER_FLOW_ROOT="${DEER_FLOW_ROOT:-$PROJECT_ROOT}"
export allow_blocking="${allow_blocking:-}"

log() {
  printf '[docker-selfheal] %s\n' "$*"
}

compose() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

http_ok() {
  local url="$1"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
  [ "$code" = "200" ]
}

all_running() {
  local status
  status="$(compose ps --services --filter status=running)"
  echo "$status" | grep -qx 'frontend' \
    && echo "$status" | grep -qx 'gateway' \
    && echo "$status" | grep -qx 'langgraph' \
    && echo "$status" | grep -qx 'nginx'
}

health_check() {
  all_running \
    && http_ok "http://localhost:2026/" \
    && http_ok "http://localhost:2026/health" \
    && http_ok "http://localhost:2026/api/models" \
    && http_ok "http://localhost:2026/api/langgraph/docs"
}

wait_health() {
  local attempts="${1:-20}"
  local sleep_sec="${2:-3}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if health_check; then
      return 0
    fi
    log "等待服务健康 (${i}/${attempts})..."
    sleep "$sleep_sec"
  done
  return 1
}

show_debug() {
  log "当前容器状态："
  compose ps || true
  log "gateway 最近日志："
  docker logs --tail 80 deer-flow-gateway || true
  log "langgraph 最近日志："
  docker logs --tail 80 deer-flow-langgraph || true
  log "nginx 最近日志："
  docker logs --tail 80 deer-flow-nginx || true
}

repair_soft() {
  log "执行轻修复：重建 gateway/langgraph + 重启 nginx"
  compose up -d --force-recreate gateway langgraph
  compose restart nginx
}

repair_deep() {
  log "执行深修复：下线并重建 venv volumes 后重启"
  compose down
  docker volume rm "${PROJECT_NAME}_gateway-venv" "${PROJECT_NAME}_langgraph-venv" 2>/dev/null || true
  (cd "$PROJECT_ROOT" && make docker-start)
  compose restart nginx
}

main() {
  log "启动 Docker 服务（make docker-start）"
  (cd "$PROJECT_ROOT" && make docker-start)

  if wait_health 20 3; then
    log "服务启动成功，健康检查通过。"
    exit 0
  fi

  repair_soft
  if wait_health 20 3; then
    log "轻修复后恢复成功。"
    exit 0
  fi

  repair_deep
  if wait_health 30 3; then
    log "深修复后恢复成功。"
    exit 0
  fi

  log "自动修复失败，请查看日志。"
  show_debug
  exit 1
}

main "$@"
