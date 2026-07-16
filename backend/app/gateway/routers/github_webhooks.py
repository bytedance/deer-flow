"""Gateway router for inbound GitHub webhook deliveries.

Receives GitHub App / repository webhook events at ``POST /api/webhooks/github``.
This route is intentionally exempt from both the auth and CSRF middleware
(see ``auth_middleware._PUBLIC_PATH_PREFIXES`` and
``csrf_middleware.should_check_csrf``) because GitHub neither sends a
session cookie nor an ``X-CSRF-Token`` header.

Authenticity is enforced via the HMAC-SHA256 signature in the
``X-Hub-Signature-256`` request header, compared in constant time against
the shared secret in the ``GITHUB_WEBHOOK_SECRET`` environment variable.

**The route is fail-closed by default.** If ``GITHUB_WEBHOOK_SECRET`` is
unset, the route is not mounted at all (`/api/webhooks/github` responds
404) so a misconfigured deployment cannot accept forged deliveries. Set
``DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS=1`` to mount the route
anyway for local development or loopback testing — every delivery is
then accepted unverified with a WARNING log line.

After verification the payload is fanned out by :func:`fanout_event` into
:class:`InboundMessage` instances on the channel bus, one per matching
custom agent binding. The :class:`GitHubChannel` (registered alongside
Feishu/Slack/etc.) takes care of posting the agent's reply back to GitHub.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.gateway.github.dispatcher import fanout_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_SECRET_ENV_VAR = "GITHUB_WEBHOOK_SECRET"
_ALLOW_UNVERIFIED_ENV_VAR = "DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS"

# Events we explicitly recognise. Anything else still returns 200 (so
# GitHub does not retry) but is logged as "unhandled" for visibility.
_KNOWN_EVENTS: frozenset[str] = frozenset(
    {
        "ping",
        "issues",
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
    }
)


def _get_webhook_secret() -> str | None:
    """Return the configured webhook secret, or None if unset.

    Read at request time so operators can rotate the secret without a
    full process restart. Treats empty strings as "unset" so a stray
    ``GITHUB_WEBHOOK_SECRET=`` in ``.env`` does not silently disable
    signature verification.
    """
    value = os.environ.get(_SECRET_ENV_VAR)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _unverified_webhooks_allowed() -> bool:
    """Return True iff the explicit dev opt-in for unverified deliveries is set.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Anything else (including unset) is False.
    """
    raw = os.environ.get(_ALLOW_UNVERIFIED_ENV_VAR, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_route_enabled() -> bool:
    """Return True iff the GitHub webhook route should be mounted.

    Mounted when either:
        * ``GITHUB_WEBHOOK_SECRET`` is set (production / staging path), or
        * ``DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS=1`` is set
          (explicit dev/loopback opt-in for testing without a real secret).

    When neither is set the route is intentionally absent — a fresh
    deployment with no secret in env cannot serve forged deliveries
    even by accident. Called by :mod:`app.gateway.app` at router
    inclusion time.
    """
    return _get_webhook_secret() is not None or _unverified_webhooks_allowed()


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify the GitHub ``X-Hub-Signature-256`` HMAC.

    Expected header format: ``sha256=<hex>``. Returns False if the header
    is missing, malformed, or fails constant-time comparison.
    """
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    provided = signature_header.removeprefix("sha256=").strip()
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _summarise_event(event: str, payload: dict[str, Any]) -> str:
    """Build a short, human-readable summary for the log line.

    Pulls the most useful identifiers per event type. Falls back to the
    raw action if anything unexpected shows up so we never crash here.
    """
    try:
        action = payload.get("action")
        repo = (payload.get("repository") or {}).get("full_name")

        if event == "ping":
            zen = payload.get("zen")
            hook_id = (payload.get("hook") or {}).get("id")
            return f"ping zen={zen!r} hook_id={hook_id} repo={repo}"

        if event == "pull_request":
            pr = payload.get("pull_request") or {}
            number = pr.get("number") or payload.get("number")
            title = pr.get("title")
            url = pr.get("html_url")
            return f"pull_request action={action} repo={repo} #{number} title={title!r} url={url}"

        if event == "pull_request_review":
            pr = payload.get("pull_request") or {}
            number = pr.get("number")
            review = payload.get("review") or {}
            state = review.get("state")  # approved | changes_requested | commented
            author = (review.get("user") or {}).get("login")
            return f"pull_request_review action={action} repo={repo} #{number} state={state} author={author}"

        if event == "issues":
            issue = payload.get("issue") or {}
            number = issue.get("number")
            title = issue.get("title")
            url = issue.get("html_url")
            return f"issues action={action} repo={repo} #{number} title={title!r} url={url}"

        if event == "issue_comment":
            issue = payload.get("issue") or {}
            number = issue.get("number")
            is_pr = "pull_request" in issue
            author = (payload.get("comment") or {}).get("user", {}).get("login")
            return f"issue_comment action={action} repo={repo} #{number} is_pr={is_pr} author={author}"

        if event == "pull_request_review_comment":
            pr = payload.get("pull_request") or {}
            number = pr.get("number")
            author = (payload.get("comment") or {}).get("user", {}).get("login")
            path = (payload.get("comment") or {}).get("path")
            return f"pull_request_review_comment action={action} repo={repo} #{number} path={path} author={author}"

        return f"{event} action={action} repo={repo}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"{event} (summary failed: {exc!r})"


