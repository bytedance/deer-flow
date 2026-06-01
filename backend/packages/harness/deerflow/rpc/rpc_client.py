"""Java RPC client for calling Java microservices.

Uses httpx for HTTP/JSON-RPC communication with connection pooling,
Nacos-based service discovery, timeout handling, and retry support.
"""

import asyncio
import logging
from typing import Any

import httpx

from deerflow.config.nacos_config import get_nacos_config
from deerflow.config.rpc_config import (
    RpcConfig,
    RpcEndpointConfig,
    RpcServiceConfig,
    get_rpc_config,
)
from deerflow.rpc.nacos_registry import NacosRegistry

logger = logging.getLogger(__name__)


class RpcError(Exception):
    """Base exception for RPC call failures."""

    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class RpcConnectionError(RpcError):
    """Network-level connection error."""


class RpcTimeoutError(RpcError):
    """RPC call timed out."""


class RpcClient:
    """HTTP/JSON-RPC client for Java microservices.

    Resolves services via Nacos discovery or direct URL, with
    connection pooling, timeout, and retry support.
    """

    def __init__(self):
        self._http: httpx.AsyncClient | None = None
        self._registry: NacosRegistry | None = None
        self._resolver_index: dict[str, int] = {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
            )
        return self._http

    def _get_registry(self) -> NacosRegistry | None:
        """Lazily create a NacosRegistry from current config.

        Returns None if Nacos is not configured.
        """
        nacos_cfg = get_nacos_config()
        if nacos_cfg is None:
            return None
        if self._registry is None:
            self._registry = NacosRegistry(nacos_cfg)
        return self._registry

    def _get_service(self, service_name: str) -> RpcServiceConfig:
        cfg = get_rpc_config()
        if cfg is None:
            raise RpcError("RPC is not configured")
        for svc in cfg.services:
            if svc.name == service_name:
                return svc
        raise RpcError(f"RPC service '{service_name}' not found in configuration")

    def _get_endpoint(self, service: RpcServiceConfig, method: str) -> RpcEndpointConfig:
        for ep in service.endpoints:
            if ep.method == method:
                return ep
        raise RpcError(
            f"Method '{method}' not found on service '{service.name}'. "
            f"Available: {[e.method for e in service.endpoints]}"
        )

    async def _resolve_base_url(self, service: RpcServiceConfig) -> str:
        """Resolve the base URL for a service, via Nacos or direct config."""
        if service.base_url:
            return service.base_url.rstrip("/")
        if service.discovery:
            registry = self._get_registry()
            if registry is None:
                raise RpcError(
                    f"Service '{service.name}' uses Nacos discovery but Nacos is not configured"
                )
            instances = await registry.discover_service(service.discovery)
            if not instances:
                raise RpcConnectionError(
                    f"No healthy instances found for service '{service.discovery}' via Nacos"
                )
            # Round-robin across instances
            key = service.discovery
            idx = self._resolver_index.get(key, 0) % len(instances)
            instance = instances[idx]
            self._resolver_index[key] = idx + 1
            return f"http://{instance['ip']}:{instance['port']}"
        raise RpcError(
            f"Service '{service.name}' has neither base_url nor discovery configured"
        )

    def _build_url(self, base_url: str, endpoint: RpcEndpointConfig, params: dict[str, Any]) -> str:
        """Build the full URL, substituting path parameters."""
        path = endpoint.path
        for k, v in params.items():
            path = path.replace(f"{{{k}}}", str(v))
        return f"{base_url}{path}"

    async def call(
        self,
        service_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Call a Java RPC service method.

        Args:
            service_name: Configured service name in config.yaml.
            method: Logical endpoint method name.
            params: Path parameters and/or request body.
            timeout: Per-call timeout override in seconds.

        Returns:
            Parsed JSON response.

        Raises:
            RpcError: On 4xx/5xx responses.
            RpcConnectionError: On network errors.
            RpcTimeoutError: On timeout.
        """
        if params is None:
            params = {}

        service = self._get_service(service_name)
        endpoint = self._get_endpoint(service, method)

        base_url = await self._resolve_base_url(service)
        url = self._build_url(base_url, endpoint, params)

        call_timeout = timeout or service.timeout or (get_rpc_config() or _DEFAULT_RPC_CFG).default_timeout

        http = await self._ensure_client()
        retry_cfg = service.retry or (get_rpc_config() or _DEFAULT_RPC_CFG).default_retry

        try:
            if retry_cfg.max_attempts > 1:
                resp = await self._request_with_retry(http, endpoint, url, params, call_timeout, retry_cfg.max_attempts)
            else:
                resp = await self._do_request(http, endpoint, url, params, call_timeout)
        except RpcError:
            raise
        except httpx.TimeoutException:
            raise RpcTimeoutError(f"RPC call to {service_name}.{method} timed out after {call_timeout}s")
        except httpx.ConnectError as e:
            raise RpcConnectionError(f"Connection failed to {url}: {e}") from e
        except Exception as e:
            raise RpcConnectionError(f"RPC call failed: {e}") from e

        if resp.status_code >= 400:
            body_text = resp.text[:1000]
            raise RpcError(
                f"RPC call to {service_name}.{method} returned {resp.status_code}: {body_text}",
                status_code=resp.status_code,
                body=body_text,
            )

        return resp.json() if resp.text else None

    async def call_raw(
        self,
        service_name: str,
        path: str,
        http_method: str = "GET",
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Call a Java RPC service with a raw path (no endpoint config lookup).

        Use this when the client code already knows the HTTP path and method,
        e.g. from a typed Python wrapper around a Java FeignClient.

        Args:
            service_name: Configured service name in config.yaml.
            path: Full HTTP path (e.g. /ins-bus-rpc/machineModel/getMachineInfoByIds).
            http_method: HTTP method (GET, POST, PUT, DELETE).
            params: Query string parameters (GET/DELETE) or request body (POST/PUT).
            timeout: Per-call timeout override in seconds.
            extra_headers: Additional HTTP headers to include in the request
                (e.g. Authorization for token forwarding).

        Returns:
            Parsed JSON response.

        Raises:
            RpcError: On 4xx/5xx responses.
            RpcConnectionError: On network errors.
            RpcTimeoutError: On timeout.
        """
        if params is None:
            params = {}

        service = self._get_service(service_name)
        base_url = await self._resolve_base_url(service)
        url = f"{base_url}{path}"

        call_timeout = timeout or service.timeout or (get_rpc_config() or _DEFAULT_RPC_CFG).default_timeout

        http = await self._ensure_client()
        retry_cfg = service.retry or (get_rpc_config() or _DEFAULT_RPC_CFG).default_retry

        # Build a synthetic endpoint just for _do_request
        endpoint = RpcEndpointConfig(method="__raw__", path=path, http_method=http_method)

        try:
            if retry_cfg.max_attempts > 1:
                resp = await self._request_with_retry(
                    http, endpoint, url, params, call_timeout, retry_cfg.max_attempts, extra_headers
                )
            else:
                resp = await self._do_request(http, endpoint, url, params, call_timeout, extra_headers)
        except RpcError:
            raise
        except httpx.TimeoutException:
            raise RpcTimeoutError(f"RPC call to {service_name}{path} timed out after {call_timeout}s")
        except httpx.ConnectError as e:
            raise RpcConnectionError(f"Connection failed to {url}: {e}") from e
        except Exception as e:
            raise RpcConnectionError(f"RPC call failed: {e}") from e

        if resp.status_code >= 400:
            body_text = resp.text[:1000]
            raise RpcError(
                f"RPC call to {service_name}{path} returned {resp.status_code}: {body_text}",
                status_code=resp.status_code,
                body=body_text,
            )

        return resp.json() if resp.text else None

    async def _do_request(
        self,
        http: httpx.AsyncClient,
        endpoint: RpcEndpointConfig,
        url: str,
        params: dict[str, Any],
        timeout: float,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        http_method = endpoint.http_method.upper()
        body_params = {k: v for k, v in params.items() if f"{{{k}}}" not in endpoint.path}
        if http_method == "GET":
            return await http.get(url, params=body_params, timeout=timeout, headers=extra_headers)
        elif http_method == "PUT":
            return await http.put(url, json=body_params, timeout=timeout, headers=extra_headers)
        elif http_method == "DELETE":
            return await http.delete(url, params=body_params, timeout=timeout, headers=extra_headers)
        else:
            return await http.post(url, json=body_params, timeout=timeout, headers=extra_headers)

    async def _request_with_retry(
        self,
        http: httpx.AsyncClient,
        endpoint: RpcEndpointConfig,
        url: str,
        params: dict[str, Any],
        timeout: float,
        max_attempts: int,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._do_request(http, endpoint, url, params, timeout, extra_headers)
            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e
                if attempt < max_attempts:
                    delay = min(0.5 * (2 ** (attempt - 1)), 10.0)
                    logger.warning(
                        "RPC call attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt, max_attempts, delay, e,
                    )
                    await asyncio.sleep(delay)
        raise RpcConnectionError(f"RPC call failed after {max_attempts} attempts") from last_error

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Default config for fallback when rpc config section is absent
_DEFAULT_RPC_CFG = RpcConfig()


# Singleton RPC client
_rpc_client: RpcClient | None = None


def get_rpc_client() -> RpcClient | None:
    """Get the singleton RPC client.

    Returns None if RPC is not configured.
    """
    global _rpc_client
    cfg = get_rpc_config()
    if cfg is None:
        return None
    if _rpc_client is None:
        _rpc_client = RpcClient()
    return _rpc_client
