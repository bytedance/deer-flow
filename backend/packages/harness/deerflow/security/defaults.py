"""Fixed deployment baseline; newly installed capabilities require grants.

Do not derive this list from discovery, the public directory, or configuration:
doing so would silently exempt future additions from enterprise authorization.
"""

DEFAULT_TOOL_TARGETS = frozenset(
    {
        "ask_clarification",
        "bash",
        "count_file_lines",
        "glob",
        "grep",
        "image_search",
        "list_uploaded_files",
        "ls",
        "memory_add",
        "memory_delete",
        "memory_search",
        "memory_update",
        "present_files",
        "read_file",
        "review_skill_package",
        "setup_agent",
        "str_replace",
        "task",
        "update_agent",
        "web_fetch",
        "web_search",
        "write_file",
        "write_todos",
        "view_image",
        "tool_search",
        "describe_skill",
    }
)

DEFAULT_SKILL_TARGETS = frozenset(
    {
        "public:academic-paper-review",
        "public:bootstrap",
        "public:chart-visualization",
        "public:claude-to-deerflow",
        "public:code-documentation",
        "public:consulting-analysis",
        "public:data-analysis",
        "public:deep-research",
        "public:find-skills",
        "public:frontend-design",
        "public:github-deep-research",
        "public:image-generation",
        "public:music-generation",
        "public:newsletter-generation",
        "public:podcast-generation",
        "public:ppt-generation",
        "public:skill-creator",
        "public:skill-reviewer",
        "public:surprise-me",
        "public:systematic-literature-review",
        "public:vercel-deploy-claimable",
        "public:video-generation",
        "public:web-design-guidelines",
    }
)


def is_default_resource(resource: str, target: str) -> bool:
    return (resource == "tool" and target in DEFAULT_TOOL_TARGETS) or (resource == "skill" and target in DEFAULT_SKILL_TARGETS) or (resource == "sandbox" and target == "*")
