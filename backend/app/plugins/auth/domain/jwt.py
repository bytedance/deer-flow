"""JWT token creation and verification."""

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel

from app.plugins.auth.domain.errors import TokenError
from app.plugins.auth.runtime.config_state import get_auth_config


class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    iat: datetime | None = None
    ver: int = 0


def create_access_token(user_id: str, expires_delta: timedelta | None = None, token_version: int = 0) -> str:
    config = get_auth_config()
    expiry = expires_delta or timedelta(days=config.token_expiry_days)
    now = datetime.now(UTC)
    payload = {"sub": user_id, "exp": now + expiry, "iat": now, "ver": token_version}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenPayload | TokenError:
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        return TokenError.EXPIRED
    except jwt.InvalidSignatureError:
        return TokenError.INVALID_SIGNATURE
    except jwt.PyJWTError:
        return TokenError.MALFORMED
