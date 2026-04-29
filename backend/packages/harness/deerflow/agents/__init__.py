
# Patch langgraph_api to accept non-UUID thread IDs (e.g. siteflow-site-xxx-timestamp).
# validate_uuid is called on every thread API request; we replace it with a version
# that returns a deterministic uuid5 for non-UUID strings instead of raising HTTP 422.
#
# IMPORTANT: only patch modules already in sys.modules to avoid triggering cascade
# imports in contexts (e.g. gateway) where langgraph_api.api is not yet loaded.
import sys as _sys
import uuid as _uuid
try:
    import langgraph_api.utils as _lg_utils
    def _validate_uuid_patched(uuid_str: str, invalid_uuid_detail) -> _uuid.UUID:
        try:
            return _uuid.UUID(uuid_str)
        except ValueError:
            return _uuid.uuid5(_uuid.NAMESPACE_DNS, uuid_str)
    _lg_utils.validate_uuid = _validate_uuid_patched
    # Only patch threads/runs modules if already loaded (LangGraph server context).
    # Importing them fresh here would cascade into langgraph_api.config which
    # requires DATABASE_URI/REDIS_URI env vars not present in the gateway.
    if "langgraph_api.api.threads" in _sys.modules:
        _sys.modules["langgraph_api.api.threads"].validate_uuid = _validate_uuid_patched
    if "langgraph_api.api.runs" in _sys.modules:
        _sys.modules["langgraph_api.api.runs"].validate_uuid = _validate_uuid_patched
except ImportError:
    pass

from .checkpointer import get_checkpointer, make_checkpointer, reset_checkpointer
from .factory import create_deerflow_agent
from .features import Next, Prev, RuntimeFeatures
from .lead_agent import make_lead_agent
from .lead_agent.prompt import prime_enabled_skills_cache
from .thread_state import SandboxState, ThreadState

# LangGraph imports deerflow.agents when registering the graph. Prime the
# enabled-skills cache here so the request path can usually read a warm cache
# without forcing synchronous filesystem work during prompt module import.
prime_enabled_skills_cache()

__all__ = [
    "create_deerflow_agent",
    "RuntimeFeatures",
    "Next",
    "Prev",
    "make_lead_agent",
    "SandboxState",
    "ThreadState",
]
