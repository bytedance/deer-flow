"""OpenViking memory backend -- embedded in-process :class:`MemoryManager`.

See ``__init__.py`` for the architecture overview. This module implements the
:class:`MemoryManager` ABC against an embedded OpenViking client
(``openviking.OpenViking(path=...)``).

Portability golden rule (see ``backends/noop/config.py``): the ONLY
``from deerflow`` import in this folder is the ABC contract line below. All host
info arrives through the ABC method args + ``backend_config``; ``storage_path``
is host-injected into ``backend_config`` (never import a deer-flow path helper).

Write strategy = **session pipeline**: :meth:`add` ingests a conversation via
OpenViking's session API (``create_session`` + ``add_message`` +
``commit_session``). The commit archives the session and runs memory extraction
(the VLM configured in ``~/.openviking/ov.conf``), which distills the
conversation into structured memories (preferences / entities / profile / ...)
under ``viking://user/{space}/memories/``. The backend never stores raw
transcripts -- it surfaces OpenViking's extracted memories (short L2 abstracts)
to deerflow. Manual facts (``create_fact`` / ``import_memory``) are written
directly under ``memories/{category}/`` with a ``DEERFLOW_META`` comment.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import PrivateAttr

# ABC contract -- the ONE allowed `from deerflow` in this backend folder.
# Change this single line (to the other agent's MemoryManager) to port.
from deerflow.agents.memory.manager import MemoryManager, MemoryManagerError

from .config import OpenVikingConfig

logger = logging.getLogger(__name__)

# Trailing metadata block OpenViking appends to memory files
# (``<!-- MEMORY_FIELDS {...} -->``). Stripped when surfacing content to deerflow.
_MEMORY_FIELDS_RE = re.compile(r"\n*<!--\s*MEMORY_FIELDS.*?-->\s*$", re.DOTALL)

# OpenViking's derived/hidden companion files (L0/L1/relations) -- excluded from
# memory listings. ``ls(show_all_hidden=False)`` already hides them, but we also
# filter by basename as a belt-and-suspenders guard.
_DERIVED_BASENAMES = {".abstract.md", ".overview.md", ".relations.json"}

# No template filtering -- OpenViking's identity.md / soul.md / profile.md are
# all legitimate memory types (enabled in the schema).  They start as templates
# and get filled by extraction or agent onboarding; showing them is correct.


def _empty_memory() -> dict[str, Any]:
    """A fresh empty memory document (DeerMem-shape; gateway fills defaults)."""
    now = datetime.now(UTC).isoformat()
    return {"version": "1.0", "lastUpdated": now, "user": {}, "history": {}, "facts": [], "display": {"sections": []}}


def _strip_memory_fields(text: str) -> str:
    """Remove the trailing ``<!-- MEMORY_FIELDS ... -->`` metadata block."""
    if not text:
        return ""
    return _MEMORY_FIELDS_RE.sub("", text).rstrip()


def _usable_abstract(text: str | None) -> str:
    """Return an L0 abstract if it is a real summary, else ``""``.

    When auto L0 generation is off (no VLM), OpenViking's ``abstract()`` returns
    a parent-directory placeholder like ``"# viking://... [Directory abstract is
    not ready]"`` rather than an empty string. Detect and discard those so the
    caller falls back to ``read()`` (full content).
    """
    if not text or not text.strip():
        return ""
    t = text.strip()
    low = t.lower()
    if "not ready" in low or "directory abstract" in low or t.startswith("# viking://"):
        return ""
    return t


def _slugify(text: str, maxlen: int = 40) -> str:
    """Make a filesystem-safe slug from text (for memory file names)."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text).strip("-")
    if not text:
        text = "memory"
    return text[:maxlen].rstrip("-") or "memory"


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or msg.get("type") or "message")
    return str(getattr(msg, "role", None) or getattr(msg, "type", None) or "message")


def _message_content_text(msg: Any) -> str:
    """Extract a plain-text body from a langchain/deerflow message."""
    if isinstance(msg, dict):
        content = msg.get("content")
    else:
        content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # Multimodal content: list of parts ({"type": "text", "text": ...}, etc.)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "\n".join(p for p in parts if p)
    return str(content)


def _is_hidden_message(msg: Any) -> bool:
    """True if the message is marked ``hide_from_ui`` (and should be skipped)."""
    if isinstance(msg, dict):
        add_kw = msg.get("additional_kwargs") or {}
    else:
        add_kw = getattr(msg, "additional_kwargs", None) or {}
    return bool(add_kw.get("hide_from_ui"))


def _ctx_get(ctx: Any, key: str, default: Any = None) -> Any:
    """Read a field from a MatchedContext that may be a dataclass or a dict."""
    if hasattr(ctx, key):
        return getattr(ctx, key)
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return default


def _all_contexts(result: Any) -> list[Any]:
    """Flatten a FindResult (memories + resources + skills) into one list.

    Embedded ``find`` returns a typed ``FindResult`` dataclass; defensively also
    handle a plain dict.
    """
    out: list[Any] = []
    for attr in ("memories", "resources", "skills"):
        vals = getattr(result, attr, None)
        if vals:
            out.extend(vals)
    if not out and isinstance(result, dict):
        for key in ("memories", "resources", "skills"):
            out.extend(result.get(key, []) or [])
    return out


# ── Fact-id encoding ────────────────────────────────────────────────────
# Fact ids surfaced to the frontend are base64url(URI). The raw viking URI
# contains '/' and ':', and FastAPI's ``/memory/facts/{fact_id}`` route cannot
# capture them: Starlette decodes %2F back to '/' so the path 404s (verified).
# base64url's alphabet (A-Za-z0-9-_) has no '/'/':' so a URI survives a round
# trip through the URL path. ``_decode_fact_id`` also accepts a raw ``viking://``
# URI so manual/debug calls still work.


