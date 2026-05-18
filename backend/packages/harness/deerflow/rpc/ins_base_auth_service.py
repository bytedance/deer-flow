"""Python client for ins-base-rpc authentication service.

Corresponds to ins-base-rpc /auth endpoints.
"""

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "ins-base-rpc"
PATH_PREFIX = "/ins-base-rpc"


class InsBaseAuthServiceClient:
    """Python client for ins-base-rpc authentication FeignClient.

    Usage:
        client = InsBaseAuthServiceClient()
        result = await client.login(encoded_user, encoded_pass)
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def login(self, encoded_user: str, encoded_pass: str) -> dict[str, Any]:
        """Login with RSA-encrypted credentials.

        Args:
            encoded_user: RSA-encrypted username.
            encoded_pass: RSA-encrypted password.

        Returns:
            dict: Raw response dict from the RPC call.
        """
        return await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/auth/login",
            "GET",
            {
                "captchaPass": "true",
                "enCodeUser": encoded_user,
                "enCodePassword": encoded_pass,
            },
        )

    async def authenticate(self, token: str) -> dict[str, Any]:
        """Authenticate a token.

        Args:
            token: The access token.

        Returns:
            dict: Raw response dict from the RPC call.
        """
        return await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/auth/authentication",
            "GET",
            {"token": token},
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an access token.

        Args:
            refresh_token: The refresh token.

        Returns:
            dict: Raw response dict from the RPC call.
        """
        return await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/auth/refresh",
            "GET",
            {"refresh": refresh_token},
        )
