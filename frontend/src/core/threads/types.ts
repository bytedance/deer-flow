import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface MessageRevision {
  id: string;
  messageId: string;
  text: string;
  createdAt: string;
}

export interface AssistantVersion {
  id: string;
  messageId: string;
  turnId: string;
  text: string;
  createdAt: string;
  contextSnapshot: {
    model_name?: string;
    mode?: string;
    reasoning_effort?: string;
  };
}

export interface VersionLogEntry {
  id: string;
  kind: "human_edit" | "assistant_regenerate" | "assistant_select";
  messageId: string;
  versionId: string;
  createdAt: string;
}

export type MessageVersionsMap = Record<string, MessageRevision[]>;
export type AssistantVersionsMap = Record<string, AssistantVersion[]>;
export type ActiveVersionMap = Record<string, string>;

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
  message_versions?: MessageVersionsMap;
  assistant_versions?: AssistantVersionsMap;
  active_version_map?: ActiveVersionMap;
  version_logs?: VersionLogEntry[];
}

export interface AgentThread extends Thread<AgentThreadState> {}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
}
