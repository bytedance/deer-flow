#!/bin/bash
# DeerFlow Live Monitor
# Streams logs from all backend services continuously.
# Usage: ./improved-monitor.sh [--status]
#   (no args)  - live log stream (default)
#   --status   - one-shot container + API health snapshot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BLUE='\033[0;34m'; MAGENTA='\033[0;35m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ── one-shot status snapshot ───────────────────────────────────────────────────
show_status() {
    echo ""
    echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║       DeerFlow — Service Status       ║${NC}"
    echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
    echo -e "${DIM}$(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo ""

    echo -e "${BOLD}Containers${NC}"
    docker ps --filter "name=deer-flow" \
        --format "  {{.Names}}\t{{.Status}}" 2>/dev/null \
    | awk -F'\t' '{
        status = $2
        icon = (status ~ /^Up/) ? "✅" : "❌"
        printf "  %s  %-30s %s\n", icon, $1, status
    }'
    echo ""

    echo -e "${BOLD}API Health${NC}"
    for endpoint in \
        "Gateway|http://localhost:2026/api/health" \
        "LangGraph|http://localhost:2026/api/langgraph/ok" \
        "Models|http://localhost:2026/api/models"; do
        label="${endpoint%%|*}"
        url="${endpoint##*|}"
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null)
        if [ "$code" = "200" ]; then
            echo -e "  ✅  ${label} (${DIM}${code}${NC})"
        else
            echo -e "  ❌  ${label} (${DIM}${code:-timeout}${NC})"
        fi
    done
    echo ""
}

# ── live log stream ─────────────────────────────────────────────────────────────
stream_logs() {
    show_status

    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  Live Log Stream   ${DIM}(Ctrl+C to exit)${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Colour-code lines by service and content
    colorize() {
        local svc="$1"
        while IFS= read -r line; do
            # service prefix colour
            case "$svc" in
                langgraph) prefix="${CYAN}[langgraph]${NC} " ;;
                gateway)   prefix="${BLUE}[gateway]  ${NC} " ;;
                frontend)  prefix="${MAGENTA}[frontend] ${NC} " ;;
                *)         prefix="${DIM}[${svc}]${NC} " ;;
            esac

            # highlight errors / warnings / thinking in the line itself
            if echo "$line" | grep -qiE "error|exception|traceback|failed|critical"; then
                echo -e "${prefix}${RED}${line}${NC}"
            elif echo "$line" | grep -qiE "warning|warn"; then
                echo -e "${prefix}${YELLOW}${line}${NC}"
            elif echo "$line" | grep -qiE "thinking|<think|tool_call|invoke|Starting|completed|run started"; then
                echo -e "${prefix}${GREEN}${line}${NC}"
            elif echo "$line" | grep -qiE "info"; then
                echo -e "${prefix}${DIM}${line}${NC}"
            else
                echo -e "${prefix}${line}"
            fi
        done
    }

    # Stream all three log files simultaneously; label each line with its source.
    # Use process substitution so all three tail -f run in parallel.
    {
        tail -f "${SCRIPT_DIR}/logs/langgraph.log" 2>/dev/null | colorize langgraph &
        tail -f "${SCRIPT_DIR}/logs/gateway.log"   2>/dev/null | colorize gateway   &
        tail -f "${SCRIPT_DIR}/logs/frontend.log"  2>/dev/null | colorize frontend  &
        wait
    }
}

# ── entrypoint ─────────────────────────────────────────────────────────────────
case "${1:-}" in
    --status|-s)
        show_status
        ;;
    *)
        stream_logs
        ;;
esac
