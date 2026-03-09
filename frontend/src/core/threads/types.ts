import { type BaseMessage } from "@langchain/core/messages";
import type { Thread } from "@langchain/langgraph-sdk";

import type { RuntimeModelSpec } from "../models/types";
import type { Todo } from "../todos";

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: BaseMessage[];
  artifacts: string[];
  todos?: Todo[];
  token_usage?: TokenUsage;
}

export interface AgentThread extends Thread<AgentThreadState> {
  project_id?: string | null;
}

export interface AgentThreadContext {
  thread_id: string;
  model_name: string | undefined;
  model_spec?: RuntimeModelSpec;
  thinking_effort?: string;
  user_id?: string;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
}