def _encode_fact_id(uri: str) -> str:
    return base64.urlsafe_b64encode(uri.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_fact_id(fact_id: str) -> str:
    """Resolve a frontend fact id back to a viking URI (base64url or raw)."""
    if not fact_id:
        return fact_id
    if fact_id.startswith("viking://"):
        return fact_id
    try:
        pad = "=" * (-len(fact_id) % 4)
        dec = base64.urlsafe_b64decode(fact_id + pad).decode("utf-8")
        if dec.startswith("viking://"):
            return dec
    except (ValueError, UnicodeDecodeError):
        pass
    return fact_id  # let the client raise if this is not a real URI


# ── Per-file metadata ───────────────────────────────────────────────────
# OpenViking preserves raw file content verbatim and appends its own trailing
# ``<!-- MEMORY_FIELDS ... -->``. We prepend our own ``DEERFLOW_META`` comment
# so get_memory can recover category / createdAt / source / confidence without
# inferring them from the URI (which breaks once _add nests files under a
# ``{thread_id}`` subdir -- parts[-2] is the thread_id, not the category).
# ``read()`` returns the raw file, so the comment round-trips. Values must not
# contain ``}`` (flat meta only) -- the non-greedy regex stops at the first ``}``.

_DEERFLOW_META_RE = re.compile(r"<!--\s*DEERFLOW_META\s+(\{.*?\})\s*-->\s*\n?", re.DOTALL)


def _build_meta_comment(meta: dict[str, Any]) -> str:
    return f"<!-- DEERFLOW_META {json.dumps(meta, ensure_ascii=False)} -->\n"


def _split_meta(text: str) -> tuple[str, dict[str, Any] | None]:
    """Return (content_without_meta, meta_dict_or_None) from raw file text."""
    if not text:
        return "", None
    m = _DEERFLOW_META_RE.search(text)
    if not m:
        return text, None
    try:
        meta = json.loads(m.group(1))
        if not isinstance(meta, dict):
            meta = None
    except (ValueError, TypeError):
        meta = None
    content = _DEERFLOW_META_RE.sub("", text, count=1)
    return content, meta


def _looks_like_uuid(segment: str) -> bool:  # pragma: no cover - retained for back-compat/debug
    """True if a URI path segment looks like a thread_id (UUID or hex uuid12).

    Unused since the session-pipeline redesign (categories are now the segment
    after ``memories/``); kept for external/debug use.
    """
    s = segment.lower()
    if len(s) == 36 and s.count("-") == 4:
        return all(c in "0123456789abcdef-" for c in s)
    # uuid12 hex tail used by create_fact / import_memory.
    return len(s) in (12, 8) and all(c in "0123456789abcdef" for c in s)


def _dedup_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate facts (same category + normalized content).

    ``_add`` re-extracts the full conversation each time there are new messages
    (for reliable extraction), which produces duplicate facts across sessions.
    OpenViking 0.4.11 has no config-enabled hard dedup, so collapse exact
    content duplicates here for the panel/search view. Conflicts (Python vs
    Rust -- different content) are NOT merged (need semantic consolidation).
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for f in facts:
        key = (str(f.get("category", "")).strip().lower(), str(f.get("content", "")).strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


class OpenVikingMemoryManager(MemoryManager):
    """Memory backend backed by an embedded OpenViking store.

    OpenViking owns embedding, L0/L1/L2 summarization, and retrieval; this
    backend only translates the deerflow :class:`MemoryManager` contract into
    OpenViking file/URI operations (``write`` / ``find`` / ``ls`` / ``read`` /
    ``rm``).
    """

    # Parsed config + OpenViking client + URI roots (PrivateAttr: not validated
    # / serialized pydantic fields). storage_path comes from backend_config
    # (host-injected) -- never import a deer-flow path helper.
    _config: Any = PrivateAttr(default=None)
    _client: Any = PrivateAttr(default=None)
    _memories_base: str = PrivateAttr(default="")
    _data_path: str = PrivateAttr(default="")
    _actor: str = PrivateAttr(default="")
    _init_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    # Per-thread content-hash set of messages already ingested this process.
    # add() receives the full (growing) history each debounced call; without
    # dedup each call would re-extract the whole conversation -> duplicate
    # memories. Hashing (role+content) means each message is extracted once.
    # On restart the set resets (residual dups are handled by OpenViking's
    # consolidation, enabled via enable_memory_decay in ov.conf).
    # Per-thread content-hash sets are capped so the in-memory dedup dict
    # does not grow without bound in long-running multi-tenant deployments.
    _MAX_SEEN_PER_THREAD: int = 4096
    # FIFO-ordered insert-tracking dicts (Python 3.7+ dict preserves insertion
    # order) so eviction drops the *oldest* entries — the most recent 4096
    # message hashes survive and dedup remains effective at high message counts.
    _seen_msgs: dict[str, dict[str, int]] = PrivateAttr(default_factory=dict)

    # search() is overridden -- supports_search is auto-derived by __init_subclass__

    # ── Construction / lifecycle ─────────────────────────────────────────
    def model_post_init(self, __context: Any) -> None:
        self._config = OpenVikingConfig.from_backend_config(self.backend_config)
        self._memories_base = f"viking://user/{self._config.user_space}/memories"
        self._data_path = self._config.resolve_data_path()
        self._actor = self._config.actor_peer_id or self._config.user_space
        # If providers are configured in backend_config (embedding/vlm/ov_conf),
        # generate <data_path>/ov.conf so EVERYTHING lives in deerflow's config --
        # no separate ~/.openviking/ov.conf, no `openviking-server init`. OpenViking
        # reads it via the OPENVIKING_CONFIG_FILE env var (overrides the default
        # ~/.openviking/ov.conf). If no providers configured, fall back to
        # ~/.openviking/ov.conf (legacy).
        if self._config.has_providers:
            self._write_ov_conf()
        # `import openviking` is lazy so the backend registers without the extra
        # installed. The factory's ensure_backend_deps() installs it (when
        # allow_lazy_installs is true) before from_config; this check is a safety
        # net with a clear error. The client itself is constructed lazily in
        # _ensure_ready() so a missing/misconfigured ov.conf surfaces at first
        # use / warm(), not at deerflow startup.
        try:
            import openviking as ov  # noqa: F401
        except ImportError as exc:  # pragma: no cover - clear user-facing error
            raise MemoryManagerError("The 'openviking' package is required for the openviking memory backend. Set memory.allow_lazy_installs: true in config.yaml to auto-install on first use, or run: uv pip install openviking") from exc
        logger.info(
            "OpenViking memory backend configured: space=%r data_path=%s (client constructed lazily on first use)",
            self._config.user_space,
            self._data_path,
        )

    def _write_ov_conf(self) -> None:
        """Write ``<data_path>/ov.conf`` from backend_config + point OpenViking at it.

        Assembles the ov.conf (raw ``ov_conf`` + embedding/vlm shortcuts + backend
        defaults) and sets ``OPENVIKING_CONFIG_FILE`` so the embedded client reads
        this file instead of ``~/.openviking/ov.conf``.
        """
        ov_conf_path = os.path.join(self._data_path, "ov.conf")
        conf = self._config.build_ov_conf()
        try:
            fd = os.open(ov_conf_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            raise MemoryManagerError(f"Failed to write OpenViking config {ov_conf_path}: {exc}") from exc
        # NOTE: This mutates process-global os.environ. The OpenViking SDK
        # only reads the config path from this env var at construction time
        # (no constructor argument accepts a config path). In a single-backend
        # process (the normal case) this is safe. If reset_memory_manager()
        # creates a fresh instance without providers, the stale env var is
        # harmless (OpenViking reads the file, which still exists). If a
        # different backend is selected after reset, the env var is ignored
        # (only the OpenViking SDK reads it).
        os.environ["OPENVIKING_CONFIG_FILE"] = ov_conf_path
        logger.info("OpenViking config generated from backend_config -> %s", ov_conf_path)

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> OpenVikingMemoryManager:
        """Build a wired instance from backend config + host hooks.

        Consumes the ``should_keep_hidden_message`` host hook (stashed into
        ``backend_config`` so :meth:`model_post_init` picks it up via the config
        parser) and the ``callbacks`` tracing hook.
        """
        cfg = dict(backend_config or {})
        # Host hooks arrive as kwargs, NOT in backend_config. Fold the
        # hidden-message filter into backend_config so OpenVikingConfig parses it.
        if "should_keep_hidden_message" in host_hooks and "should_keep_hidden_message" not in cfg:
            cfg["should_keep_hidden_message"] = host_hooks["should_keep_hidden_message"]
        callbacks = host_hooks.get("callbacks")
        return cls(backend_config=cfg, mode=mode, callbacks=callbacks)

    def _ensure_ready(self) -> None:
        """Construct + initialize the OpenViking client once (thread-safe).

        Construction is deferred to here (not ``model_post_init``) because
        ``OpenViking(path=...)`` reads ``~/.openviking/ov.conf`` at construction
        time -- so a missing/misconfigured ov.conf surfaces as a
        :class:`MemoryManagerError` at first use / :meth:`warm`, not at deerflow
        startup. Idempotent: a successful init is not repeated.
        """
        if self._client is not None and getattr(self._client, "_initialized", False):
            return
        with self._init_lock:
            if self._client is None:
                try:
                    import openviking as ov

                    self._client = ov.OpenViking(path=self._data_path, actor_peer_id=self._actor)
                except MemoryManagerError:
                    raise
                except Exception as exc:
                    raise MemoryManagerError("OpenViking client construction failed. Configure ~/.openviking/ov.conf first (run `openviking-server init`): " + str(exc)) from exc
            if not getattr(self._client, "_initialized", False):
                try:
                    self._client.initialize()
                except Exception as exc:
                    raise MemoryManagerError("OpenViking initialize() failed: " + str(exc)) from exc

    def _scope_base(self, agent_name: str | None) -> str:  # pragma: no cover - retained for back-compat/debug
        """URI root for one agent's memories (unused since the session-pipeline redesign).

        OpenViking memories are user-level (under ``memories/`` directly), not
        agent-scoped. Kept only so external callers/debugging that reach for it
        still resolve to a sensible URI.
        """
        scope = agent_name or "_global"
        return f"{self._memories_base}/{scope}"

    def _safe_mkdir(self, uri: str) -> None:
        """mkdir, ignoring 'already exists' (OpenViking mkdir is not idempotent)."""
        self._ensure_ready()
        try:
            self._client.mkdir(uri)
        except Exception as exc:  # already-exists is expected; log others at debug
            logger.debug("mkdir(%s) skipped: %s", uri, exc)

    def _write_memory_file(self, uri: str, content: str, *, wait: bool, mode: str = "create") -> str:
        """Write a NEW memory file (mode="create") and return its URI.

        ``mode="create"`` is the default because add/import/create_fact always
        target a fresh uuid-named URI. ``mode="replace"`` (used by
        :meth:`update_fact`, which calls the client directly) requires the file
        to already exist -- it stats first and raises NotFoundError otherwise.
        """
        self._ensure_ready()
        try:
            self._client.write(
                uri,
                content,
                mode=mode,
                wait=wait,
                timeout=self._config.write_timeout if wait else None,
            )
        except Exception as exc:
            raise MemoryManagerError(f"OpenViking write failed for {uri}: {exc}") from exc
        return uri

    def _list_memory_uris(self, scope_uri: str) -> list[str]:
        """Full URIs of real memory .md files under ``scope_uri`` (excludes derived)."""
        self._ensure_ready()
        try:
            entries = self._client.ls(
                scope_uri,
                recursive=True,
                simple=True,
                show_all_hidden=False,
            )
        except Exception as exc:
            logger.debug("ls(%s) failed: %s", scope_uri, exc)
            return []
        uris: list[str] = []
        for entry in entries or []:
            uri = entry if isinstance(entry, str) else _ctx_get(entry, "uri", "")
            if not uri or not uri.endswith(".md"):
                continue
            base = os.path.basename(uri)
            if base in _DERIVED_BASENAMES:
                continue
            uris.append(uri)
        return uris

    def _memory_content(self, uri: str, *, prefer_abstract: bool) -> str:
        """Read a memory's text: L0 abstract (clean, short) or full content."""
        content, _meta = self._read_with_meta(uri, prefer_abstract=prefer_abstract)
        return content

    def _read_with_meta(self, uri: str, *, prefer_abstract: bool = False) -> tuple[str, dict[str, Any] | None]:
        """Read a memory's content (meta comment + MEMORY_FIELDS stripped) + meta.

        Returns ``(content, meta_or_None)``. When ``prefer_abstract`` is set and a
        real L0 abstract is available, returns it (abstracts carry no meta, so
        ``meta`` is ``None`` in that branch). Falls back to ``read()`` otherwise.
        """
        self._ensure_ready()
        if prefer_abstract:
            try:
                abstract = _usable_abstract(self._client.abstract(uri))
                if abstract:
                    return abstract, None
            except Exception as exc:
                logger.debug("abstract(%s) failed: %s", uri, exc)
        try:
            raw = self._client.read(uri) or ""
        except Exception as exc:
            logger.debug("read(%s) failed: %s", uri, exc)
            return "", None
        content, meta = _split_meta(raw)
        return _strip_memory_fields(content), meta

    def _stat_created_at(self, uri: str) -> str:
        """Best-effort creation timestamp for a memory URI (for the panel).

        Extracted memories are written by OpenViking (no DEERFLOW_META), so read
        the file stat. Returns ``""`` if unavailable -- the gateway renders that
        as "-".
        """
        try:
            st = self._client.stat(uri) or {}
        except Exception as exc:
            logger.debug("stat(%s) failed: %s", uri, exc)
            return ""
        if not isinstance(st, dict):
            return ""
        # OpenViking stat() returns ``modTime`` (ISO str); accept common aliases.
        for key in ("created_at", "createdAt", "created", "modTime", "mtime", "modified", "ctime"):
            v = st.get(key)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, (int, float)) and v:
                try:
                    return datetime.fromtimestamp(float(v), tz=UTC).isoformat()
                except (ValueError, OSError, OverflowError):
                    return ""
        return ""

    def _filter_messages(self, messages: list[Any]) -> list[Any]:
        """Drop hidden messages unless the host hook keeps them."""
        keep_hook = self._config.should_keep_hidden_message
        out: list[Any] = []
        for msg in messages:
            if not _is_hidden_message(msg):
                out.append(msg)
            elif keep_hook is not None:
                add_kw = msg.get("additional_kwargs") if isinstance(msg, dict) else getattr(msg, "additional_kwargs", None) or {}
                if keep_hook(add_kw):
                    out.append(msg)
        return out

    def _new_messages(self, thread_id: str, messages: list[Any]) -> list[Any]:
        """Return only messages not yet ingested for this thread (content-hash dedup).

        Each session created by :meth:`_add` contains ONLY the new messages, so
        ``commit_session`` extracts them once -- old messages are never re-sent,
        which is what prevents the duplicate-fact flood (the same conversation
        re-extracted on every debounced ``add``).
        """
        seen = self._seen_msgs.setdefault(thread_id, {})
        new: list[Any] = []
        for msg in messages:
            role = _message_role(msg)
            content = _message_content_text(msg)
            if not content:
                continue
            h = hashlib.sha256(f"{role}\x00{content}".encode()).hexdigest()
            if h in seen:
                continue
            seen[h] = 1
            new.append(msg)
        # FIFO-evict oldest hashes so the most recent ``_MAX_SEEN_PER_THREAD``
        # survive and dedup stays effective at high message counts.  Without
        # this a long-running multi-tenant process accumulates unbounded memory.
        while len(seen) > self._MAX_SEEN_PER_THREAD:
            # pop first (oldest) item — Python 3.7+ dict preserves insertion order
            seen.pop(next(iter(seen)))
        return new

    # ── Write ────────────────────────────────────────────────────────────
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        # NOTE: user_id and trace_id are accepted for ABC compatibility but
        # not used -- this backend is single-user (see clear_memory docstring).
        self._add(thread_id, messages, agent_name=agent_name, wait=self._config.wait_on_write)

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        # Flush path (called right before summarization drops messages): block on
        # extraction so the distilled memories are captured before the source is lost.
        self._add(thread_id, messages, agent_name=agent_name, wait=True)

    def _add(self, thread_id: str, messages: list[Any], *, agent_name: str | None, wait: bool) -> None:
        """Ingest a conversation via OpenViking's session pipeline.

        ``create_session`` + ``add_message`` (per turn) + ``commit_session``. The
        commit archives the session and runs memory extraction (the VLM in
        ov.conf), distilling the conversation into structured memories under
        ``memories/``. A fresh session id per call (``thread_id`` + nonce) keeps
        ``add_message`` idempotent -- :meth:`add` receives the full (growing)
        history each debounced call, so reusing one session would duplicate
        messages. OpenViking consolidates extracted memories across sessions.

        Never breaks the agent run: any backend failure is logged and swallowed
        (mirrors DeerMem's backpressure-degrade behavior).
        """
        try:
            self._ensure_ready()
        except MemoryManagerError as exc:
            logger.warning("OpenViking add skipped (backend not ready): %s", exc)
            return
        filtered = self._filter_messages(messages or [])
        if not filtered:
            return
        # Gate: skip when nothing new since the last add (avoids redundant
        # re-extraction of an unchanged history). When there IS new content,
        # re-extract the FULL conversation (not just the new tail) so earlier
        # turns are re-evaluated in richer context -- a turn that extracted
        # nothing alone (e.g. the assistant asked clarifying questions) is
        # caught once a later turn engages. Duplicate facts this produces are
        # collapsed by get_memory/search content dedup.
        if not self._new_messages(thread_id, filtered):
            return
        sid = f"{thread_id}-{uuid.uuid4().hex[:8]}"
        try:
            self._client.create_session(session_id=sid)
        except Exception as exc:
            logger.warning("OpenViking create_session failed (sid=%s): %s", sid, exc)
            return
        for msg in filtered:  # FULL conversation -> reliable extraction
            role = _message_role(msg)
            # OpenViking session roles are user/assistant.
            role = {"human": "user", "ai": "assistant"}.get(role, role)
            content = _message_content_text(msg)
            if not content:
                continue
            try:
                self._client.add_message(sid, role, content)
            except Exception as exc:
                logger.debug("add_message failed (sid=%s): %s", sid, exc)
        try:
            res = self._client.commit_session(sid)
        except Exception as exc:
            logger.warning("OpenViking commit_session failed (sid=%s): %s", sid, exc)
            return
        if wait:
            self._wait_for_commit(res, sid)
        else:
            logger.info("OpenViking session committed (sid=%s); extraction runs async", sid)

    def _wait_for_commit(self, commit_result: Any, sid: str, *, timeout: float | None = None) -> None:
        """Poll the commit background task until extraction completes/fails."""
        if not isinstance(commit_result, dict):
            return
        task_id = commit_result.get("task_id")
        if not task_id:
            return
        deadline = time.monotonic() + (timeout or self._config.write_timeout or 60.0)
        last = None
        while time.monotonic() < deadline:
            try:
                task = self._client.get_task(task_id) or {}
            except Exception as exc:
                logger.debug("get_task failed (sid=%s): %s", sid, exc)
                return
            status = str(task.get("status", "")).lower()
            if status != last:
                logger.debug("commit task %s status=%s (sid=%s)", task_id, status, sid)
                last = status
            if status in ("completed", "done", "success"):
                return
            if status in ("failed", "error", "cancelled"):
                logger.warning("OpenViking extraction failed (sid=%s, task=%s): %s", sid, task_id, task)
                return
            time.sleep(2)
        logger.warning("OpenViking extraction timed out (sid=%s, task=%s)", sid, task_id)

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        # Degrade to empty injection if the backend is not ready.
        try:
            self._ensure_ready()
        except MemoryManagerError as exc:
            logger.warning("OpenViking get_context skipped (backend not ready): %s", exc)
            return ""
        # Memories are user-level (OpenViking's memory namespace), not agent-scoped.
        uris = self._list_memory_uris(self._memories_base)
        if not uris:
            return ""
        per_file = self._config.per_file_injection_chars
        chunks: list[str] = []
        total = 0
        for uri in uris:
            text = self._memory_content(uri, prefer_abstract=False)
            if not text:
                continue
            if len(text) > per_file:
                text = text[:per_file].rstrip() + "..."
            chunks.append(f"- {text}")
            total += len(text)
            if total >= self._config.max_injection_chars:
                break
        if not chunks:
            return ""
        body = "\n".join(chunks)
        budget = self._config.max_injection_chars
        if len(body) > budget:
            body = body[:budget].rstrip() + "..."
        return body

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            self._ensure_ready()
        except MemoryManagerError as exc:
            logger.warning("OpenViking search skipped (backend not ready): %s", exc)
            return []
        scope = self._memories_base
        threshold = self._config.score_threshold or None
        limit = top_k or self._config.search_limit
        try:
            result = self._client.find(
                query=query or "",
                target_uri=scope,
                limit=limit,
                score_threshold=threshold,
                context_type="memory",
            )
        except Exception as exc:
            logger.warning("OpenViking find failed (query=%r): %s", query, exc)
            return []
        facts: list[dict[str, Any]] = []
        for ctx in _all_contexts(result):
            uri = _ctx_get(ctx, "uri", "")
            if not uri:
                continue
            content = _usable_abstract(_ctx_get(ctx, "abstract", "")) or self._memory_content(uri, prefer_abstract=False)
            if category:
                ctx_category = _ctx_get(ctx, "category", "") or ""
                # Also allow matching by the URI path segment (subdir) as a fallback.
                if ctx_category != category and f"/{category}/" not in uri:
                    continue
            facts.append(
                {
                    "id": _encode_fact_id(uri),
                    "content": content,
                    "category": _ctx_get(ctx, "category", "") or _category_from_uri(uri),
                    "confidence": float(_ctx_get(ctx, "score", 0.0) or 0.0),
                    "source": "openviking",
                    "createdAt": "",
                    "scope": {"uri": uri},
                }
            )
        return _dedup_facts(facts)[:limit]

    # ── Manage ───────────────────────────────────────────────────────────

    # Section-type mapping for the display driven by directory layout.
    # Memories under ``memories/{category}/`` get a section whose type is
    # derived from the category name.  Unknown categories fall back to ``"table"``.
    # OpenViking memory-type -> display section type mapping.
    # Covers all 11 default types from openviking/prompts/templates/memory/*.yaml;
    # unknown directories fall back to "table".
    _SECTION_TYPE_BY_CATEGORY: dict[str, str] = {
        "preferences": "list",
        "entities": "cards",
        "events": "list",
        "skills": "cards",
        "experiences": "list",
        "tools": "table",
        "trajectories": "table",
        "cases": "cards",
        # DeerMem / manual-fact categories (from create_fact).
        "context": "list",
        "preference": "list",
        "correction": "list",
    }

    def _build_display(self, uris: list[str]) -> dict[str, Any]:
        """Build display sections from the ``memories/`` directory tree.

        Groups URIs by their immediate parent directory under
        ``viking://user/{space}/memories/``; each directory becomes one
        section whose ``type`` is derived from the directory name.
        Top-level files (e.g. ``profile.md``) become ``"content"`` sections.
        """
        sections: list[dict[str, Any]] = []
        by_dir: dict[str, list[str]] = {}
        top_level: list[str] = []

        base_prefix = self._memories_base.rstrip("/") + "/"
        for uri in uris:
            if not uri.startswith(base_prefix):
                top_level.append(uri)
                continue
            rel = uri[len(base_prefix) :]
            if not rel:
                continue
            if "/" in rel:
                dirname = rel.split("/", 1)[0]
                by_dir.setdefault(dirname, []).append(uri)
            else:
                top_level.append(uri)

        order = 1
        for dirname in sorted(by_dir):
            dir_uris = by_dir[dirname]
            section_type = self._SECTION_TYPE_BY_CATEGORY.get(dirname, "table")
            items = self._build_section_items(dir_uris, section_type)
            if not items:
                continue
            sections.append(
                {
                    "id": dirname,
                    "title": dirname.replace("-", " ").title(),
                    "type": section_type,
                    "items": items,
                    "order": order,
                }
            )
            order += 1

        for uri in sorted(top_level):
            # Top-level files (profile.md, identity.md, soul.md): read the
            # file body directly -- abstract(file_uri) returns the PARENT
            # directory's abstract (the memories/ dir summary), not the
            # file's own content.
            content, _meta = self._read_with_meta(uri, prefer_abstract=False)
            if not content or not content.strip():
                continue
            name = os.path.splitext(os.path.basename(uri))[0]
            sections.append(
                {
                    "id": name,
                    "title": name.replace("-", " ").title(),
                    "type": "content",
                    "content": content.strip(),
                    "order": order,
                }
            )
            order += 1

        return {"sections": sections}

    def _build_section_items(self, uris: list[str], section_type: str) -> list[dict[str, Any]]:
        """Convert one directory's file URIs into display items.

        Each item carries at minimum ``id`` (encoded URI) and ``content``
        (the markdown body).  Card sections additionally carry ``title``,
        ``body``, and optional ``tags``.
        """
        items: list[dict[str, Any]] = []
        for uri in sorted(uris):
            content, meta = self._read_with_meta(uri, prefer_abstract=True)
            # Fall back to full stripped body when the abstract is empty
            # or a placeholder.
            if not content or not content.strip():
                content, meta = self._read_with_meta(uri, prefer_abstract=False)
            if not content or not content.strip():
                continue
            m = meta or {}
            item: dict[str, Any] = {
                "id": _encode_fact_id(uri),
                "content": content.strip(),
                # OpenViking's delete_fact / update_fact work on every memory
                # file, so all items are editable + deletable from the panel.
                "deletable": True,
                "editable": True,
            }
            if section_type == "cards":
                # Derive a short title from the content's first heading or
                # from the filename.
                first_line = content.strip().split("\n")[0].lstrip("#").strip()
                item["title"] = first_line or _slugify(os.path.basename(uri))
                item["body"] = content.strip()
                if isinstance(m.get("category"), str):
                    item["tags"] = [m["category"]]
            conf = m.get("confidence")
            if isinstance(conf, (int, float)):
                item["confidence"] = float(conf)
            createdAt = m.get("createdAt") or self._stat_created_at(uri)
            if createdAt:
                item["createdAt"] = createdAt
            if isinstance(m.get("source"), str):
                item["source"] = m["source"]
            items.append(item)
        return items

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        uris = self._list_memory_uris(self._memories_base)
        doc = _empty_memory()
        try:
            doc["display"] = self._build_display(uris)
        except Exception:
            logger.exception("display build failed; returning empty display")
            doc["display"] = {"sections": []}
        return doc

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Backend-native full export with raw file contents in ``data``.

        The ``data.files`` dict maps viking URIs to their raw byte content
        so a same-backend import losslessly restores the directory tree.
        """
        doc = self.get_memory(user_id=user_id, agent_name=agent_name)
        files: dict[str, str] = {}
        uris = self._list_memory_uris(self._memories_base)
        for uri in uris:
            try:
                raw = self._client.read(uri) or ""
            except Exception as exc:
                logger.debug("export_memory: read(%s) skipped: %s", uri, exc)
                continue
            if raw:
                files[uri] = raw
        doc["data"] = {"files": files}
        return doc

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        # NOTE: This backend is single-user -- all memories live under one
        # ``user_space`` (configured in backend_config, default "default").
        # ``user_id`` and ``agent_name`` are accepted for API compatibility
        # but do not scope the deletion. In a multi-user deployment, use
        # separate ``user_space`` values per user (each gets its own viking
        # URI namespace), or use the HTTP-mode ``openviking`` backend which
        # supports server-side multi-tenancy.
        try:
            self._client.rm(self._memories_base, recursive=True)
        except Exception as exc:
            logger.debug("rm(%s) skipped: %s", self._memories_base, exc)
        self._safe_mkdir(self._memories_base)
        # Clear the dedup gate so the next add() in a cached thread
        # re-extracts instead of seeing every prior hash still resident
        # and silently returning empty.
        self._seen_msgs.clear()
        return _empty_memory()

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Import memory via a 2-layer waterfall: native data -> extraction.

        Layer 1 (``data``): same-backend lossless round-trip (``data.files``).
        Layer 2 (extraction): collect ALL text content from the source payload
        -- regardless of format (display items, facts, user/history summaries)
        -- and feed it to OpenViking's extraction pipeline (session->commit).
        The target backend re-learns the data in its own format; no format
        mapping, no ``facts[]`` direct write.
        """
        payload = memory_data or {}

        # ── Layer 1: backend-native ``data`` (lossless round-trip) ───────
        data = payload.get("data")
        files = data.get("files") if isinstance(data, dict) else None
        if isinstance(files, dict) and files:
            written = self._import_from_native(files)
            if written == 0:
                logger.warning("import_memory: data.files provided but _import_from_native wrote zero files; falling through to extraction")
            else:
                return self.get_memory(user_id=user_id, agent_name=agent_name)

        # ── Layer 2: extraction (feed source content to the pipeline) ────
        contents = self._collect_importable_content(payload)
        if contents:
            try:
                self._import_via_extraction(contents)
            except Exception as exc:
                logger.warning("Extraction import failed; memories not imported: %s", exc)

        return self.get_memory(user_id=user_id, agent_name=agent_name)

    def _collect_importable_content(self, payload: dict[str, Any]) -> list[str]:
        """Collect ALL text content from the import payload, regardless of format.

        Handles any source backend's format:
        - ``display.sections[].content`` (content-type sections)
        - ``display.sections[].items[].content/body`` (list/cards/table items)
        - ``facts[].content`` (DeerMem format -- treated as plain text, not files)
        - ``user/history.*.summary`` (DeerMem summaries)
        """
        contents: list[str] = []

        # From display sections (OpenViking or any backend that provides display)
        display = payload.get("display")
        if isinstance(display, dict):
            for section in display.get("sections", []) or []:
                if not isinstance(section, dict):
                    continue
                sc = section.get("content")
                if isinstance(sc, str) and sc.strip():
                    contents.append(sc)
                for item in section.get("items", []) or []:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("content") or item.get("body") or ""
                    if isinstance(text, str) and text.strip():
                        contents.append(text)

        # From facts[] (DeerMem source -- content is text, not a file to write)
        for fact in payload.get("facts", []) or []:
            if isinstance(fact, dict):
                text = fact.get("content") or ""
                if isinstance(text, str) and text.strip():
                    contents.append(text)

        # From user/history summaries (DeerMem source)
        for section_name in ("user", "history"):
            section = payload.get(section_name)
            if isinstance(section, dict):
                for key in (
                    "workContext",
                    "personalContext",
                    "topOfMind",
                    "recentMonths",
                    "earlierContext",
                    "longTermBackground",
                ):
                    sub = section.get(key)
                    if isinstance(sub, dict):
                        summary = sub.get("summary") or ""
                        if isinstance(summary, str) and summary.strip():
                            contents.append(summary)

        return contents

    def _import_via_extraction(self, contents: list[str]) -> None:
        """Feed imported content through OpenViking's extraction pipeline.

        Constructs a simulated conversation from the collected text and commits
        it so the VLM re-extracts memories in OpenViking's own format
        (preferences/entities/profile/...). No format mapping -- the extraction
        LLM decides how to organize the imported information.
        """
        try:
            self._ensure_ready()
        except MemoryManagerError as exc:
            logger.warning("import: backend not ready: %s", exc)
            return

        sid = f"import-{uuid.uuid4().hex[:8]}"
        try:
            self._client.create_session(session_id=sid)
        except Exception as exc:
            logger.warning("import create_session failed: %s", exc)
            return

        # Pack all content into one user message; the extraction LLM will
        # distill it into structured memories in OpenViking's format.
        user_msg = "Please remember the following information about me:\n\n" + "\n\n".join(f"- {c}" for c in contents)
        try:
            self._client.add_message(sid, "user", user_msg)
            self._client.add_message(sid, "assistant", "Got it. I've noted all of this.")
        except Exception as exc:
            logger.warning("import add_message failed: %s", exc)
            return

        try:
            res = self._client.commit_session(sid)
            self._wait_for_commit(res, sid)
        except Exception as exc:
            logger.warning("import commit_session failed: %s", exc)

    def _import_from_native(self, files: dict[str, str]) -> int:
        """Restore the ``memories/`` directory tree from a ``data.files`` dict.

        Each key is a viking URI; the value is the raw file content to write.
        URIs outside ``self._memories_base`` are remapped or skipped.

        Returns the number of files actually written (0 when every URI was
        filtered or every write failed).
        """
        self._ensure_ready()
        base = self._memories_base.rstrip("/")
        remapped: dict[str, str] = {}
        for uri, raw in files.items():
            if not isinstance(uri, str) or not isinstance(raw, str):
                continue
            if "/memories/" not in uri:
                continue
            rel = uri.split("/memories/", 1)[1]
            if not rel or ".." in rel or rel.startswith("/"):
                continue
            target = f"{base}/{rel}"
            remapped[target] = raw

        if not remapped:
            logger.warning("import_memory: data.files contained no remappable URIs; nothing imported via native layer")
            return 0

        written = 0
        for target_uri, raw in remapped.items():
            parent = target_uri.rsplit("/", 1)[0]
            self._safe_mkdir(parent)
            try:
                # True upsert: if the file already exists, overwrite it
                # in-place so re-importing a modified backup reflects edits.
                # mode="create" would silently skip the existing file (the
                # except below swallows the error as debug).
                try:
                    self._client.stat(target_uri)
                    mode = "replace"
                except Exception:
                    mode = "create"
                self._client.write(
                    target_uri,
                    raw,
                    mode=mode,
                    wait=self._config.wait_on_write,
                    timeout=self._config.write_timeout if self._config.wait_on_write else None,
                )
            except Exception as exc:
                logger.debug("import_memory: write(%s) skipped: %s", target_uri, exc)
                continue
            written += 1
        return written

    # ── Tier 3 hooks (fact CRUD) ─────────────────────────────────────────
    def create_fact(
        self,
        content: str,
        category: str = "context",
        confidence: float = 0.5,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        scope = self._memories_base
        category = category or "context"
        dir_uri = f"{scope}/{category}"
        self._safe_mkdir(dir_uri)
        tail = _slugify(content)
        file_uri = f"{dir_uri}/{tail}-{uuid.uuid4().hex[:6]}.md"
        created_at = datetime.now(UTC).isoformat()
        meta = {
            "category": category,
            "createdAt": created_at,
            "source": "manual",
            "confidence": float(confidence),
        }
        self._write_memory_file(file_uri, _build_meta_comment(meta) + content, wait=self._config.wait_on_write)
        # Return the live memory state (display-driven) so the newly created
        # fact appears in the display section for its category.
        return (self.get_memory(user_id=user_id, agent_name=agent_name), _encode_fact_id(file_uri))

    def delete_fact(
        self,
        fact_id: str,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        uri = _decode_fact_id(fact_id)
        try:
            self._client.rm(uri)
        except Exception as exc:
            # Normalize not-found to KeyError so the gateway returns a clean 404
            # (it maps KeyError -> 404); other errors surface as MemoryManagerError.
            low = str(exc).lower()
            if "not found" in low or "no such" in low or "not exist" in low:
                raise KeyError(uri) from exc
            raise MemoryManagerError(f"OpenViking delete failed for {uri}: {exc}") from exc
        return self.get_memory(user_id=user_id, agent_name=agent_name)

    def update_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        uri = _decode_fact_id(fact_id)
        # Read existing content + meta so omitted fields are preserved.
        existing_content, meta = self._read_with_meta(uri, prefer_abstract=False)
        if not existing_content and meta is None:
            # read() failed (file missing) -> 404, not a silent orphan write.
            raise KeyError(uri)
        meta = dict(meta or {})
        if category:
            meta["category"] = category
        if confidence is not None:
            meta["confidence"] = float(confidence)
        body = _build_meta_comment(meta) + (content if content is not None else existing_content)
        target_uri = uri
        new_dir: str | None = None
        if category:
            new_dir = f"{self._memories_base}/{category}"
            target_uri = f"{new_dir}/{os.path.basename(uri)}"
        if target_uri != uri:
            # Category change = move: create at the new URI, drop the old file.
            self._safe_mkdir(new_dir)  # type: ignore[arg-type]
            self._write_memory_file(target_uri, body, wait=self._config.wait_on_write, mode="create")
            try:
                self._client.rm(uri)
            except Exception as exc:
                logger.debug("rm old %s after move skipped: %s", uri, exc)
        else:
            try:
                self._client.write(
                    target_uri,
                    body,
                    mode="replace",
                    wait=self._config.wait_on_write,
                    timeout=self._config.write_timeout if self._config.wait_on_write else None,
                )
            except Exception as exc:
                raise MemoryManagerError(f"OpenViking update failed for {target_uri}: {exc}") from exc
        return self.get_memory(user_id=user_id, agent_name=agent_name)

    def reload_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        # OpenViking has no separate reload concept; re-fetch the live state.
        return self.get_memory(user_id=user_id, agent_name=agent_name)

    # ── Lifecycle ────────────────────────────────────────────────────────
    def warm(self) -> bool | None:
        """Heavy one-time init: initialize the embedded store + health check."""
        try:
            self._ensure_ready()
            return bool(self._client.is_healthy())
        except Exception as exc:
            logger.warning("OpenViking warm() failed: %s", exc)
            return False

    def shutdown_flush(self, timeout: float) -> bool:
        """Release the embedded OpenViking client on graceful shutdown."""
        if self._client is None:
            return True
        try:
            self._client.close()
            return True
        except Exception as exc:
            logger.warning("OpenViking close() failed: %s", exc)
            return False


def _category_from_uri(uri: str) -> str:
    """Infer a memory's category from its URI (fallback when no DEERFLOW_META).

    Extracted memories live under ``memories/{category}/...`` -- e.g.
    ``memories/preferences/{user}/{file}.md``, ``memories/entities/{proj}/x.md``,
    ``memories/profile.md``. The category is the path segment immediately after
    ``memories``. Manual facts (``create_fact``/``import_memory``) land under
    ``memories/{category}/{slug}.md`` -- same rule applies.
    """
    parts = [p for p in uri.split("/") if p]
    if "memories" in parts:
        i = parts.index("memories")
        if i + 1 < len(parts):
            cat = parts[i + 1]
            return cat[:-3] if cat.endswith(".md") else cat
    return "context"
