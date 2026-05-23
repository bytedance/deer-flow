import type { MCPServerConfig } from "./types";

export type PresetAuthType = "apiKey" | "oauth" | "none";

export type OAuthProvider = "google" | "slack" | "notion";

export interface PresetField {
  name: string;
  label: string;
  type: "text" | "password" | "path";
  placeholder?: string;
  required: boolean;
  description?: string;
}

export interface McpPreset {
  id: string;
  displayName: string;
  description: string;
  icon?: string;
  authType: PresetAuthType;
  docsUrl?: string;
  /** Connect-button label for OAuth presets (e.g., "Connect with Google"). */
  oauthProvider?: OAuthProvider;
  /** Empty for `oauth` and `none`. */
  fields: PresetField[];
  /** Only called for apiKey / none auth types. OAuth presets are built backend-side. */
  toServerConfig?: (values: Record<string, string>) => MCPServerConfig;
}

export const MCP_PRESETS: McpPreset[] = [
  {
    id: "github",
    displayName: "GitHub",
    description:
      "Search repositories, read files, manage issues and pull requests on GitHub.",
    authType: "apiKey",
    docsUrl: "https://github.com/settings/tokens?type=beta",
    fields: [
      {
        name: "token",
        label: "Personal Access Token",
        type: "password",
        placeholder: "github_pat_... or ghp_...",
        required: true,
        description:
          "Create a fine-grained PAT with Contents: Read and Issues: Read & Write.",
      },
    ],
    toServerConfig: (values) => ({
      enabled: true,
      type: "stdio",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-github"],
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: values.token ?? "" },
      description: "GitHub repositories, issues, and pull requests.",
    }),
  },
  {
    id: "notion",
    displayName: "Notion",
    description:
      "Read and write pages, databases, and blocks in your Notion workspace.",
    authType: "apiKey",
    docsUrl: "https://www.notion.so/my-integrations",
    fields: [
      {
        name: "token",
        label: "Integration Token",
        type: "password",
        placeholder: "ntn_... or secret_...",
        required: true,
        description:
          "Create an internal integration in Notion and share target pages with it.",
      },
    ],
    toServerConfig: (values) => ({
      enabled: true,
      type: "stdio",
      command: "npx",
      args: ["-y", "@notionhq/notion-mcp-server"],
      env: {
        OPENAPI_MCP_HEADERS: JSON.stringify({
          Authorization: `Bearer ${values.token ?? ""}`,
          "Notion-Version": "2022-06-28",
        }),
      },
      description: "Notion pages, databases, and blocks.",
    }),
  },
  {
    id: "gmail",
    displayName: "Gmail",
    description:
      "Read and send Gmail messages on behalf of the connected Google account.",
    authType: "oauth",
    oauthProvider: "google",
    docsUrl: "https://github.com/GongRzhe/Gmail-MCP-Server",
    fields: [],
  },
  {
    id: "gdrive",
    displayName: "Google Drive",
    description:
      "Search and read files from Google Drive on behalf of the connected account.",
    authType: "oauth",
    oauthProvider: "google",
    docsUrl:
      "https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive",
    fields: [],
  },
  {
    id: "filesystem",
    displayName: "Filesystem",
    description:
      "Read and write files inside a specific directory on the server host.",
    authType: "none",
    docsUrl:
      "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    fields: [
      {
        name: "allowedPath",
        label: "Allowed directory",
        type: "path",
        placeholder: "/home/user/projects",
        required: true,
        description:
          "Absolute path the MCP server is allowed to read and write.",
      },
    ],
    toServerConfig: (values) => ({
      enabled: true,
      type: "stdio",
      command: "npx",
      args: [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        values.allowedPath ?? "",
      ],
      env: {},
      description: `Local filesystem access: ${values.allowedPath ?? ""}`,
    }),
  },
];

export function getPresetById(id: string): McpPreset | undefined {
  return MCP_PRESETS.find((preset) => preset.id === id);
}
