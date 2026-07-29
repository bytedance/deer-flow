"""OpenViking memory backend -- embedded in-process :class:`MemoryManager`.

Adapts OpenViking (https://github.com/volcengine/OpenViking) as a deerflow memory
backend. Runs OpenViking **embedded** in the deerflow process -- no separate
server -- via ``openviking.OpenViking(path=<data dir>)``.

OpenViking is a client-server *or* embedded context database that embeds
internally: you hand it text, it handles embedding, L0/L1/L2 summarization, and
hierarchical retrieval. Memories are files under
``viking://user/{space}/memories/{category}/{id}.md``; the URI path auto-classifies
them as ``context_type="memory"``.

v1 write strategy: **raw write** -- :meth:`add` serializes conversation messages
to a markdown memory file via ``client.write(uri, content, mode="create")``.
Deterministic, no extra VLM-extraction cost, memories retrievable immediately
(file content) even before vector indexing finishes. Session-extraction
(``commit_session``) is a planned follow-up.

Heavy ``openviking`` dependency is an **optional extra** (``deerflow-harness[openviking]``);
the ``import openviking`` is lazy (inside ``model_post_init``) so this backend
registers/scans fine without the extra installed. Selecting
``manager_class: openviking`` without the extra raises a clear ImportError at
construction.
"""

from .openviking_manager import OpenVikingMemoryManager

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``openviking``.
MANAGER_CLASS = OpenVikingMemoryManager
