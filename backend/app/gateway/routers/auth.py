"""Authentication router for Feishu OAuth login."""

import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import quote, unquote

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.gateway.auth.feishu import FeishuAuthError, FeishuOAuthClient
from deerflow.config.app_config import AppConfig, get_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Session cookie name
SESSION_COOKIE = "deerflow_session"
# Session duration: 7 days
SESSION_MAX_AGE = 7 * 24 * 60 * 60


def _read_raw_feishu_config() -> dict:
    """Read raw Feishu auth config from config.yaml (without env resolution)."""
    config = get_app_config()
    raw_data = {}
    try:
        import yaml
        config_path = config.resolve_config_path()
        with open(config_path) as f:
            raw_data = yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Failed to read config.yaml for auth settings")
    return raw_data.get("auth", {}).get("feishu", {})


def _get_feishu_config() -> dict:
    """Get Feishu auth configuration with $ENV_VAR references resolved."""
    raw = _read_raw_feishu_config()
    return AppConfig.resolve_env_variables(raw)


def _get_session_secret() -> str:
    """Get session signing secret from config or generate a default."""
    feishu_config = _get_feishu_config()
    # Use app_secret as signing key (always available if Feishu auth is configured)
    return feishu_config.get("app_secret", "deerflow-default-session-secret")


def _create_feishu_client() -> FeishuOAuthClient:
    """Create a Feishu OAuth client from config."""
    feishu_config = _get_feishu_config()
    if not feishu_config.get("enabled"):
        raise ValueError("Feishu auth is not enabled in config.yaml")
    lark_host = feishu_config.get("lark_host", "https://open.feishu.cn")
    app_id = feishu_config.get("app_id", "")
    app_secret = feishu_config.get("app_secret", "")
    if not app_id or not app_secret:
        raise ValueError("Feishu app_id and app_secret must be configured in config.yaml")
    return FeishuOAuthClient(lark_host=lark_host, app_id=app_id, app_secret=app_secret)


def _sign_session(payload: dict) -> str:
    """Create a signed session token from a payload dict.

    The JSON payload is base64url-encoded to ensure the cookie value
    contains only ASCII-safe characters (avoids latin-1 encoding errors
    with non-ASCII user names).
    """
    secret = _get_session_secret()
    payload["_ts"] = int(time.time())
    data_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    b64_data = base64.urlsafe_b64encode(data_bytes).decode("ascii")
    sig = hmac.new(secret.encode(), data_bytes, hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"


def _verify_session(token: str) -> dict | None:
    """Verify and decode a signed session token. Returns None if invalid."""
    secret = _get_session_secret()
    parts = token.rsplit(".", 1)
    if len(parts) != 2:
        return None
    b64_data, sig = parts
    try:
        data_bytes = base64.urlsafe_b64decode(b64_data)
    except Exception:
        return None
    expected_sig = hmac.new(secret.encode(), data_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(data_bytes)
    except (json.JSONDecodeError, ValueError):
        return None
    # Check expiration
    ts = payload.get("_ts", 0)
    if time.time() - ts > SESSION_MAX_AGE:
        return None
    return payload


@router.get("/feishu/login")
async def feishu_login(request: Request, redirect: str = "/workspace/chats/new"):
    """Initiate Feishu OAuth login flow.

    Redirects the user to the Feishu authorization page.
    After authorization, Feishu will redirect back to our callback endpoint.
    """
    try:
        client = _create_feishu_client()
    except ValueError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    feishu_config = _get_feishu_config()
    callback_url = feishu_config.get("callback_url", "")
    if not callback_url:
        # Auto-detect from request
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        callback_url = f"{scheme}://{host}/api/auth/feishu/callback"

    # Encode the redirect URL as state parameter
    state = quote(redirect, safe="")
    authorize_url = client.get_authorize_url(redirect_uri=callback_url, state=state)
    return RedirectResponse(url=authorize_url)


@router.get("/feishu/callback")
async def feishu_callback(code: str = "", state: str = ""):
    """Handle Feishu OAuth callback.

    Exchanges the authorization code for user info, creates a session cookie,
    and redirects to the original page.
    """
    if not code:
        return JSONResponse(status_code=400, content={"error": "Missing authorization code"})

    try:
        client = _create_feishu_client()
        user_info = await client.authorize(code)
    except FeishuAuthError as e:
        logger.error("Feishu OAuth failed: %s", e)
        return JSONResponse(status_code=401, content={"error": f"Feishu auth failed: {e.msg}"})
    except Exception as e:
        logger.exception("Feishu OAuth error")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Build session payload from user info
    session_payload = {
        "open_id": user_info.get("open_id", ""),
        "name": user_info.get("name", ""),
        "en_name": user_info.get("en_name", ""),
        "avatar_url": user_info.get("avatar_url", ""),
        "email": user_info.get("email", ""),
        "user_id": user_info.get("user_id", ""),
    }
    token = _sign_session(session_payload)

    # Redirect back to the original page
    redirect_url = unquote(state) if state else "/workspace/chats/new"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/session")
async def get_session(deerflow_session: str | None = Cookie(default=None)):
    """Get the current user session.

    Returns user info if authenticated, or 401 if not.
    """
    if not deerflow_session:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    payload = _verify_session(deerflow_session)
    if not payload:
        return JSONResponse(status_code=401, content={"error": "Session expired or invalid"})

    # Remove internal fields
    user_info = {k: v for k, v in payload.items() if not k.startswith("_")}
    return {"authenticated": True, "user": user_info}


@router.post("/logout")
async def logout():
    """Clear the session cookie and log out."""
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return response


@router.get("/config")
async def get_auth_config():
    """Get auth configuration (which providers are enabled)."""
    raw_config = _read_raw_feishu_config()
    return {
        "feishu": {
            "enabled": raw_config.get("enabled", False),
        },
    }
