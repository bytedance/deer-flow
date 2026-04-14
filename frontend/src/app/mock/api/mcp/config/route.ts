export function GET() {
  return Response.json({
    mcp_servers: {
      "mcp-github-trending": {
        enabled: true,
        type: "stdio",
        command: "uvx",
        args: ["mcp-github-trending"],
        env: {},
        url: null,
        headers: {},
        description:
          "A MCP server that provides access to GitHub trending repositories and developers data",
        tools: {
          trending_repositories: {
            enabled: true,
            discovered: true,
            description: "Fetch trending repositories on GitHub",
          },
          trending_developers: {
            enabled: false,
            discovered: true,
            description: "Fetch trending developers on GitHub",
          },
        },
      },
      "context-7": {
        enabled: true,
        description:
          "Get the latest documentation and code into Cursor, Claude, or other LLMs",
        tools: {
          resolve_library_id: {
            enabled: true,
            discovered: true,
            description: "Resolve a library identifier before loading docs",
          },
          get_library_docs: {
            enabled: true,
            discovered: true,
            description: "Fetch the latest docs for a selected library",
          },
        },
      },
      "feishu-importer": {
        enabled: false,
        description: "Import Feishu documents",
        tools: {},
      },
    },
  });
}
