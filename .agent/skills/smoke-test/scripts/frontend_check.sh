#!/usr/bin/env bash
set +e

echo "=========================================="
echo "  Frontend Page Smoke Check"
echo "=========================================="
echo ""

BASE_URL="${BASE_URL:-http://localhost:2026}"
DOC_PATH="${DOC_PATH:-/en/docs}"

# When the gateway has authentication enabled (DEER_FLOW_AUTH_DISABLED != 1),
# protected /workspace/* routes redirect anonymous requests to /login.
# We detect auth, register / log in a smoke-test user, and pass the session
# cookie to all curl calls so the real pages are verified, not the login form.
SMOKE_TEST_EMAIL="${SMOKE_TEST_EMAIL:-smoke-test@deerflow.dev}"
SMOKE_TEST_PASSWORD="${SMOKE_TEST_PASSWORD:-SmokeTest123!}"
COOKIE_JAR=$(mktemp /tmp/deerflow-smoke-cookies.XXXXXX)
trap 'rm -f "$COOKIE_JAR"' EXIT
CURL_AUTH_OPTS=""

authenticate() {
    # Make sure the service is reachable before detecting auth
    local health
    health=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/" 2>/dev/null)
    if [ "$health" = "000" ]; then
        echo "✗ Cannot reach ${BASE_URL} — is the service running?"
        return 1
    fi

    # A protected endpoint returns 401 when auth is on
    local auth_check
    auth_check=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/models" 2>/dev/null)
    if [ "$auth_check" != "401" ]; then
        echo "ℹ Auth is disabled — no login needed"
        return 0
    fi

    echo "🔐 Auth is enabled — setting up smoke test session..."

    # Check whether the system needs first-boot initialization
    local needs_setup
    needs_setup=$(curl -s "${BASE_URL}/api/v1/auth/setup-status" \
        | grep -o '"needs_setup":[^,}]*' | grep -o 'true\|false')
    if [ "$needs_setup" = "true" ]; then
        echo "  Initializing system with smoke test admin..."
        local init_code
        init_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "${BASE_URL}/api/v1/auth/initialize" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"${SMOKE_TEST_EMAIL}\",\"password\":\"${SMOKE_TEST_PASSWORD}\"}" \
            -c "$COOKIE_JAR" 2>/dev/null)
        if [ "$init_code" != "201" ]; then
            echo "✗ Initialize failed (HTTP $init_code)"
            return 1
        fi
        echo "✓ Admin initialized & logged in"
    elif [ -z "$needs_setup" ]; then
        echo "⚠ Could not determine setup status — skipping initialize, trying register/login"
    else
        # Register first — on success (201) it also auto-logs-in via the cookie.
        # This avoids a wasted login attempt that counts toward rate-limiting.
        local auth_code
        auth_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "${BASE_URL}/api/v1/auth/register" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"${SMOKE_TEST_EMAIL}\",\"password\":\"${SMOKE_TEST_PASSWORD}\"}" \
            -c "$COOKIE_JAR" 2>/dev/null)

        if [ "$auth_code" = "201" ]; then
            echo "✓ Registered as ${SMOKE_TEST_EMAIL}"
        else
            # User already exists — clear stale cookies from register attempt, then log in
            : > "$COOKIE_JAR"
            local login_code
            login_code=$(curl -s -o /dev/null -w "%{http_code}" \
                -X POST "${BASE_URL}/api/v1/auth/login/local" \
                --data-urlencode "username=${SMOKE_TEST_EMAIL}" \
                --data-urlencode "password=${SMOKE_TEST_PASSWORD}" \
                -c "$COOKIE_JAR" 2>/dev/null)
            if [ "$login_code" != "200" ]; then
                echo "✗ Login failed (HTTP $login_code)"
                return 1
            fi
            echo "✓ Logged in as ${SMOKE_TEST_EMAIL}"
        fi
    fi

    # Verify the session cookie works across all branches
    local me_code
    me_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -b "$COOKIE_JAR" "${BASE_URL}/api/v1/auth/me" 2>/dev/null)

    if [ "$me_code" = "200" ]; then
        echo "✓ Session verified for ${SMOKE_TEST_EMAIL}"
        CURL_AUTH_OPTS="-b $COOKIE_JAR"
        return 0
    fi

    echo "✗ Auth failed — session cookie not accepted (HTTP $me_code)"
    echo "  Set SMOKE_TEST_EMAIL / SMOKE_TEST_PASSWORD or check the existing account"
    return 1
}

all_passed=true

check_status() {
    local name="$1"
    local url="$2"
    local expected_re="$3"

    local status
    status="$(curl -s -o /dev/null -w "%{http_code}" -L ${CURL_AUTH_OPTS} "$url")"
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
    effective="$(curl -s -o /dev/null -w "%{url_effective}" -L ${CURL_AUTH_OPTS} "$url")"
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
