from collections import OrderedDict
from copy import deepcopy
from time import monotonic


class ReadmeCache:
    """带过期时间和容量限制的内存缓存。"""

    def __init__(
        self,
        ttl_seconds: float = 300,
        max_entries: int = 16,
        clock=monotonic,
    ):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("缓存有效期和容量必须大于 0。")

        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries = OrderedDict()

    def _remove_expired(self):
        now = self.clock()
        expired_keys = [
            key
            for key, (expires_at, _) in self._entries.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            del self._entries[key]

    def get(self, key: str) -> dict | None:
        self._remove_expired()

        if key not in self._entries:
            return None

        _, value = self._entries[key]

        # 最近访问的条目移到末尾。
        self._entries.move_to_end(key)

        # 返回副本，避免调用方意外修改缓存。
        return deepcopy(value)

    def set(self, key: str, value: dict):
        self._remove_expired()

        self._entries[key] = (
            self.clock() + self.ttl_seconds,
            deepcopy(value),
        )
        self._entries.move_to_end(key)

        # 超过容量时，淘汰最久没有访问的条目。
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self):
        self._entries.clear()