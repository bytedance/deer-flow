from importlib import import_module

_ROUTER_MODULES = {
    "admin",
    "agents",
    "artifacts",
    "assistants_compat",
    "audio",
    "auth_router",
    "channels",
    "cost",
    "feedback",
    "genui",
    "genui_telemetry",
    "mcp",
    "memory",
    "models",
    "rag",
    "report_runs",
    "report_template_telemetry",
    "report_templates",
    "runs",
    "skills",
    "suggestions",
    "tenant_status",
    "thread_runs",
    "threads",
    "uploads",
}

__all__ = sorted(_ROUTER_MODULES)


def __getattr__(name: str):
    if name in _ROUTER_MODULES:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
