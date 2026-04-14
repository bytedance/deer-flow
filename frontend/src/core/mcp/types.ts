export interface MCPToolConfig extends Record<string, unknown> {
  enabled: boolean;
  discovered: boolean;
  description: string;
  active_in_runtime: boolean;
  pending_reload_action: "none" | "enable" | "disable";
}

export type MCPRuntimeStatus =
  | "not_initialized"
  | "pending_reload"
  | "in_sync";

export interface MCPRuntimeConfig extends Record<string, unknown> {
  status: MCPRuntimeStatus;
  reload_mode: "next_tool_load";
  restart_required: boolean;
  will_apply_on_next_load: boolean;
  cache_initialized: boolean;
  cache_stale: boolean;
  config_last_modified_at: string | null;
  runtime_config_last_loaded_at: string | null;
  active_server_count: number;
  active_tool_count: number;
  active_tools_by_server: Record<string, string[]>;
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
  runtime_tool_count: number;
  pending_reload_tool_count: number;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
  runtime: MCPRuntimeConfig;
}

export interface MCPToolConfigUpdate {
  enabled: boolean;
}

export interface MCPServerConfigUpdate {
  enabled: boolean;
  description: string;
  type?: string;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  headers?: Record<string, string>;
  oauth?: Record<string, unknown> | null;
  tools: Record<string, MCPToolConfigUpdate>;
}

export interface MCPConfigUpdate {
  mcp_servers: Record<string, MCPServerConfigUpdate>;
}
