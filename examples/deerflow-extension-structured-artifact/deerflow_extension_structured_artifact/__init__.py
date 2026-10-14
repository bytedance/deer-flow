"""Deterministic read-only retrieval example for structured tool artifacts."""

from deerflow_extension_api import ModelTool, PluginContribution, PluginToolResult, extension

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
    "required": ["query"],
    "additionalProperties": False,
}

_CATALOG = (
    ("deerflow-guide", "DeerFlow runs a LangGraph agent with sandboxed tools and persistent thread state."),
    ("plugin-contract", "Full-stack plugins contribute model tools through the public extension contract."),
)


@extension(api="0.2.6", name="structured-artifact")
def install(registry, config):
    async def retrieve(payload, context):
        query = payload["query"].strip().lower()
        matches = [{"id": source_id, "excerpt": excerpt} for source_id, excerpt in _CATALOG if query in excerpt.lower()]
        summary = f"Found {len(matches)} source(s) for the requested topic."
        return PluginToolResult(summary, {"query": payload["query"], "sources": matches})

    registry.plugin(
        PluginContribution(
            namespace="community.structured-artifact",
            title="Structured artifact retrieval",
            description="Return concise retrieval summaries with separate evidence artifacts.",
            enabled=True,
            tools=(
                ModelTool(
                    "retrieve_sources",
                    "Retrieve matching read-only source evidence.",
                    _INPUT_SCHEMA,
                    retrieve,
                    response_format="content_and_artifact",
                ),
            ),
        )
    )
