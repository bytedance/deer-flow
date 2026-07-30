"""OpenViking memory backend -- embedded in-process :class:`MemoryManager`.

Adapts OpenViking (https://github.com/volcengine/OpenViking) as a deerflow memory
backend. Runs OpenViking **embedded** in the deerflow process -- no separate
server -- via ``openviking.OpenViking(path=<data dir>)``.

OpenViking is a client-server *or* embedded context database that embeds
internally: you hand it text, it handles embedding, L0/L1/L2 summarization, and
hierarchical retrieval. Memories are files under
``viking://user/{space}/memories/{category}/{id}.md``; the URI path auto-classifies
them as ``context_type="memory"``.

Write strategy: **session pipeline** -- :meth:`add` hands the conversation to
OpenViking's session pipeline (``create_session`` + ``add_message`` per turn +
``commit_session``). OpenViking's VLM extracts structured memories (preferences /
entities / profile / ...) and stores them as files under
``viking://user/{space}/memories/``. The backend surfaces the distilled memories,
not raw transcripts. ``add`` returns immediately when ``wait_on_write: false``;
``add_nowait`` (the summarization-flush path) blocks until extraction finishes.

Memory partitioning: manual facts (``create_fact``, ``import_memory`` Layer 1)
are written to ``memories/{agent}/``, where ``agent_name=None`` resolves to
``"__default__"`` (matching DeerMem's ``DEFAULT_AGENT_BUCKET``).  Extracted
memories (the session pipeline) land at the root ``memories/`` level because
OpenViking's extraction engine does not accept a per-agent output path.  Reads
stay at the root level so both scoped facts and shared extracted memories are
visible.  ``clear_memory(agent_name=X)`` removes only agent X's facts;
``clear_memory(agent_name=None)`` clears everything (ABC contract).

Heavy ``openviking`` dependency is **auto-installed** via ``plugin.yaml`` when
``memory.allow_lazy_installs: true`` is set (deps land outside the venv so
``uv sync`` never wipes them). The ``import openviking`` is lazy (inside
``model_post_init``) so this backend registers/scans fine without the dependency
installed. Selecting ``manager_class: openviking_embedded`` without it raises a
clear ImportError at construction.
"""

from .openviking_manager import OpenVikingMemoryManager

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``openviking_embedded``.
MANAGER_CLASS = OpenVikingMemoryManager
