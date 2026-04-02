export interface Agent {
  name: string;
  display_name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  soul?: string | null;
}

export interface CreateAgentRequest {
  name?: string | null;
  display_name?: string | null;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  display_name?: string | null;
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  soul?: string | null;
}
