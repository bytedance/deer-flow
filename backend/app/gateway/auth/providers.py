"""Auth provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ipaddress
import json
import logging

from app.gateway.auth.config import TrustedHeaderProviderConfig
from app.gateway.auth.repositories.base import UserRepository

logger = logging.getLogger(__name__)


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> "User | None":
        """Authenticate user with given credentials.

        Returns User if authentication succeeds, None otherwise.
        """
        ...

    @abstractmethod
    async def get_user(self, user_id: str) -> "User | None":
        """Retrieve user by ID."""
        ...

    async def authenticate_request(self, request) -> "User | None":
        """Optional request-level authentication hook."""
        return None


class TrustedHeaderAuthProvider(AuthProvider):
    """Trusted reverse-proxy header auth provider."""

    def __init__(self, repository: UserRepository, config: TrustedHeaderProviderConfig) -> None:
        self._repo = repository
        self._config = config
        self._trusted_networks = [ipaddress.ip_network(cidr, strict=False) for cidr in config.trusted_networks]

    async def authenticate(self, credentials: dict) -> "User | None":
        user_id = credentials.get("user_id")
        if not user_id:
            return None
        return await self.get_user(str(user_id))

    async def get_user(self, user_id: str) -> "User | None":
        return await self._repo.get_user_by_id(user_id)

    def _client_ip_trusted(self, client_host: str | None) -> bool:
        if not self._trusted_networks or not client_host:
            return False
        ip = ipaddress.ip_address(client_host)
        return any(ip in network for network in self._trusted_networks)

    async def authenticate_request(self, request) -> "User | None":
        client_host = request.client.host if request.client else None
        if not self._client_ip_trusted(client_host):
            return None

        raw_user_id = request.headers.get(self._config.user_id_header)
        if raw_user_id and raw_user_id.strip():
            user_id = raw_user_id.strip()
            signature = request.headers.get(self._config.hmac_signature_header)
            if not self._config.verify_hmac(user_id, signature):
                logger.info("trusted-header auth rejected request due to HMAC mismatch")
                return None
            return await self.get_user(user_id)

        for header in self._config.legacy_user_id_headers:
            raw = request.headers.get(header)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            user_id = parsed.get("user_id")
            if user_id:
                signature = request.headers.get(self._config.hmac_signature_header)
                if not self._config.verify_hmac(str(user_id), signature):
                    logger.info("trusted-header auth rejected legacy header due to HMAC mismatch")
                    return None
                return await self.get_user(str(user_id))

        return None


# Import User at runtime to avoid circular imports
from app.gateway.auth.models import User  # noqa: E402
