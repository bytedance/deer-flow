#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WAIT_SCRIPT="$REPO_ROOT/scripts/wait-for-port.sh"

TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

MOCK_BIN="$TMP_DIR/bin"
mkdir -p "$MOCK_BIN"

write_mock() {
    local name="$1"
    local body="$2"
    cat >"$MOCK_BIN/$name" <<EOF
#!/usr/bin/env bash
set -euo pipefail
$body
EOF
    chmod +x "$MOCK_BIN/$name"
}

assert_absent() {
    local path="$1"
    if [ -e "$path" ]; then
        echo "Expected '$path' to be absent"
        exit 1
    fi
}

assert_present() {
    local path="$1"
    if [ ! -e "$path" ]; then
        echo "Expected '$path' to be present"
        exit 1
    fi
}

DARWIN_LSOF_MARK="$TMP_DIR/darwin-lsof-called"
write_mock "uname" 'echo Darwin'
write_mock "curl" 'exit 0'
write_mock "ss" 'exit 1'
write_mock "netstat" 'exit 1'
write_mock "lsof" "touch \"$DARWIN_LSOF_MARK\"; exit 1"

PATH="$MOCK_BIN:$PATH" DEER_FLOW_WAIT_FOR_PORT_SINGLE_CHECK=1 bash "$WAIT_SCRIPT" 2024
assert_absent "$DARWIN_LSOF_MARK"

rm -f "$MOCK_BIN/uname" "$MOCK_BIN/curl" "$MOCK_BIN/lsof"

LINUX_LSOF_MARK="$TMP_DIR/linux-lsof-called"
write_mock "uname" 'echo Linux'
write_mock "ss" 'exit 1'
write_mock "netstat" 'exit 1'
write_mock "lsof" "touch \"$LINUX_LSOF_MARK\"; exit 0"

PATH="$MOCK_BIN:$PATH" DEER_FLOW_WAIT_FOR_PORT_SINGLE_CHECK=1 bash "$WAIT_SCRIPT" 2024
assert_present "$LINUX_LSOF_MARK"

echo "wait-for-port tests passed"
