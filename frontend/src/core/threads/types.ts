import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface ThreadUsage {
  models: Array<{
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  }>;
  tool_calls: Record<string, number>;
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
  usage?: ThreadUsage;
}

export interface AgentThread extends Thread<AgentThreadState> { }

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  workspace_type?: string;
  workspace_id?: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
}
