#!/usr/bin/env bash
# Usage: ./scripts/daemonize.sh "command to run" /tmp/logfile.log
# Starts a command in a fully detached session: new SID, redirected stdin/stdout/stderr.
# The calling shell returns immediately because no file descriptors are shared.
set -e

COMMAND="$1"
LOGFILE="${2:-/tmp/daemon.log}"

# Create log dir if needed
mkdir -p "$(dirname "$LOGFILE")"

# setsid: new session (escapes bash tool's process group kill)
# </dev/null: detach stdin (prevents bash tool from waiting on input pipe)
# > logfile 2>&1: redirect stdout+stderr (closes the pipe so bash tool returns)
setsid bash -c "$COMMAND" </dev/null > "$LOGFILE" 2>&1 &

PID=$!
echo "Started PID $PID, logs at $LOGFILE"
