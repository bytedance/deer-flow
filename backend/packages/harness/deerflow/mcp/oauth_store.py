"""Encrypted, cross-process storage for rotating MCP OAuth tokens.

``OAuthTokenManager`` keeps tokens in process memory. For the ``refresh_token``
grant that is not enough: providers that rotate refresh tokens (Auth0, Okta,
Google) consume the old one on every refresh, so a second Gateway replica, a
restart, a tool-cache reset or a new personal-tool manager that starts again
from the configured seed gets ``invalid_grant``. This store keeps each
connection's latest tokens in ``mcp_oauth_tokens`` (see
``deerflow.persistence.mcp_oauth_tokens``), encrypted with the deployment
credentials key (``DEER_FLOW_CREDENTIALS_KEY``), and arbitrates refreshes
between processes with a short lease.

The host installs one store per process (:func:`set_mcp_oauth_token_store`);
without one, tokens stay in process memory as before. Every method blocks
(SQL, possibly the first key-file read): call it through ``asyncio.to_thread``.
``client_credentials`` tokens are never stored; each process can mint its own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from deerflow.config.credentials_key import CredentialsCipher, CredentialsDecryptError
from deerflow.config.extensions_config import McpOAuthConfig
from deerflow.persistence.mcp_oauth_tokens import SqlMcpOAuthTokenRepository

logger = logging.getLogger(__name__)

#: How long a claimed refresh stays reserved without a renewal. The holder
#: renews it every third of this while its token request runs, because HTTP
#: timeouts bound each I/O wait, not the whole request.
REFRESH_LEASE_SECONDS = 30.0
#: The longest a token request may hold the lease; it is abandoned after this.
REFRESH_MAX_SECONDS = 120.0
#: How often a process waiting on a peer's refresh re-reads the row.
REFRESH_POLL_SECONDS = 0.2


class McpOAuthTokenStoreUnavailable(RuntimeError):
    """The store cannot be read or written; refreshing anyway could consume a token nobody keeps."""


class McpOAuthTokenKeyUnavailable(McpOAuthTokenStoreUnavailable):
    """The credentials key cannot be loaded, so nothing can be stored encrypted."""


@dataclass(frozen=True)
class McpOAuthTokenKey:
    """Row key: personal connections never share a row with a same-named deployment one."""

    scope: Literal["deployment", "personal"]
    owner_user_id: str
    server_key: str

    @classmethod
    def for_server(cls, server_name: str, owner_user_id: str | None) -> McpOAuthTokenKey:
        if owner_user_id is None:
            return cls(scope="deployment", owner_user_id="", server_key=server_name)
        return cls(scope="personal", owner_user_id=owner_user_id, server_key=server_name)


@dataclass(frozen=True)
class PersistedOAuthToken:
    """A usable stored token chain: written under the caller's fingerprint and decrypted."""

    access_token: str | None
    token_type: str | None
    expires_at: datetime | None
    refresh_token: str


class StoredTokenLookup(NamedTuple):
    """A row read for one token chain: ``version`` is ``None`` without a row; ``token`` is ``None`` when unusable."""

    version: int | None
    token: PersistedOAuthToken | None
    #: The row matched this chain but no configured key could decrypt it.
    undecryptable: bool = False


def _server_subject(key: McpOAuthTokenKey) -> str:
    return f"MCP server '{key.server_key}'"


def oauth_config_fingerprint(oauth: McpOAuthConfig) -> str:
    """Identify the configured token chain, so a changed seed wins over a stored rotation.

    Covers what makes an issued refresh token valid: endpoint, client, grant,
    scope, audience and the configured seed. ``client_secret`` is left out
    because rotating it keeps the issued chain valid. Only the SHA-256 digest
    is stored, never the seed itself.
    """
    identity = [oauth.token_url, oauth.client_id, oauth.grant_type, oauth.scope, oauth.audience, oauth.refresh_token]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()


def oauth_token_request_fingerprint(oauth: McpOAuthConfig) -> str:
    """Identify how an access token is requested and read, beyond the token chain.

    ``extra_token_params`` (for example a ``resource`` or provider-specific
    audience) select what the issued access token is for, and the response
    fields select which value is used. A stored access token is reused only
    by a process whose fingerprint matches; otherwise it refreshes from the
    stored refresh token, which stays valid across such changes.
    """
    identity = [sorted(oauth.extra_token_params.items()), oauth.token_field, oauth.token_type_field, oauth.expires_in_field, oauth.default_token_type]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()


