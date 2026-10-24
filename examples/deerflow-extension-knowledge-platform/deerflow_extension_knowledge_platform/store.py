"""Transactional bounded policy snapshots, independent of host persistence."""

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from deerflow_extension_knowledge_management.contracts import ProcessingOptions

from .models import OPERATIONS, RANK, TOOLS, ConnectionPolicy, PlatformPolicy, Settings, Space, resource_key


class RevisionConflict(Exception):
    pass


def administrator(principal):
    if not principal.user_id or not principal.is_admin or principal.is_internal:
        raise PermissionError("Platform policy requires a human administrator")


def inherited_defaults(policies):
    values, default = {}, None
    for policy in policies:
        values.update(policy.processing.model_dump(exclude_none=True))
        if "default_tool" in policy.model_fields_set:
            default = policy.default_tool
    return values, default


@dataclass(frozen=True)
class _SpaceState:
    space_id: str
    space: Space
    parent: "_SpaceState | None"
    resources: frozenset[str]
    operations: frozenset[str]
    tools: frozenset[str]
    members: dict[str, str]
    enabled: bool
    default_tool: str | None
    default_overridden: bool


class _PolicyTree:
    """One snapshot only: reuse ancestor state, never cache grants across requests."""

    def __init__(self, policy, resources):
        self.policy, self.resources = policy, resources
        self.states, self.processing, self.groups, self.connection_defaults = {}, {}, {}, {}
        self.connections = {}
        for connection, _ in resources.values():
            if connection.id not in self.connections:
                self.connections[connection.id] = policy.connections.get(connection.id, ConnectionPolicy())

    def resolve(self, space_id):
        pending, visited = [], set()
        cursor = space_id
        while cursor is not None and cursor not in self.states:
            if cursor in visited or cursor not in self.policy.spaces:
                raise ValueError("Cyclic or missing space parent")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cursor):
                raise ValueError("Invalid space identity")
            visited.add(cursor)
            pending.append(cursor)
            cursor = self.policy.spaces[cursor].parent_id
        for key in reversed(pending):
            space = self.policy.spaces[key]
            parent = self.states.get(space.parent_id)
            if parent is None and space.resources is None:
                raise ValueError("Root requires an explicit resource envelope")
            values = {}
            for field, initial in (("resources", frozenset()), ("operations", OPERATIONS), ("tools", TOOLS)):
                ceiling = getattr(parent, field) if parent else initial
                value = getattr(space, field)
                if parent is not None and value is not None and not value <= ceiling:
                    raise ValueError(f"Child {field} exceed parent envelope")
                values[field] = ceiling if value is None else value
            members = dict(parent.members) if parent else {}
            if parent and any(RANK[role] > RANK[members.get(user, "blocked")] for user, role in space.members.items()):
                raise ValueError("Child membership exceeds ancestor grant")
            for user, role in space.members.items():
                if role == "blocked":
                    members.pop(user, None)
                else:
                    members[user] = role
            overridden = "default_tool" in space.model_fields_set
            self.states[key] = _SpaceState(
                space_id=key,
                space=space,
                parent=parent,
                **values,
                members=members,
                enabled=space.enabled and (parent.enabled if parent else True),
                default_tool=space.default_tool if overridden else (parent.default_tool if parent else None),
                default_overridden=overridden or (parent.default_overridden if parent else False),
            )
        return self.states[space_id]

    def resource_groups(self, selected):
        if selected not in self.groups:
            groups = {}
            for key in selected:
                if key not in self.resources:
                    raise ValueError("Unknown operator resource")
                connection, base = self.resources[key]
                previous = groups.get(connection.id, (connection, TOOLS))[1]
                groups[connection.id] = (connection, previous & base.tools)
            self.groups[selected] = groups
        return self.groups[selected]

    def default_tool(self, state, connection):
        if state.default_overridden:
            return state.default_tool
        cp = self.connections[connection]
        return cp.default_tool if "default_tool" in cp.model_fields_set else self.policy.defaults.default_tool

    def tools(self, state, connection):
        cp = self.connections[connection]
        return state.tools & (self.policy.defaults.tools if self.policy.defaults.tools is not None else TOOLS) & (cp.tools if cp.tools is not None else TOOLS)

    def defaults(self, state, connection):
        if connection not in self.connection_defaults:
            self.connection_defaults[connection] = inherited_defaults([self.policy.defaults, self.connections[connection]])[0]
        pending, cursor = [], state
        while cursor is not None and cursor.space_id not in self.processing:
            pending.append(cursor)
            cursor = cursor.parent
        values = self.processing[cursor.space_id] if cursor else {}
        for item in reversed(pending):
            values = {**values, **item.space.processing.model_dump(exclude_none=True)}
            self.processing[item.space_id] = values
        return {**self.connection_defaults[connection], **self.processing[state.space_id]}


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
        tree = _PolicyTree(policy, self.resources)
        for space_id in policy.spaces:
            state = tree.resolve(space_id)
            for connection, base_tools in tree.resource_groups(state.resources).values():
                ProcessingOptions.model_validate(tree.defaults(state, connection.id))
                default = tree.default_tool(state, connection.id)
                if default is not None and default not in tree.tools(state, connection.id) & base_tools:
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

    def _access(self, principal, space_id, tree):
        if not principal.user_id or principal.is_internal or not tree.policy.defaults.enabled:
            raise PermissionError("Space access denied")
        if space_id not in tree.policy.spaces:
            raise PermissionError("Space access denied")
        state = tree.resolve(space_id)
        role = state.members.get(principal.user_id, "blocked")
        if not state.enabled or not RANK[role]:
            raise PermissionError("Space access denied")
        try:
            groups = tree.resource_groups(state.resources)
        except ValueError:
            raise PermissionError("Space contains an unavailable operator resource") from None
        # Keep listing and detail admission identical after operator tool revocation.
        # Intersect base tools per connection without constructing resource responses.
        for connection, base_tools in groups.values():
            default = tree.default_tool(state, connection.id)
            if tree.connections[connection.id].enabled and default is not None and default not in tree.tools(state, connection.id) & base_tools:
                raise PermissionError("Space default tool is no longer available")
        return state, role

    def _effective(self, principal, space_id, revision, policy):
        tree = _PolicyTree(policy, self.resources)
        state, role = self._access(principal, space_id, tree)
        operations = state.operations & (policy.defaults.operations if policy.defaults.operations is not None else OPERATIONS)
        if role == "viewer":
            operations &= {"capabilities", "status"}
        items, defaults = [], {}
        for key in sorted(state.resources):
            conn, base = self.resources[key]
            cp = tree.connections[conn.id]
            if not cp.enabled:
                continue
            if conn.id not in defaults:
                defaults[conn.id] = tree.defaults(state, conn.id)
            resource_tools = tree.tools(state, conn.id) & base.tools
            items.append(
                {
                    "resource_id": key,
                    "provider": conn.provider,
                    "connection_id": conn.id,
                    "native_base_id": base.base_id,
                    "dataset_id": base.dataset_id,
                    "operations": sorted(operations & base.operations & (cp.operations if cp.operations is not None else OPERATIONS)),
                    "tools": sorted(resource_tools),
                    "default_tool": tree.default_tool(state, conn.id),
                    "processing": defaults[conn.id],
                }
            )
        return {"version": 1, "revision": revision, "space_id": space_id, "title": state.space.title, "role": role, "resources": items}

    def effective(self, principal, space_id):
        with closing(self.connect()) as db:
            revision, policy = self._snapshot(db)
        return self._effective(principal, space_id, revision, policy)

    def spaces(self, principal):
        with closing(self.connect()) as db:
            revision, policy = self._snapshot(db)
        tree = _PolicyTree(policy, self.resources)
        items = []
        for space_id in policy.spaces:
            try:
                state, role = self._access(principal, space_id, tree)
            except PermissionError:
                continue
            items.append({"space_id": space_id, "title": state.space.title, "role": role})
        return {"revision": revision, "items": items}
