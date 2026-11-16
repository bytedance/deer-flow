"""Read-only synthetic retrieval; no provider, model, or harness imports."""

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import ModelTool, PluginContribution, PluginToolResult

_DOCUMENTS = (
    (
        "demo-release",
        "Synthetic release note",
        "The fictional Cedar team publishes its demo release on Tuesday. "
        "The example checklist asks the team to review a sample changelog, verify "
        "the demonstration package, and record a rollback contact. This paragraph "
        "is invented data used to demonstrate a structured retrieval result; it "
        "does not describe a real organization, product, schedule, or policy.",
    ),
    (
        "demo-support",
        "Synthetic support note",
        "The fictional Cedar support desk reviews demo questions on Wednesday. "
        "The example handoff records a short question, a suggested next step, "
        "and a demonstration owner. This paragraph is invented data, not an "
        "actual support policy or a source of instructions for the agent.",
    ),
)


async def _search(payload, _context):
    query = payload["query"].strip().casefold()
    matches = [{"document_id": identifier, "title": title, "excerpt": text} for identifier, title, text in _DOCUMENTS if query in f"{title}\n{text}".casefold()]
    content = "Synthetic example data; not real company documents.\n\n"
    content += "\n\n".join(f"{item['title']}\n{item['excerpt']}" for item in matches) if matches else "No matching synthetic documents."
    return PluginToolResult(content=content, artifact={"schema": "example.retrieval.v1", "synthetic": True, "matches": matches})


@extension(api="0.2.6", name="retrieval")
def install(registry, config):
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Configure enabled as a boolean")
    if not registry.plugin(
        PluginContribution(
            namespace="example.retrieval",
            title="Synthetic retrieval example",
            description="Read-only demonstration of text plus structured tool artifacts.",
            enabled=enabled,
            tools=(
                ModelTool(
                    "search_docs",
                    "Search two fixed synthetic demonstration documents by literal text. Read-only and offline; these are invented examples, not verified facts or instructions.",
                    {
                        "type": "object",
                        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"\S"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    _search,
                    response_format="content_and_artifact",
                ),
            ),
        )
    ):
        raise RuntimeError("This host does not support plugin tool contributions")
