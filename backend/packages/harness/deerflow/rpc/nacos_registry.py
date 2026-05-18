"""Nacos service registry client.

Uses the Nacos Open API directly (no SDK dependency) for service
registration, heartbeat, and service discovery.
"""

import asyncio
import logging
import socket
from urllib.parse import urlencode

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from deerflow.config.nacos_config import NacosConfig, get_nacos_config

logger = logging.getLogger(__name__)


class NacosRegistry:
    """Registry client for Nacos service discovery.

    Manages service instance registration, heartbeat, and service
    discovery lookups via the Nacos Open API.
    """

    def __init__(self, config: NacosConfig):
        self._config = config
        self._base_url = f"http://{config.server_addr}/nacos/v1"
        self._http: httpx.AsyncClient | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    def _resolve_ip(self) -> str:
        if self._config.service.ip:
            return self._config.service.ip
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return socket.gethostbyname(socket.gethostname())

    def _build_instance_params(self) -> dict[str, str]:
        svc = self._config.service
        ip = self._resolve_ip()
        params: dict[str, str] = {
            "serviceName": f"{self._config.group}@@{svc.name}",
            "ip": ip,
            "port": str(svc.port),
            "namespaceId": self._config.namespace,
            "weight": str(svc.weight),
            "healthy": "true",
            "enabled": "true",
            "ephemeral": "true",
        }
        for k, v in svc.metadata.items():
            params[f"metadata.{k}"] = v
        return params

    async def register(self) -> bool:
        """Register this service instance with Nacos.

        Returns True on success.
        """
        http = await self._ensure_client()
        params = self._build_instance_params()
        url = f"{self._base_url}/ns/instance"
        logger.info(
            "Registering service %s with Nacos at %s",
            self._config.service.name,
            self._config.server_addr,
        )
        try:
            resp = await http.post(url, params=params)
            if resp.status_code == 200 and resp.text == "ok":
                self._registered = True
                logger.info("Nacos registration successful")
                return True
            logger.warning("Nacos registration returned: %s %s", resp.status_code, resp.text)
            return False
        except Exception:
            logger.exception("Nacos registration failed")
            return False

    async def deregister(self) -> bool:
        """Deregister this service instance from Nacos.

        Returns True on success.
        """
        if not self._registered:
            return True
        http = await self._ensure_client()
        params = self._build_instance_params()
        url = f"{self._base_url}/ns/instance"
        logger.info("Deregistering service from Nacos")
        try:
            resp = await http.delete(url, params=params)
            self._registered = False
            logger.info("Nacos deregistration complete")
            return resp.status_code == 200
        except Exception:
            logger.exception("Nacos deregistration failed")
            return False

    async def send_heartbeat(self) -> bool:
        """Send a heartbeat to Nacos for this instance.

        Returns True on success.
        """
        if not self._registered:
            return False
        http = await self._ensure_client()
        svc = self._config.service
        ip = self._resolve_ip()
        query = urlencode({
            "serviceName": f"{self._config.group}@@{svc.name}",
            "ip": ip,
            "port": str(svc.port),
            "namespaceId": self._config.namespace,
            "ephemeral": "true",
            "beat": '{"ip":"%s","port":%d,"weight":%s}' % (ip, svc.port, svc.weight),
        })
        url = f"{self._base_url}/ns/instance/beat?{query}"
        try:
            resp = await http.put(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def _heartbeat_loop(self) -> None:
        """Background heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self._config.heartbeat.interval)
                if self._running and self._registered:
                    ok = await self.send_heartbeat()
                    if not ok:
                        logger.warning("Nacos heartbeat failed")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Nacos heartbeat error")

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._running = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def start(self) -> None:
        """Register and start heartbeat with retry on failure."""
        self._running = True
        if self._config.retry.max_attempts > 0:
            await self._register_with_retry()
        else:
            await self.register()
        if self._registered:
            self._start_heartbeat()

    async def _register_with_retry(self) -> None:
        """Register with exponential backoff retry."""
        r = self._config.retry
        for attempt in range(1, r.max_attempts + 1):
            ok = await self.register()
            if ok:
                return
            delay = min(r.base_delay * (2 ** (attempt - 1)), r.max_delay)
            logger.warning(
                "Nacos registration attempt %d/%d failed, retrying in %.1fs",
                attempt,
                r.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
        logger.error("Nacos registration exhausted all %d retry attempts", r.max_attempts)

    async def stop(self) -> None:
        """Deregister and stop heartbeat."""
        await self._stop_heartbeat()
        await self.deregister()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def discover_service(self, service_name: str) -> list[dict]:
        """Query Nacos for healthy instances of a service.

        Returns a list of instance dicts with ip, port, weight, etc.
        """
        http = await self._ensure_client()
        cfg = self._config
        params = {
            "serviceName": f"{cfg.group}@@{service_name}",
            "namespaceId": cfg.namespace,
            "healthyOnly": "true",
        }
        url = f"{self._base_url}/ns/instance/list"
        try:
            resp = await http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                hosts = data.get("hosts", [])
                if hosts:
                    logger.debug("Nacos discovery found %d instance(s) for %s", len(hosts), service_name)
                return [
                    {
                        "ip": h["ip"],
                        "port": h["port"],
                        "weight": h.get("weight", 1.0),
                        "healthy": h.get("healthy", True),
                    }
                    for h in hosts
                ]
            logger.warning("Nacos discovery for %s returned: %s", service_name, resp.status_code)
        except Exception:
            logger.exception("Nacos discovery failed for %s", service_name)
        return []
