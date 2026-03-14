export function GET() {
  return Response.json({
    servers: {
      "mcp-github-trending": {
        tools: [
          {
            name: "get_github_trending_repositories",
            description:
              "Get trending GitHub repositories for a specific language and time period",
          },
          {
            name: "get_github_trending_developers",
            description:
              "Get trending GitHub developers for a specific language and time period",
          },
        ],
        error: null,
      },
      "context-7": {
        tools: [
          {
            name: "resolve-library-id",
            description:
              "Resolves a package/product name to a Context7-compatible library ID",
          },
          {
            name: "get-library-docs",
            description:
              "Fetches up-to-date documentation for a library using a Context7-compatible library ID",
          },
        ],
        error: null,
      },
      "feishu-importer": {
        tools: [],
        error: "Failed to connect: connection refused",
      },
    },
  });
}
