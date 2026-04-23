export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  soul?: string | null;
  owner?: string | null;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  soul?: string | null;
}
