#!/bin/bash
# Start MCP test servers

echo "Starting weather server on port 18001..."
cd /root/code/deer-flow/backend
setsid uv run python ../tests/mcp_test/weather_server.py > /tmp/weather_server.log 2>&1 &
WEATHER_PID=$!
echo "Weather server PID: $WEATHER_PID"

echo "Starting calculator server on port 18002..."
setsid uv run python ../tests/mcp_test/calculator_server.py > /tmp/calculator_server.log 2>&1 &
CALC_PID=$!
echo "Calculator server PID: $CALC_PID"

sleep 3

echo "Checking servers..."
if kill -0 $WEATHER_PID 2>/dev/null; then
    echo "Weather server is running"
else
    echo "Weather server failed to start"
    cat /tmp/weather_server.log
fi

if kill -0 $CALC_PID 2>/dev/null; then
    echo "Calculator server is running"
else
    echo "Calculator server failed to start"
    cat /tmp/calculator_server.log
fi

echo "PIDs: weather=$WEATHER_PID calculator=$CALC_PID"
