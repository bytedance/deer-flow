#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Checking Docker Environment"
echo "=========================================="
echo ""

# Check whether Docker is installed
if command -v docker >/dev/null 2>&1; then
    echo "✓ Docker is installed"
    docker --version
else
    echo "✗ Docker is not installed"
    exit 1
fi
echo ""

# Check the Docker daemon
if docker info >/dev/null 2>&1; then
    echo "✓ Docker daemon is running normally"
else
    echo "✗ Docker daemon is not running"
    echo "  Please start Docker Desktop or the Docker service"
    exit 1
fi
echo ""

# Check Docker Compose
if docker compose version >/dev/null 2>&1; then
    echo "✓ Docker Compose is available"
    docker compose version
else
    echo "✗ Docker Compose is not available"
    exit 1
fi
echo ""

# Check port 2026
if ! command -v lsof >/dev/null 2>&1; then
    echo "✗ lsof is required to check whether port 2026 is available"
    exit 1
fi

port_2026_usage="$(lsof -nP -iTCP:2026 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$port_2026_usage" ]; then
    echo "⚠  Port 2026 is already in use"
    echo "  Occupying process:"
    echo "$port_2026_usage"

    deerflow_process_found=0
    while IFS= read -r pid; do
        if [ -z "$pid" ]; then
            continue
        fi

        process_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        case "$process_command" in
            *[Dd]eer[Ff]low*|*[Dd]eerflow*|*[Nn]ginx*deerflow*|*deerflow/*[Nn]ginx*)
                deerflow_process_found=1
                ;;
        esac
    done <<EOF
$(printf '%s\n' "$port_2026_usage" | awk 'NR > 1 {print $2}')
EOF

    if [ "$deerflow_process_found" -eq 1 ]; then
        echo "✓ Port 2026 is occupied by DeerFlow"
    else
        echo "✗ Port 2026 must be free before starting DeerFlow"
        exit 1
    fi
else
    echo "✓ Port 2026 is available"
fi
echo ""

echo "=========================================="
echo "  Docker Environment Check Complete"
echo "=========================================="