@router.post("/github")
async def receive_github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Receive a GitHub webhook delivery.

    - Verifies the HMAC-SHA256 signature against ``GITHUB_WEBHOOK_SECRET``.
    - Logs the event + delivery id + a one-line payload summary.
    - Returns ``{"ok": True, ...}`` on successful (or no-op) dispatch so
      GitHub marks the delivery successful and does not retry.

    **Transient fan-out failures return 503**, not 200. GitHub retries 5xx
    deliveries with exponential backoff (up to ~5 attempts over ~8 hours)
    but does *not* retry 200 OK. A transient registry filesystem error or
    bus publish failure on a 200 path would silently drop a real webhook
    forever, so we return 503 instead and let GitHub redeliver — by the
    time the redelivery lands the underlying outage is usually gone. The
    `is_route_enabled()` startup check still handles *configuration*
    errors fail-closed (route absent → 404); 503 is reserved for runtime
    failures GitHub should retry. Permanent / non-retryable conditions
    (unknown event, missing channel service) keep returning 200.

    The route is fail-closed: :func:`is_route_enabled` should have already
    prevented this handler from being mounted when no secret is configured.
    The runtime guard below is a defense-in-depth fallback in case
    ``GITHUB_WEBHOOK_SECRET`` was unset *after* startup (e.g. an operator
    rotating env vars without restarting) — without the secret and without
    the explicit unverified opt-in, return 503 rather than accept a
    forgeable delivery.
    """
    body = await request.body()

    secret = _get_webhook_secret()
    if secret is None:
        if not _unverified_webhooks_allowed():
            # Should be unreachable if startup-time is_route_enabled() was honored,
            # but a runtime rotation that cleared the secret without a restart
            # would land here. Refuse the delivery.
            logger.error(
                "github_webhook: %s is not set and %s=1 not set; rejecting delivery (event=%s delivery=%s)",
                _SECRET_ENV_VAR,
                _ALLOW_UNVERIFIED_ENV_VAR,
                x_github_event,
                x_github_delivery,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Webhook signature verification not configured. Set {_SECRET_ENV_VAR} or {_ALLOW_UNVERIFIED_ENV_VAR}=1 for unverified dev mode.",
            )
        logger.warning(
            "github_webhook: accepting UNVERIFIED delivery (event=%s delivery=%s). %s=1 is set — dev/loopback mode ONLY. Do not use in production.",
            x_github_event,
            x_github_delivery,
            _ALLOW_UNVERIFIED_ENV_VAR,
        )
    else:
        if not _verify_signature(secret, body, x_hub_signature_256):
            logger.warning(
                "github_webhook: signature verification FAILED (event=%s delivery=%s)",
                x_github_event,
                x_github_delivery,
            )
            raise HTTPException(status_code=401, detail="Invalid or missing X-Hub-Signature-256")

    if not x_github_event:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    # Parse JSON payload after signature is verified (verify-then-parse).
    try:
        payload: dict[str, Any] = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        logger.warning(
            "github_webhook: invalid JSON body (event=%s delivery=%s): %s",
            x_github_event,
            x_github_delivery,
            exc,
        )
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if x_github_event in _KNOWN_EVENTS:
        logger.info(
            "github_webhook delivery=%s | %s",
            x_github_delivery,
            _summarise_event(x_github_event, payload),
        )
        handled = True
        # Publish inbound messages onto the channel bus so the
        # ChannelManager picks them up and routes them to the right
        # custom agents. No direct agent-run calls here.
        from app.channels.service import get_channel_service

        service = get_channel_service()
        if service is None:
            # Permanent state, not a transient failure: ``channels.github``
            # is not enabled in this deployment. Returning 503 would
            # condemn GitHub to retry every delivery on backoff for hours
            # before giving up, all the way to no-op. Stay on 200 and
            # surface the reason in the response body for operators
            # checking the redelivery page.
            logger.warning(
                "github_webhook: channel service not available — no agents fired (delivery=%s event=%s)",
                x_github_delivery,
                x_github_event,
            )
            dispatch_result: dict[str, Any] | None = {
                "error": "channel_service_not_available",
                "hint": "add channels.github.enabled: true to config.yaml",
            }
        elif not service.is_channel_enabled("github"):
            # ``channels.github.enabled: false`` is the documented operator
            # kill-switch for GitHub integration. The webhook route itself
            # is governed by ``GITHUB_WEBHOOK_SECRET`` (fail-closed when
            # unset), so an operator who flipped only ``enabled: false``
            # without also unsetting the secret would otherwise keep
            # firing agents on every delivery — agents that then post
            # back to GitHub via ``gh``, contradicting the documented
            # off-switch. Bail before ``fanout_event`` so no inbound
            # ever reaches the bus consumer in ChannelManager. Stay on
            # 200 (permanent state, not transient) so GitHub doesn't
            # retry; surface the reason in dispatch_result for the
            # Recent Deliveries panel.
            logger.info(
                "github_webhook: channels.github.enabled=false — skipping fan-out (delivery=%s event=%s)",
                x_github_delivery,
                x_github_event,
            )
            dispatch_result = {"skipped": "channel_disabled"}
        else:
            # Pull the operator-set default mention handle from the live
            # ``channels.github`` block so the dispatcher can use it as a
            # fallback when neither the trigger nor the agent's own
            # ``github.bot_login`` declares one. CLAUDE.md documents this
            # field as the global default for ``require_mention`` triggers;
            # reading the live config (which tracks UI-driven flips via
            # ``configure_channel``) keeps the documented contract honest
            # without forcing a process restart for operators tuning it.
            github_channel_config = service.get_channel_config("github") or {}
            raw_default_mention = github_channel_config.get("default_mention_login")
            operator_default_mention_login = raw_default_mention.strip() if isinstance(raw_default_mention, str) else None

            # Let fan-out exceptions propagate as 503 so GitHub retries.
            # ``fanout_event`` calls the registry (filesystem) and the
            # message bus; both can fail transiently (disk hiccup, bus
            # queue full, asyncio cancellation). Swallowing those into a
            # 200 would permanently drop a real webhook because GitHub
            # only retries on 5xx. The startup-time ``is_route_enabled``
            # check still covers fail-closed *configuration* errors.
            try:
                dispatch_result = await fanout_event(
                    service.bus,
                    x_github_event,
                    x_github_delivery,
                    payload,
                    operator_default_mention_login=operator_default_mention_login,
                )
            except Exception as exc:  # noqa: BLE001 — re-raised as 503 below
                logger.exception(
                    "github_webhook: fanout failed (delivery=%s event=%s) — returning 503 so GitHub retries",
                    x_github_delivery,
                    x_github_event,
                )
                raise HTTPException(
                    status_code=503,
                    detail=f"fan-out failed for delivery {x_github_delivery!r}: {exc!r}",
                ) from exc
    else:
        logger.info(
            "github_webhook delivery=%s | unhandled event=%s action=%s repo=%s",
            x_github_delivery,
            x_github_event,
            payload.get("action"),
            (payload.get("repository") or {}).get("full_name"),
        )
        handled = False
        dispatch_result = None

    return {
        "ok": True,
        "event": x_github_event,
        "delivery": x_github_delivery,
        "handled": handled,
        "dispatch": dispatch_result,
    }
