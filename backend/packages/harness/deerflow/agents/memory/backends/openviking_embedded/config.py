"""OpenViking backend config -- parse ``backend_config`` into :class:`OpenVikingConfig`.

Follows the portability golden rule (see ``backends/noop/config.py`` for the full
version): a backend receives ALL host info through (1) the ABC method args and
(2) the ``backend_config`` dict. The ONLY ``from deerflow`` import allowed in
this folder is the ABC contract line in ``openviking_manager.py``.

The factory (``manager.py::get_memory_manager``) injects ``storage_path`` (a
writable state dir) into ``backend_config`` for every backend. OpenViking owns
its own storage layout, so we use ``storage_path`` only as the default parent for
``data_path`` (the OpenViking store directory) when ``data_path`` is empty.

OpenViking's providers (embedding / VLM / rerank / vector-db / ...) are normally
in ``~/.openviking/ov.conf``. This backend can ALSO generate that file from
deerflow config so everything lives in one place: set ``embedding`` / ``vlm``
(shortcuts for the two most common providers) or ``ov_conf`` (a raw dict written
verbatim -- full control over every ov.conf field). The backend writes it to
``<data_path>/ov.conf`` and points OpenViking at it via the
``OPENVIKING_CONFIG_FILE`` env var. If none of these are provided, the backend
falls back to ``~/.openviking/ov.conf`` (run ``openviking-server init``).
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpenVikingConfig:
    """Parsed config for the OpenViking embedded backend.

    All fields have safe defaults so zero-config construction works (given a
    valid ``~/.openviking/ov.conf`` for the embedding provider).
    """

    #: Writable state dir, host-injected. Used as the parent of ``data_path``
    #: when ``data_path`` is empty. OpenViking lands its store under ``data_path``.
    storage_path: str = ""

    #: OpenViking store directory (passed as ``OpenViking(path=...)``). Empty =
    #: ``{storage_path}/openviking``; falls back to ``./runtime/openviking`` if
    #: ``storage_path`` is also empty.
    data_path: str = ""

    #: User space in the viking URI tree -> ``viking://user/{user_space}/memories``.
    #: At runtime the manager uses ``user_id`` (from the ABC args) when provided,
    #: falling back to this. Single-user deployments leave this as ``"default"``.
    user_space: str = "default"

    #: OpenViking actor peer identity. Defaults to ``user_space``. Set explicitly
    #: only if the deployment needs a stable peer id independent of the space.
    actor_peer_id: str | None = None

    #: Subdirectory under ``memories/`` where :meth:`add` lands conversation
    #: transcripts (e.g. ``memories/conversation/{thread_id}/{id}.md``).
    memory_category: str = "conversation"

    #: Minimum semantic score for ``find`` results; 0.0 = no filter (pass None).
    score_threshold: float = 0.0

    #: Default ``limit`` for :meth:`search` when the caller does not pass ``top_k``.
    search_limit: int = 5

    #: Hard character budget for :meth:`get_context` injection text. OpenViking
    #: does not truncate for you; the backend must (the host applies no budget).
    max_injection_chars: int = 2000

    #: Per-file character budget when rendering memory content for injection.
    per_file_injection_chars: int = 500

    #: Whether :meth:`add` blocks on vector/semantic indexing (``write(wait=...)``).
    #: False = fire-and-forget (content is persisted immediately; vectors lag).
    #: :meth:`add_nowait` (the summarization-flush path) always forces True so
    #: content is fully indexed before the host drops the source messages.
    wait_on_write: bool = False

    #: Timeout (seconds) for ``write(wait=True)`` and ``wait_processed``.
    write_timeout: float = 60.0

    #: Host-injected hook: filter ``hide_from_ui`` messages. ``None`` = skip all
    #: hidden messages. Called as ``should_keep_hidden_message(additional_kwargs)``
    #: -> bool (True = keep despite hide_from_ui).
    should_keep_hidden_message: Callable[[Any], bool] | None = field(default=None)

    #: Raw ov.conf dict -- written verbatim to ``<data_path>/ov.conf``. Full
    #: control over EVERY OpenViking field (embedding/vlm/rerank/storage/parsers/
    #: encryption/search_mode/...). Use this when you need fields beyond the
    #: ``embedding``/``vlm`` shortcuts. ``$ENV`` refs are expanded by OpenViking
    #: at load time (deerflow's dotenv already populated ``os.environ``).
    ov_conf: dict[str, Any] | None = None

    #: Shortcut for ``ov_conf.embedding.dense`` (the embedding provider: provider,
    #: model, api_base, api_key, dimension, input). Merged into ``ov_conf``.
    embedding: dict[str, Any] | None = None

    #: Shortcut for ``ov_conf.vlm`` (the VLM used for memory extraction:
    #: provider, model, api_base, api_key, ...). Merged into ``ov_conf``.
    vlm: dict[str, Any] | None = None

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> OpenVikingConfig:
        """Build a config from the ``backend_config`` dict.

        Reads ONLY known keys; unknown keys are ignored (with a warning logged)
        so the host can safely inject ``storage_path`` into every backend's
        ``backend_config`` without breaking ones that don't use it. ``None``
        values are dropped so YAML empty keys fall back to defaults.
        """
        import logging

        cfg = dict(backend_config or {})

        known = {
            "storage_path",
            "data_path",
            "user_space",
            "actor_peer_id",
            "memory_category",
            "score_threshold",
            "search_limit",
            "max_injection_chars",
            "per_file_injection_chars",
            "wait_on_write",
            "write_timeout",
            "should_keep_hidden_message",
            "ov_conf",
            "embedding",
            "vlm",
        }

        unknown = sorted(k for k in cfg if k not in known)
        if unknown:
            logging.getLogger(__name__).warning("OpenViking backend_config: ignoring unknown keys: %s", ", ".join(unknown))

        # Drop None values so empty YAML keys fall back to defaults.
        picked = {k: v for k, v in cfg.items() if k in known and v is not None}

        return cls(
            storage_path=str(picked.get("storage_path") or ""),
            data_path=str(picked.get("data_path") or ""),
            user_space=str(picked.get("user_space") or "default") or "default",
            actor_peer_id=picked.get("actor_peer_id"),
            memory_category=str(picked.get("memory_category") or "conversation") or "conversation",
            score_threshold=float(picked.get("score_threshold", 0.0) or 0.0),
            search_limit=int(picked.get("search_limit", 5) or 5),
            max_injection_chars=int(picked.get("max_injection_chars", 2000) or 2000),
            per_file_injection_chars=int(picked.get("per_file_injection_chars", 500) or 500),
            wait_on_write=bool(picked.get("wait_on_write", False)),
            write_timeout=float(picked.get("write_timeout", 60.0) or 60.0),
            should_keep_hidden_message=picked.get("should_keep_hidden_message"),
            ov_conf=picked.get("ov_conf"),
            embedding=picked.get("embedding"),
            vlm=picked.get("vlm"),
        )

    def resolve_data_path(self) -> str:
        """Resolve the OpenViking store directory, creating it if needed."""
        if self.data_path:
            path = self.data_path
        elif self.storage_path:
            path = os.path.join(self.storage_path, "openviking")
        else:
            path = os.path.join("runtime", "openviking")
        os.makedirs(path, exist_ok=True)
        # Restrict to owner-only: the store directory contains ov.conf (API
        # keys) and the embedded database -- neither should be world-readable.
        os.chmod(path, 0o700)
        return path

    @property
    def has_providers(self) -> bool:
        """True if any provider config was given (so we generate ov.conf)."""
        return bool(self.ov_conf or self.embedding or self.vlm)

    def build_ov_conf(self) -> dict[str, Any]:
        """Assemble the ov.conf dict to write under ``data_path``.

        Layered (later wins): raw ``ov_conf`` (full user control) -> ``embedding``
        / ``vlm`` shortcuts merged in -> backend-required defaults via
        ``setdefault`` (only the knobs the session-pipeline backend needs to
        function; the user's explicit values always win).
        """
        # Deep-copy the raw user dict so we never mutate the parsed config.
        conf: dict[str, Any] = copy.deepcopy(dict(self.ov_conf or {}))
        if self.embedding:
            emb = dict(conf.get("embedding") or {})
            emb["dense"] = copy.deepcopy(self.embedding)
            conf["embedding"] = emb
        if self.vlm:
            conf["vlm"] = copy.deepcopy(self.vlm)
        # Backend-required defaults (setdefault = user override wins).
        conf.setdefault("auto_generate_l0", True)
        conf.setdefault("auto_generate_l1", False)
        mem = dict(conf.get("memory") or {})
        mem.setdefault("version", "v2")
        mem.setdefault("extraction_enabled", True)
        conf["memory"] = mem
        return conf
