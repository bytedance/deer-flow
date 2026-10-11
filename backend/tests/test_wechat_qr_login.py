"""Browser QR sessions are bounded, owner-scoped and never expose credentials."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.channels.wechat_qr_login import QRLoginError, WechatQRLogin


@pytest.fixture
def login():
    manager = WechatQRLogin()
    manager.request = AsyncMock(return_value={"qrcode": "private-poll-id", "qrcode_img_content": "https://example.com/scan"})
    return manager


@pytest.mark.asyncio
async def test_confirmation_applies_credentials_once_without_returning_them(login):
    session = await login.start("alice", {})
    assert "private-poll-id" not in str(session)
    login.request.return_value = {"status": "confirmed", "bot_token": "secret-token", "ilink_bot_id": "bot-1"}
    apply = AsyncMock(return_value={"provider": "wechat", "configured": True})
    result = await login.poll("alice", session["id"], apply)
    assert result["status"] == "confirmed"
    assert "secret-token" not in str(result)
    assert "bot_token" not in str(result)
    apply.assert_awaited_once_with({"bot_token": "secret-token", "ilink_bot_id": "bot-1"})
    assert await login.poll("alice", session["id"], apply) == result
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_owner_cannot_read_cancel_or_replace_pending_login(login):
    session = await login.start("alice", {})
    for action in [login.poll("bob", session["id"], AsyncMock()), login.cancel("bob", session["id"]), login.start("bob", {})]:
        with pytest.raises(QRLoginError):
            await action


@pytest.mark.asyncio
async def test_expiry_and_provider_timeout_do_not_apply_credentials(login):
    session = await login.start("alice", {})
    apply = AsyncMock()
    login.request.side_effect = httpx.ReadTimeout("sensitive URL")
    assert (await login.poll("alice", session["id"], apply))["status"] == "pending"
    login.session.expires_at = 0
    assert (await login.poll("alice", session["id"], apply))["status"] == "expired"
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_fences_late_confirmation(login):
    session = await login.start("alice", {})
    entered, release = asyncio.Event(), asyncio.Event()

    async def request(*args):
        entered.set()
        await release.wait()
        return {"status": "confirmed", "bot_token": "late-token"}

    login.request.side_effect = request
    apply = AsyncMock()
    poll = asyncio.create_task(login.poll("alice", session["id"], apply))
    await entered.wait()
    await login.cancel("alice", session["id"])
    release.set()
    with pytest.raises(QRLoginError):
        await poll
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_provider_response_and_missing_credentials(login):
    login.request.return_value = {"qrcode": "id"}
    with pytest.raises(QRLoginError):
        await login.start("alice", {})
    login.request.return_value = {"qrcode": "id", "qrcode_img_content": "scan"}
    session = await login.start("alice", {})
    login.request.return_value = {"status": "confirmed"}
    apply = AsyncMock()
    assert (await login.poll("alice", session["id"], apply))["status"] == "failed"
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_session_invalidates_old_and_manual_mutation_cancels(login):
    old = await login.start("alice", {})
    new = await login.start("alice", {})
    with pytest.raises(QRLoginError):
        await login.poll("alice", old["id"], AsyncMock())
    async with login.mutation():
        pass
    with pytest.raises(QRLoginError):
        await login.poll("alice", new["id"], AsyncMock())


@pytest.mark.asyncio
async def test_failed_apply_is_not_repeated_or_exposed(login):
    session = await login.start("alice", {})
    login.request.return_value = {"status": "confirmed", "bot_token": "secret"}
    apply = AsyncMock(side_effect=RuntimeError("secret-token-in-error"))
    with pytest.raises(QRLoginError) as error:
        await login.poll("alice", session["id"], apply)
    assert "secret" not in str(error.value)
    assert (await login.poll("alice", session["id"], apply))["status"] == "failed"
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_expiry_during_poll_rejects_late_credentials(login):
    session = await login.start("alice", {})

    async def request(*args):
        login.session.expires_at = 0
        return {"status": "confirmed", "bot_token": "too-late"}

    login.request.side_effect = request
    apply = AsyncMock()
    assert (await login.poll("alice", session["id"], apply))["status"] == "expired"
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_transport_closes_http_client_without_starting_channel(monkeypatch):
    from app.channels.wechat import WechatChannel

    request = AsyncMock(return_value={"qrcode": "id", "qrcode_img_content": "scan"})
    stop = AsyncMock()
    start = AsyncMock()
    monkeypatch.setattr(WechatChannel, "request_login_qrcode", request)
    monkeypatch.setattr(WechatChannel, "stop", stop)
    monkeypatch.setattr(WechatChannel, "start", start)
    await WechatQRLogin().start("alice", {})
    stop.assert_awaited_once()
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_polls_only_apply_once(login):
    session = await login.start("alice", {})
    entered, release = asyncio.Event(), asyncio.Event()

    async def request(*args):
        entered.set()
        await release.wait()
        return {"status": "confirmed", "bot_token": "secret"}

    login.request.side_effect = request
    apply = AsyncMock(return_value={"provider": "wechat"})
    first = asyncio.create_task(login.poll("alice", session["id"], apply))
    await entered.wait()
    second = asyncio.create_task(login.poll("alice", session["id"], apply))
    release.set()
    results = await asyncio.gather(first, second)
    assert all(result["status"] == "confirmed" for result in results)
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_redirect_then_confirmation_saves_returned_api_host(login):
    session = await login.start("alice", {})
    login.request.return_value = {"status": "scaned_but_redirect", "redirect_host": "ilinkai2.weixin.qq.com"}
    apply = AsyncMock(return_value={"provider": "wechat"})
    assert (await login.poll("alice", session["id"], apply))["status"] == "scanned"
    login.request.return_value = {"status": "confirmed", "bot_token": "secret", "baseurl": "https://ilinkai2.weixin.qq.com/"}
    await login.poll("alice", session["id"], apply)
    assert login.request.call_args.args[0]["base_url"] == "https://ilinkai2.weixin.qq.com"
    assert apply.call_args.args[0]["base_url"] == "https://ilinkai2.weixin.qq.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1", "evil.example", "weixin.qq.com.evil.example", "ilinkai.weixin.qq.com@127.0.0.1", "ilinkai.weixin.qq.com:8001", "ilinkai.weixin.qq.com/path", ""])
async def test_untrusted_provider_redirect_is_rejected(login, host):
    session = await login.start("alice", {})
    login.request.return_value = {"status": "scaned_but_redirect", "redirect_host": host}
    apply = AsyncMock()
    result = await login.poll("alice", session["id"], apply)
    assert result["status"] == "failed"
    assert result["error"] == "invalid_response"
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_code_is_submitted_without_exposing_or_reusing_it(login):
    session = await login.start("alice", {})
    apply = AsyncMock()
    login.request.return_value = {"status": "need_verifycode"}
    assert (await login.poll("alice", session["id"], apply))["status"] == "verification_required"
    result = await login.poll("alice", session["id"], apply, verify_code="123456")
    assert login.request.call_args.kwargs["verify_code"] == "123456"
    assert result["error"] == "verification_rejected"
    assert "123456" not in str(result)
    login.request.return_value = {"status": "scaned"}
    assert (await login.poll("alice", session["id"], apply, verify_code="654321"))["status"] == "scanned"
    await login.poll("alice", session["id"], apply)
    assert not login.request.call_args.kwargs.get("verify_code")
    apply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [("binded_redirect", "already_bound"), ("verify_code_blocked", "verification_blocked"), ("new-unsupported-status", "invalid_response")])
async def test_action_required_states_do_not_silently_wait(login, status, error):
    session = await login.start("alice", {})
    login.request.return_value = {"status": status}
    apply = AsyncMock()
    result = await login.poll("alice", session["id"], apply)
    assert result["status"] == "failed"
    assert result["error"] == error
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_temporary_provider_error_retries_same_qr_and_clears_feedback(login):
    session = await login.start("alice", {})
    request = httpx.Request("GET", "https://example.com/?qrcode=secret")
    login.request.side_effect = httpx.HTTPStatusError("sensitive-response", request=request, response=httpx.Response(502, request=request))
    result = await login.poll("alice", session["id"], AsyncMock())
    assert result["status"] == "pending"
    assert result["error"] == "network"
    assert "secret" not in str(result)
    login.request.side_effect = None
    login.request.return_value = {"status": "scaned"}
    result = await login.poll("alice", session["id"], AsyncMock())
    assert result["status"] == "scanned"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_confirmation_cannot_save_token_to_untrusted_api_host(login):
    session = await login.start("alice", {})
    login.request.return_value = {"status": "confirmed", "bot_token": "secret", "baseurl": "http://127.0.0.1"}
    apply = AsyncMock()
    assert (await login.poll("alice", session["id"], apply))["status"] == "failed"
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_transport_uses_long_poll_and_provider_query(monkeypatch):
    from app.channels.wechat import WechatChannel

    request = AsyncMock(return_value={"status": "scaned"})
    monkeypatch.setattr(WechatChannel, "_request_public_get_json", request)
    result = await WechatQRLogin().request({}, "private-id", verify_code="123456")
    assert result["status"] == "scaned"
    request.assert_awaited_once_with("/ilink/bot/get_qrcode_status", params={"qrcode": "private-id", "verify_code": "123456"}, timeout=35)


@pytest.mark.asyncio
async def test_verification_input_and_expired_sessions_do_not_reach_provider(login):
    session = await login.start("alice", {})
    login.request.reset_mock()
    with pytest.raises(QRLoginError):
        await login.poll("alice", session["id"], AsyncMock(), verify_code="123456")
    login.session.status = "verification_required"
    with pytest.raises(QRLoginError):
        await login.poll("alice", session["id"], AsyncMock(), verify_code="not-digits")
    login.session.expires_at = 0
    assert (await login.poll("alice", session["id"], AsyncMock(), verify_code="123456"))["status"] == "expired"
    login.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_timeout_keeps_code_and_signals_automatic_retry(login):
    session = await login.start("alice", {})
    login.request.return_value = {"status": "need_verifycode"}
    await login.poll("alice", session["id"], AsyncMock())
    login.request.side_effect = httpx.ReadTimeout("private URL and code")
    result = await login.poll("alice", session["id"], AsyncMock(), verify_code="123456")
    assert result["error"] == "network"
    assert "123456" not in str(result)
    login.request.side_effect = None
    login.request.return_value = {"status": "scaned"}
    assert (await login.poll("alice", session["id"], AsyncMock()))["status"] == "scanned"
    assert login.request.call_args.kwargs["verify_code"] == "123456"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"status": "wait"},
        {"status": "pending"},
        {"status": "scaned_but_redirect", "redirect_host": "ilinkai2.weixin.qq.com"},
    ],
)
async def test_pairing_wait_and_redirect_keep_polling_with_submitted_code(login, response):
    session = await login.start("alice", {})
    apply = AsyncMock(return_value={"provider": "wechat", "configured": True})
    login.request.return_value = {"status": "need_verifycode"}
    await login.poll("alice", session["id"], apply)

    login.request.return_value = response
    result = await login.poll("alice", session["id"], apply, verify_code="123456")
    # The browser automatically polls scanned sessions, but waits for input
    # when verification_required has no network error.
    assert result["status"] == "scanned"
    assert result["error"] is None
    assert "123456" not in str(result)
    apply.assert_not_awaited()

    # No resubmission from the browser is needed, even after multiple waits.
    login.request.return_value = {"status": "wait"}
    result = await login.poll("alice", session["id"], apply)
    assert result["status"] == "scanned"
    assert login.request.call_args.kwargs.get("verify_code") == "123456"
    if response["status"] == "scaned_but_redirect":
        assert login.request.call_args.args[0]["base_url"] == "https://ilinkai2.weixin.qq.com"

    login.request.return_value = {"status": "confirmed", "bot_token": "secret-token"}
    result = await login.poll("alice", session["id"], apply)
    assert login.request.call_args.kwargs.get("verify_code") == "123456"
    assert result["status"] == "confirmed"
    assert login.session.verify_code is None
    assert "123456" not in str(result)
    assert "secret-token" not in str(result)
    apply.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,status,error",
    [
        ({"status": "need_verifycode"}, "verification_required", "verification_rejected"),
        ({"status": "scaned"}, "scanned", None),
        ({"status": "expired"}, "expired", None),
        ({"status": "verify_code_blocked"}, "failed", "verification_blocked"),
        ({"status": "binded_redirect"}, "failed", "already_bound"),
        ({"status": "scaned_but_redirect", "redirect_host": "evil.example"}, "failed", "invalid_response"),
        ({"status": "confirmed"}, "failed", "invalid_response"),
        ({"status": "unsupported"}, "failed", "invalid_response"),
    ],
)
async def test_pairing_code_is_cleared_after_provider_decides(login, response, status, error):
    session = await login.start("alice", {})
    apply = AsyncMock()
    login.request.return_value = {"status": "need_verifycode"}
    await login.poll("alice", session["id"], apply)
    login.request.return_value = {"status": "wait"}
    await login.poll("alice", session["id"], apply, verify_code="123456")

    login.request.return_value = response
    result = await login.poll("alice", session["id"], apply)
    assert login.request.call_args.kwargs.get("verify_code") == "123456"
    assert result["status"] == status
    assert result["error"] == error
    assert login.session.verify_code is None
    assert "123456" not in str(result)
    apply.assert_not_awaited()

    if status == "verification_required":
        login.request.return_value = {"status": "scaned"}
        await login.poll("alice", session["id"], apply, verify_code="654321")
        assert login.request.call_args.kwargs["verify_code"] == "654321"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "transport", "invalid_response", "expired"])
async def test_pairing_wait_handles_network_retry_and_session_end(login, failure):
    session = await login.start("alice", {})
    apply = AsyncMock(return_value={"provider": "wechat"})
    login.request.return_value = {"status": "need_verifycode"}
    await login.poll("alice", session["id"], apply)
    login.request.return_value = {"status": "wait"}
    await login.poll("alice", session["id"], apply, verify_code="123456")
    login.request.reset_mock()

    if failure == "expired":
        login.session.expires_at = 0
    else:
        login.request.side_effect = {
            "timeout": httpx.ReadTimeout("private URL and code"),
            "transport": httpx.ConnectError("private URL and code"),
            "invalid_response": ValueError("private URL and code"),
        }[failure]
    result = await login.poll("alice", session["id"], apply)
    assert "123456" not in str(result)
    apply.assert_not_awaited()

    if failure in {"timeout", "transport"}:
        assert result["status"] == "scanned"
        assert result["error"] == "network"
        login.request.side_effect = None
        login.request.return_value = {"status": "confirmed", "bot_token": "secret-token"}
        assert (await login.poll("alice", session["id"], apply))["status"] == "confirmed"
        assert login.request.call_args.kwargs.get("verify_code") == "123456"
        assert login.session.verify_code is None
        apply.assert_awaited_once()
    else:
        assert result["status"] == ("expired" if failure == "expired" else "failed")
        assert login.session.verify_code is None
        if failure == "expired":
            login.request.assert_not_awaited()
