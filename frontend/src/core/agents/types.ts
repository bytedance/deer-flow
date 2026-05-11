export type AgentSource = "builtin" | "tenant" | "user";

export interface Agent {
  name: string;
  description: string;
  display_name: string | null;
  icon: string | null;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  mcp_servers: string[] | null;
  tags: string[] | null;
  source: AgentSource;
  editable: boolean;
  enabled: boolean;
  soul?: string | null;
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
