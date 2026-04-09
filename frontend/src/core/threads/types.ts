import type { Message, Metadata, Thread } from "@langchain/langgraph-sdk";

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

export interface AgentThreadMetadata extends NonNullable<Metadata> {
  agent_name?: string;
}

export interface AgentThread extends Omit<Thread<AgentThreadState>, "metadata"> {
  metadata: AgentThreadMetadata | null | undefined;
  context?: AgentThreadContext;
}
