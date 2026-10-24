"""Transactional bounded policy snapshots, independent of host persistence."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from deerflow_extension_knowledge_management.contracts import ProcessingOptions

from .models import OPERATIONS, RANK, TOOLS, ConnectionPolicy, PlatformPolicy, Settings, resource_key


class RevisionConflict(Exception):
    pass


def administrator(principal):
    if not principal.user_id or not principal.is_admin or principal.is_internal:
        raise PermissionError("Platform policy requires a human administrator")


def chain(policy, space_id):
    result, visited = [], set()
    while space_id is not None:
        if space_id in visited or space_id not in policy.spaces:
            raise ValueError("Cyclic or missing space parent")
        visited.add(space_id)
        space = policy.spaces[space_id]
        result.append((space_id, space))
        space_id = space.parent_id
    return list(reversed(result))


def bounds(path):
    resources, operations, tools = None, OPERATIONS, TOOLS
    for _, space in path:
        if space.resources is not None:
            if resources is not None and not space.resources <= resources:
                raise ValueError("Child resources exceed parent envelope")
            resources = space.resources
        if space.operations is not None:
            if not space.operations <= operations:
                raise ValueError("Child operations exceed parent envelope")
            operations = space.operations
        if space.tools is not None:
            if not space.tools <= tools:
                raise ValueError("Child tools exceed parent envelope")
            tools = space.tools
    return resources or frozenset(), operations, tools


def inherited_defaults(policies):
    values, default = {}, None
    for policy in policies:
        values.update(policy.processing.model_dump(exclude_none=True))
        if "default_tool" in policy.model_fields_set:
            default = policy.default_tool
    return values, default


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = Path(settings.storage_path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        self.resources = {resource_key(c.provider, c.id, r.base_id): (c, r) for c in settings.connections for r in c.resources}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS platform_policy (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO platform_policy VALUES (1, 0, ?)", (PlatformPolicy().model_dump_json(),))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _snapshot(self, db):
        revision, data = db.execute("SELECT revision, data FROM platform_policy WHERE id=1").fetchone()
        policy = PlatformPolicy.model_validate_json(data)
        return revision, policy

    def validate(self, policy):
        if not policy.connections.keys() <= {c.id for c in self.settings.connections}:
            raise ValueError("Unknown operator connection")
        for space_id, space in policy.spaces.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", space_id):
                raise ValueError("Invalid space identity")
            path = chain(policy, space_id)
            if path[0][1].resources is None:
                raise ValueError("Root requires an explicit resource envelope")
            resources, _, space_tools = bounds(path)
            if not resources <= self.resources.keys():
                raise ValueError("Unknown operator resource")
            # An explicit child grant can narrow an inherited grant, never add one.
            roles = {}
            for index, (_, ancestor) in enumerate(path):
                for user, role in ancestor.members.items():
                    if index and RANK[role] > RANK[roles.get(user, "blocked")]:
                        raise ValueError("Child membership exceeds ancestor grant")
                    roles[user] = role
            for resource in resources:
                conn, base = self.resources[resource]
                connection_policy = policy.connections.get(conn.id, ConnectionPolicy())
                values, default = inherited_defaults([policy.defaults, connection_policy, *(ancestor for _, ancestor in path)])
                tools = space_tools & base.tools & (connection_policy.tools if connection_policy.tools is not None else TOOLS) & (policy.defaults.tools if policy.defaults.tools is not None else TOOLS)
                ProcessingOptions.model_validate(values)
                if default is not None and default not in tools:
                    raise ValueError("Default tool is outside the effective tool envelope")

    def read(self, principal):
        administrator(principal)
        with closing(self.connect()) as db:
            revision, policy = self._snapshot(db)
        # Operator configuration, endpoints and credential references never leave Store.
        return {
            "revision": revision,
            "policy": policy.model_dump(mode="json", exclude_unset=True),
            "unavailable_resources": sorted({resource for space in policy.spaces.values() for resource in (space.resources or ()) if resource not in self.resources}),
            "resources": [{"resource_id": key, "provider": c.provider, "connection_id": c.id, "native_base_id": r.base_id, "dataset_id": r.dataset_id} for key, (c, r) in self.resources.items()],
        }

    def replace(self, principal, data, expected_revision):
        administrator(principal)
        policy = PlatformPolicy.model_validate(data)
        self.validate(policy)
        # Preserve absent-vs-null default_tool semantics across persistence/round trips.
        serialized = policy.model_dump_json(exclude_unset=True)
        if len(serialized.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Policy exceeds 1 MiB")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            revision = db.execute("SELECT revision FROM platform_policy WHERE id=1").fetchone()[0]
            if revision != expected_revision:
                raise RevisionConflict("Policy changed; reload before retrying")
            db.execute("UPDATE platform_policy SET revision=?, data=? WHERE id=1", (revision + 1, serialized))
        return {"revision": revision + 1, "policy": json.loads(serialized)}

    def _effective(self, principal, space_id, revision, policy):
        if not principal.user_id or principal.is_internal or not policy.defaults.enabled:
            raise PermissionError("Space access denied")
        if space_id not in policy.spaces:
            raise PermissionError("Space access denied")
        path = chain(policy, space_id)
        role = "blocked"
        for _, space in path:
            role = space.members.get(principal.user_id, role)
            if not space.enabled:
                raise PermissionError("Space access denied")
        if not RANK[role]:
            raise PermissionError("Space access denied")
        selected, operations, tools = bounds(path)
        if not selected <= self.resources.keys():
            raise PermissionError("Space contains an unavailable operator resource")
        operations &= policy.defaults.operations if policy.defaults.operations is not None else OPERATIONS
        tools &= policy.defaults.tools if policy.defaults.tools is not None else TOOLS
        if role == "viewer":
            operations &= {"capabilities", "status"}
        items = []
        for key in sorted(selected):
            conn, base = self.resources[key]
            cp = policy.connections.get(conn.id, ConnectionPolicy())
            if not cp.enabled:
                continue
            values, default = inherited_defaults([policy.defaults, cp, *(space for _, space in path)])
            resource_tools = tools & base.tools & (cp.tools if cp.tools is not None else TOOLS)
            if default is not None and default not in resource_tools:
                raise PermissionError("Space default tool is no longer available")
            items.append(
                {
                    "resource_id": key,
                    "provider": conn.provider,
                    "connection_id": conn.id,
                    "native_base_id": base.base_id,
                    "dataset_id": base.dataset_id,
                    "operations": sorted(operations & base.operations & (cp.operations if cp.operations is not None else OPERATIONS)),
                    "tools": sorted(resource_tools),
                    "default_tool": default,
                    "processing": values,
                }
            )
        return {"version": 1, "revision": revision, "space_id": space_id, "title": path[-1][1].title, "role": role, "resources": items}

    def effective(self, principal, space_id):
        with closing(self.connect()) as db:
            revision, policy = self._snapshot(db)
        return self._effective(principal, space_id, revision, policy)

    def spaces(self, principal):
        with closing(self.connect()) as db:
            revision, policy = self._snapshot(db)
        items = []
        for space_id in policy.spaces:
            try:
                effective = self._effective(principal, space_id, revision, policy)
            except PermissionError:
                continue
            items.append({key: effective[key] for key in ("space_id", "title", "role")})
        return {"revision": revision, "items": items}
