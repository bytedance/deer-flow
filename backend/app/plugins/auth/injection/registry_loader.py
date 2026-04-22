"""Load auth route policies from the plugin's YAML registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from starlette.routing import compile_path
import yaml

_POLICY_FILE = Path(__file__).resolve().parents[1] / "route_policies.yaml"


@dataclass(frozen=True)
class RoutePolicySpec:
    public: bool = False
    capability: str | None = None
    policies: tuple[str, ...] = ()
    require_existing: bool = True


@dataclass(frozen=True)
class RoutePolicyEntry:
    method: str
    path: str
    spec: RoutePolicySpec
    path_regex: object = field(repr=False)

    def matches_request(self, method: str, path: str) -> bool:
        if self.method != method.upper():
            return False
        return self.path_regex.match(path) is not None


class RoutePolicyRegistry:
    def __init__(self, entries: list[RoutePolicyEntry]) -> None:
        self._entries = entries
        self._specs = {(entry.method, entry.path): entry.spec for entry in entries}

    def get(self, method: str, path_template: str) -> RoutePolicySpec | None:
        return self._specs.get((method.upper(), path_template))

    def has(self, method: str, path_template: str) -> bool:
        return (method.upper(), path_template) in self._specs

    def match_request(self, method: str, path: str) -> RoutePolicySpec | None:
        normalized_method = method.upper()
        for entry in self._entries:
            if entry.matches_request(normalized_method, path):
                return entry.spec
        return None

    def is_public_request(self, method: str, path: str) -> bool:
        spec = self.match_request(method, path)
        return bool(spec and spec.public)

    @property
    def keys(self) -> set[tuple[str, str]]:
        return set(self._specs)


def _normalize_methods(item: dict) -> tuple[str, ...]:
    methods = item.get("methods")
    if methods is None:
        methods = [item["method"]]
    if isinstance(methods, str):
        methods = [methods]
    return tuple(str(method).upper() for method in methods)


def _build_spec(item: dict) -> RoutePolicySpec:
    return RoutePolicySpec(
        public=bool(item.get("public", False)),
        capability=item.get("capability"),
        policies=tuple(item.get("policies", [])),
        require_existing=bool(item.get("require_existing", True)),
    )


def load_route_policy_registry() -> RoutePolicyRegistry:
    payload = yaml.safe_load(_POLICY_FILE.read_text(encoding="utf-8")) or {}
    raw_routes: list[dict] = []
    for section, entries in payload.items():
        if section == "routes":
            if isinstance(entries, list):
                raw_routes.extend(entries)
            continue
        if not isinstance(entries, list):
            continue
        for item in entries:
            normalized = dict(item)
            if section == "public":
                normalized["public"] = True
            raw_routes.append(normalized)
    entries: list[RoutePolicyEntry] = []
    for item in raw_routes:
        path = str(item["path"])
        spec = _build_spec(item)
        path_regex, _, _ = compile_path(path)
        for method in _normalize_methods(item):
            entries.append(
                RoutePolicyEntry(
                    method=method,
                    path=path,
                    spec=spec,
                    path_regex=path_regex,
                )
            )
    return RoutePolicyRegistry(entries)


__all__ = ["RoutePolicyRegistry", "RoutePolicySpec", "load_route_policy_registry"]
