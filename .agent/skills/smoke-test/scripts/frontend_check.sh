#!/usr/bin/env bash
set +e

echo "=========================================="
echo "  Frontend Page Smoke Check"
echo "=========================================="
echo ""

BASE_URL="${BASE_URL:-http://localhost:2026}"
DOC_PATH="${DOC_PATH:-/en/docs}"

# On auth-enabled deployments, verify protected routes with a session for an
# existing account. Account provisioning belongs to the operator.
COOKIE_JAR=""
trap 'if [ -n "$COOKIE_JAR" ]; then rm -f -- "$COOKIE_JAR"; fi' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

curl_get() {
    if [ -n "$COOKIE_JAR" ]; then
        # curl treats a cookie argument containing '=' as literal cookie data.
        curl -q --cookie - "$@" < "$COOKIE_JAR"
    else
        curl -q "$@"
    fi
}

authenticate() {
    local auth_check
    if ! auth_check=$(curl -q -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/models"); then
        echo "✗ Cannot reach ${BASE_URL} — is the service running?" >&2
        return 1
    fi
    case "$auth_check" in
        200)
            echo "ℹ Auth is disabled — no login needed"
            return 0
            ;;
        401) ;;
        *)
            echo "✗ Could not check authentication (HTTP $auth_check)" >&2
            return 1
            ;;
    esac

    if [ -z "${SMOKE_TEST_EMAIL:-}" ] || [ -z "${SMOKE_TEST_PASSWORD:-}" ]; then
        echo "✗ Set SMOKE_TEST_EMAIL and SMOKE_TEST_PASSWORD for an existing test account." >&2
        return 1
    fi
    if ! COOKIE_JAR=$(mktemp "${TMPDIR:-/tmp}/deerflow-smoke-cookies.XXXXXX"); then
        echo "✗ Could not create a temporary cookie jar" >&2
        return 1
    fi

    echo "🔐 Auth is enabled — signing in to the existing test account..."
    local login_code
    if ! login_code=$(printf '%s' "$SMOKE_TEST_PASSWORD" | curl -q -s -o /dev/null -w "%{http_code}" \
        "${BASE_URL}/api/v1/auth/login/local" \
        --data-urlencode "username=${SMOKE_TEST_EMAIL}" \
        --data-urlencode 'password@-' \
        --data-urlencode 'remember_me=false' \
        -c "$COOKIE_JAR") || [ "$login_code" != "200" ]; then
        echo "✗ Login failed (HTTP ${login_code:-unavailable}). Check the existing test account and finish setup first." >&2
        return 1
    fi

    local me_code
    if ! me_code=$(curl_get -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/auth/me") || [ "$me_code" != "200" ]; then
        echo "✗ Auth failed — session cookie not accepted (HTTP ${me_code:-unavailable})" >&2
        return 1
    fi

    echo "✓ Session verified"
}

all_passed=true

check_status() {
    local name="$1"
    local url="$2"
    local expected_re="$3"

    local status
    status="$(curl_get -s -o /dev/null -w "%{http_code}" -L "$url")"
    if echo "$status" | grep -Eq "$expected_re"; then
        echo "✓ $name ($url) -> $status"
    else
        echo "✗ $name ($url) -> $status (expected: $expected_re)"
        all_passed=false
    fi
}

check_final_url() {
    local name="$1"
    local url="$2"
    local expected_path_re="$3"

    local effective
    effective="$(curl_get -s -o /dev/null -w "%{url_effective}" -L "$url")"
    if echo "$effective" | grep -Eq "$expected_path_re"; then
        echo "✓ $name redirect target -> $effective"
    else
        echo "✗ $name redirect target -> $effective (expected path: $expected_path_re)"
        all_passed=false
    fi
}

# Authenticate before checking protected routes
authenticate || exit 1

echo ""
echo "1. Checking entry pages..."
check_status "Landing page" "${BASE_URL}/" "200"
check_status "Workspace redirect" "${BASE_URL}/workspace" "200|301|302|307|308"
check_final_url "Workspace redirect" "${BASE_URL}/workspace" "/workspace/chats/"
echo ""

echo "2. Checking key workspace routes..."
check_status "New chat page" "${BASE_URL}/workspace/chats/new" "200"
check_final_url "New chat page" "${BASE_URL}/workspace/chats/new" "/workspace/"
check_status "Chats list page" "${BASE_URL}/workspace/chats" "200"
check_final_url "Chats list page" "${BASE_URL}/workspace/chats" "/workspace/"
check_status "Agents gallery page" "${BASE_URL}/workspace/agents" "200"
check_final_url "Agents gallery page" "${BASE_URL}/workspace/agents" "/workspace/agents"
echo ""

echo "3. Checking docs route (optional)..."
check_status "Docs page" "${BASE_URL}${DOC_PATH}" "200|404"
echo ""

echo "=========================================="
echo "  Frontend Smoke Check Summary"
echo "=========================================="
echo ""
if [ "$all_passed" = true ]; then
    echo "✅ Frontend smoke checks passed!"
    exit 0
else
    echo "❌ Frontend smoke checks failed"
    exit 1
fi
