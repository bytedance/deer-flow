export interface MCPToolInfo {
  name: string;
  description: string;
}

export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
  disabled_tools: string[];
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}

export interface MCPServerToolsResult {
  tools: MCPToolInfo[];
  error: string | null;
}

export interface MCPToolsResponse {
  servers: Record<string, MCPServerToolsResult>;
}
