export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}
