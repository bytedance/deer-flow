export interface Agent {
  name: string;
  display_name?: string | null;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  soul?: string | null;
}

// Keep this in sync with backend AGENT_DISPLAY_NAME_MAX_LENGTH.
export const AGENT_DISPLAY_NAME_MAX_LENGTH = 100;

export interface CreateAgentRequest {
  name: string;
  display_name?: string | null;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  display_name?: string | null;
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
}
