import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
}

export interface AgentThread extends Thread<AgentThreadState> {
  context?: AgentThreadContext;
}

export interface RunMessage {
  run_id: string;
  content: Message;
  metadata: {
    caller: string;
  };
  created_at: string;
}

/**
 * Stable identifier for each row in the context-window breakdown. New
 * categories must be added at both the backend (`_BREAKDOWN_ORDER` in
 * `backend/app/gateway/context_usage.py`) and here.
 */
export type ContextUsageBreakdownKey =
  | "messages"
  | "system_prompt"
  | "skills"
  | "system_tools"
  | "mcp_tools"
  | "custom_agents"
  | "memory_files"
  | "mcp_tools_deferred"
  | "system_tools_deferred"
  | "autocompact_buffer"
  | "free_space";

export interface ThreadContextUsageBreakdownItem {
  key: ContextUsageBreakdownKey | string;
  tokens: number;
  /**
   * Whether this row contributes to the "% used" total. `false` means the
   * row is shown as reserved / unoccupied (deferred tool schemas, autocompact
   * buffer, free space).
   */
  active: boolean;
}

export interface ThreadContextUsage {
  max_context_tokens: number | null;
  used_tokens: number;
  percentage: number | null;
  breakdown: ThreadContextUsageBreakdownItem[];
}

export interface ThreadTokenUsageResponse {
  thread_id: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_runs: number;
  by_model: Record<string, { tokens: number; runs: number }>;
  by_caller: {
    lead_agent: number;
    subagent: number;
    middleware: number;
  };
  context_usage?: ThreadContextUsage | null;
}
