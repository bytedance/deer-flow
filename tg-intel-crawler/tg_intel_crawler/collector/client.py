import asyncio
import logging
from pathlib import Path

import yaml
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

logger = logging.getLogger("tg_crawler")


class TGClient:
    """Wrapper around Telethon's TelegramClient with auto-reconnect."""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        tg_cfg = config["telegram"]
        self._api_id = tg_cfg["api_id"]
        self._api_hash = tg_cfg["api_hash"]
        self._phone = tg_cfg["phone"]
        session_name = tg_cfg.get("session_name", "crawler_session")
        session_path = str(Path(config_path).parent / session_name)

        proxy = self._build_proxy(tg_cfg.get("proxy"))
        if proxy:
            logger.info(
                f"Using proxy: {proxy[0]}://{proxy[1]}:{proxy[2]}"
            )

        self._client = TelegramClient(
            session_path, self._api_id, self._api_hash, proxy=proxy
        )
        self._client.flood_sleep_threshold = 60

    @staticmethod
    def _build_proxy(proxy_cfg):
        """Build a Telethon-compatible proxy tuple from config.

        Expected config shape:
            proxy:
              type: socks5  # or socks4, http
              host: 127.0.0.1
              port: 7897
              username: optional
              password: optional

        Returns None if no proxy configured.
        """
        if not proxy_cfg:
            return None

        try:
            import socks  # provided by pysocks
        except ImportError as exc:
            raise RuntimeError(
                "Proxy configured but 'pysocks' is not installed. "
                "Run: pip install pysocks"
            ) from exc

        type_map = {
            "socks5": socks.SOCKS5,
            "socks4": socks.SOCKS4,
            "http": socks.HTTP,
        }
        proxy_type_name = str(proxy_cfg.get("type", "socks5")).lower()
        if proxy_type_name not in type_map:
            raise ValueError(
                f"Unsupported proxy type: {proxy_type_name}. "
                f"Use one of: {list(type_map)}"
            )

        host = proxy_cfg["host"]
        port = int(proxy_cfg["port"])
        username = proxy_cfg.get("username")
        password = proxy_cfg.get("password")

        if username and password:
            return (type_map[proxy_type_name], host, port, True, username, password)
        return (type_map[proxy_type_name], host, port)

    @property
    def client(self) -> TelegramClient:
        return self._client

    async def connect(self) -> None:
        """Connect and authenticate. Interactive on first run."""
        await self._client.connect()

        if not await self._client.is_user_authorized():
            logger.info("First-time login required.")
            await self._client.send_code_request(self._phone)
            code = input(f"Enter the code sent to {self._phone}: ")
            try:
                await self._client.sign_in(self._phone, code)
            except SessionPasswordNeededError:
                password = input("Two-factor auth enabled. Enter password: ")
                await self._client.sign_in(password=password)

        me = await self._client.get_me()
        logger.info(f"Logged in as: {me.first_name} (ID: {me.id})")

    async def disconnect(self) -> None:
        """Disconnect the client."""
        await self._client.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()