class McpOAuthTokenStore:
    """Encrypt and arbitrate one process's view of ``mcp_oauth_tokens``.

    ``cipher`` defaults to the process-wide credentials cipher, loaded on first
    use so deployments without OAuth connections never create a key file.
    """

    def __init__(self, repository: SqlMcpOAuthTokenRepository, *, cipher: CredentialsCipher | None = None) -> None:
        self._repo = repository
        self._explicit_cipher = cipher

    def _cipher(self) -> CredentialsCipher:
        if self._explicit_cipher is not None:
            return self._explicit_cipher
        from deerflow.config.credentials_key import get_credentials_cipher

        try:
            return get_credentials_cipher()
        except Exception:
            logger.exception("Failed to load the credentials key for MCP OAuth tokens")
            raise McpOAuthTokenKeyUnavailable("The credentials key for stored MCP OAuth tokens cannot be loaded") from None

    def _call(self, subject: str, action: str, operation: Callable[[], object]):
        try:
            return operation()
        except McpOAuthTokenStoreUnavailable:
            raise
        except Exception:
            # Database errors render the statement and its parameters; keep
            # them in the log, never in the model-visible tool error.
            logger.exception("Failed to %s the stored OAuth tokens for %s", action, subject)
            raise McpOAuthTokenStoreUnavailable(f"OAuth token storage is unavailable for {subject}; try again later") from None

    def load(self, key: McpOAuthTokenKey, *, fingerprint: str, request_fingerprint: str) -> StoredTokenLookup:
        """Read the chain's row: no row has no version; a row this chain cannot use has no token.

        The access token is withheld (``None``) when it was requested under
        another ``request_fingerprint``; the refresh token is still returned.
        """
        cipher = self._cipher()
        row = self._call(_server_subject(key), "read", lambda: self._repo.get(key.scope, key.owner_user_id, key.server_key))
        if row is None:
            return StoredTokenLookup(None, None)
        if row.config_fingerprint != fingerprint or row.refresh_token_enc is None:
            # Written for another seed/endpoint, or claimed but never filled.
            return StoredTokenLookup(row.version, None)
        try:
            refresh_token = cipher.decrypt_text(row.refresh_token_enc)
            reusable = row.access_token_enc is not None and row.token_request_fingerprint == request_fingerprint
            access_token = cipher.decrypt_text(row.access_token_enc) if reusable else None
        except CredentialsDecryptError:
            logger.warning(
                "Stored OAuth token for MCP server '%s' cannot be decrypted with the configured credentials key(s); using the configured refresh token. Every instance needs the same DEER_FLOW_CREDENTIALS_KEY.",
                key.server_key,
            )
            return StoredTokenLookup(row.version, None, undecryptable=True)
        expires_at = datetime.fromtimestamp(row.access_expires_at, UTC) if row.access_expires_at is not None else None
        return StoredTokenLookup(row.version, PersistedOAuthToken(access_token=access_token, token_type=row.token_type, expires_at=expires_at, refresh_token=refresh_token))

    def claim(self, key: McpOAuthTokenKey, *, fingerprint: str, expected_version: int | None) -> str | None:
        """Claim the next refresh; returns the lease token, or ``None`` while a peer holds it or wrote since the read."""
        lease_owner = str(uuid.uuid4())
        claimed = self._call(
            _server_subject(key),
            "claim",
            lambda: self._repo.claim(
                key.scope,
                key.owner_user_id,
                key.server_key,
                config_fingerprint=fingerprint,
                expected_version=expected_version,
                lease_owner=lease_owner,
                lease_seconds=REFRESH_LEASE_SECONDS,
                now=time.time(),
            ),
        )
        return lease_owner if claimed else None

    def save(
        self,
        key: McpOAuthTokenKey,
        *,
        lease_owner: str,
        fingerprint: str,
        request_fingerprint: str,
        access_token: str,
        token_type: str,
        expires_at: datetime,
        refresh_token: str,
        rotated: bool,
    ) -> bool:
        """Store a refreshed token under the claim; ``False`` when the lease was lost meanwhile."""
        cipher = self._cipher()
        access_token_enc = cipher.encrypt_text(access_token)
        refresh_token_enc = cipher.encrypt_text(refresh_token)
        return self._call(
            _server_subject(key),
            "write",
            lambda: self._repo.write(
                key.scope,
                key.owner_user_id,
                key.server_key,
                lease_owner=lease_owner,
                config_fingerprint=fingerprint,
                access_token_enc=access_token_enc,
                token_request_fingerprint=request_fingerprint,
                token_type=token_type,
                access_expires_at=expires_at.timestamp(),
                refresh_token_enc=refresh_token_enc,
                rotated=rotated,
                now=time.time(),
            ),
        )

    def renew(self, key: McpOAuthTokenKey, lease_owner: str) -> bool:
        """Extend the claim's lease by ``REFRESH_LEASE_SECONDS``; ``False`` once it is no longer held."""
        return self._call(_server_subject(key), "renew", lambda: self._repo.renew(key.scope, key.owner_user_id, key.server_key, lease_owner=lease_owner, lease_seconds=REFRESH_LEASE_SECONDS))

    def release(self, key: McpOAuthTokenKey, lease_owner: str) -> bool:
        return self._call(_server_subject(key), "release", lambda: self._repo.release(key.scope, key.owner_user_id, key.server_key, lease_owner=lease_owner))

    def forget_unconfigured(self, owner_user_id: str | None, configured_server_keys: Collection[str]) -> int:
        """Delete the rows of one owner's connections (``None``: the deployment's) that a saved configuration no longer has.

        A removed connection's key can never be derived again, so its row would
        only keep refresh-token ciphertext around. Returns how many were deleted.
        """
        scope_key = McpOAuthTokenKey.for_server("", owner_user_id)
        subject = "deployment MCP servers" if owner_user_id is None else f"personal MCP connections of user '{owner_user_id}'"
        return self._call(subject, "prune", lambda: self._repo.delete_except(scope_key.scope, scope_key.owner_user_id, configured_server_keys))


_store: McpOAuthTokenStore | None = None


def set_mcp_oauth_token_store(store: McpOAuthTokenStore | None) -> McpOAuthTokenStore | None:
    """Install the host's store for managers built without one, returning the previous store."""
    global _store
    previous, _store = _store, store
    return previous


def get_mcp_oauth_token_store() -> McpOAuthTokenStore | None:
    return _store
