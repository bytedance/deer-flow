export interface MCPToolConfig extends Record<string, unknown> {
  enabled: boolean;
  discovered: boolean;
  description: string;
}

export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
  type?: string;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  headers?: Record<string, string>;
  oauth?: Record<string, unknown> | null;
  tools: Record<string, MCPToolConfig>;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}
