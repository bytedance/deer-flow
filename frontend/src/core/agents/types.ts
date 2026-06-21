export type AgentSource = "builtin" | "tenant" | "user";

export interface NavItem {
  path: string;
  label: string;
  icon: string;
}

export interface StarterConfig {
  label: string;
  prompt: string;
  icon?: string | null;
  auto_start?: boolean;
}

export interface Agent {
  name: string;
  description: string;
  display_name: string | null;
  icon: string | null;
  visibility?: "public" | "hidden" | string | null;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  mcp_servers: string[] | null;
  tags: string[] | null;
  source: AgentSource;
  editable: boolean;
  enabled: boolean;
  soul?: string | null;
  type?: "agent" | "group" | null;
  parent?: string | null;
  order?: number | null;
  starters?: StarterConfig[] | null;
  nav_items?: NavItem[] | null;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
}

export interface AgentGroup {
  label: string;
  source: AgentSource;
  agents: Agent[];
}
