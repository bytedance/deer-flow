export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
  /** Display-only metadata; never passed to the MCP transport. */
  presentation?: Record<string, unknown>;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}
