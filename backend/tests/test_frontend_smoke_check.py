"""Exercise the frontend smoke check without contacting a deployment."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

_SCRIPT = Path(__file__).resolve().parents[2] / ".agent/skills/smoke-test/scripts/frontend_check.sh"
_PRELUDE = r"""
has_session_cookie() {
    local cookie_source="$1"
    [ -f logged-in ] || return 1
    # curl treats a cookie argument containing '=' as literal cookie data.
    case "$cookie_source" in
        ""|*=*) return 1 ;;
        -) [ "$(cat)" = 'temporary session' ] ;;
        *) [ -f "$cookie_source" ] && [ "$(cat < "$cookie_source")" = 'temporary session' ] ;;
    esac
}
curl() {
    local arg endpoint write_format body cookie_output cookie_input i
    local sent_username=false
    local -a args=("$@")
    for (( i=0; i < ${#args[@]}; i++ )); do
        arg=${args[$i]}
        case "$arg" in
            http://fixture.invalid/*) endpoint=${arg#http://fixture.invalid} ;;
            -w) write_format=${args[$((i+1))]} ;;
            -c) cookie_output=${args[$((i+1))]} ;;
            -b|--cookie) cookie_input=${args[$((i+1))]} ;;
            --data-urlencode)
                if [ "${args[$((i+1))]}" = "username=$SMOKE_TEST_EMAIL" ]; then
                    sent_username=true
                fi
                ;;
        esac
    done
    printf '%s\n' "$endpoint" >> requests.log
    case "$endpoint" in
        /api/models) printf '%s' "$FAKE_AUTH_STATUS" ;;
        /api/v1/auth/login/local)
            body=$(cat)
            case " $* " in
                *" --data-urlencode password@- --data-urlencode remember_me=false "*) ;;
                *) return 1 ;;
            esac
            [ "$sent_username" = true ] && [ "$body" = "$SMOKE_TEST_PASSWORD" ] && [ -n "$cookie_output" ] || return 1
            printf 'temporary session' > "$cookie_output"
            if [ "$FAKE_LOGIN_STATUS" = 200 ]; then
                touch logged-in
            fi
            printf '%s' "$FAKE_LOGIN_STATUS"
            ;;
        /api/v1/auth/me)
            if has_session_cookie "$cookie_input"; then
                printf '200'
            else
                printf '401'
            fi
            ;;
        /workspace*)
            if [ "$FAKE_AUTH_STATUS" = 401 ]; then
                has_session_cookie "$cookie_input" || return 1
            fi
            if [ "$write_format" = '%{url_effective}' ]; then
                if [ "$endpoint" = /workspace ]; then
                    printf 'http://fixture.invalid/workspace/chats/new'
                else
                    printf 'http://fixture.invalid%s' "$endpoint"
                fi
            else
                printf '200'
            fi
            ;;
        /|/en/docs) printf '200' ;;
        *) return 1 ;;
    esac
}
export -f curl has_session_cookie
"$1" frontend_check.sh
"""


@pytest.mark.parametrize(
    ("auth_status", "login_status", "credentials", "exit_code", "attempts"),
    [
        ("200", "200", False, 0, []),
        ("401", "200", False, 1, []),
        ("401", "200", True, 0, ["/api/v1/auth/login/local", "/api/v1/auth/me"]),
        ("401", "401", True, 1, ["/api/v1/auth/login/local"]),
        ("503", "200", True, 1, []),
    ],
    ids=["anonymous", "missing-credentials", "existing-account", "rejected-login", "auth-probe-unavailable"],
)
def test_smoke_check_only_signs_in_to_existing_accounts(tmp_path, auth_status, login_status, credentials, exit_code, attempts):
    bash = require_script_bash()
    shutil.copy2(_SCRIPT, tmp_path / "frontend_check.sh")
    scratch = tmp_path / "cookie scratch=local"
    scratch.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV", "SMOKE_TEST_EMAIL", "SMOKE_TEST_PASSWORD"}}
    env.update(BASE_URL="http://fixture.invalid", DOC_PATH="/en/docs", TMPDIR=f"./{scratch.name}", FAKE_AUTH_STATUS=auth_status, FAKE_LOGIN_STATUS=login_status)
    if credentials:
        env.update(SMOKE_TEST_EMAIL="tester@example.invalid", SMOKE_TEST_PASSWORD="fixture only: q+%")
    result = subprocess.run([bash, "-c", _PRELUDE, "smoke-check-test", bash], cwd=tmp_path, env=env, capture_output=True, encoding="utf-8", check=False, timeout=20)
    calls = (tmp_path / "requests.log").read_text(encoding="utf-8").splitlines()
    assert [path for path in calls if path.startswith("/api/v1/auth/")] == attempts
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert ("/workspace/chats/new" in calls) == (exit_code == 0)
    assert not list(scratch.iterdir())
    if credentials:
        assert env["SMOKE_TEST_PASSWORD"] not in result.stdout + result.stderr
