import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export type ThreadBranchRole = "main" | "branch";

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
}

export interface ThreadBranchMetadata extends Record<string, unknown> {
  root_thread_id?: string;
  parent_thread_id?: string;
  return_thread_id?: string;
  fork_checkpoint_id?: string;
  forked_from_title?: string;
  branch_name?: string;
  branch_role?: ThreadBranchRole;
  branch_depth?: number;
  branch_status?: string;
  agent_name?: string;
}

export interface ThreadRecord {
  thread_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  metadata: ThreadBranchMetadata;
  values: Partial<AgentThreadState> & Record<string, unknown>;
  interrupts?: Record<string, unknown>;
}

export interface CreateThreadBranchRequest {
  checkpoint_id?: string;
  branch_name?: string;
  copy_uploads?: boolean;
  copy_outputs?: boolean;
  copy_workspace?: boolean;
  metadata?: Record<string, unknown>;
}

export interface CreateThreadBranchResponse {
  thread_id: string;
  parent_thread_id: string;
  root_thread_id: string;
  fork_checkpoint_id?: string | null;
  created_at: string;
  metadata: ThreadBranchMetadata;
  values: Record<string, unknown>;
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
