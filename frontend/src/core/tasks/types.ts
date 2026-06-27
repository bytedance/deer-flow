import type { AIMessage } from "@langchain/langgraph-sdk";

export interface SubtaskStep {
  message: AIMessage;
  messageIndex?: number;
}

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  latestMessage?: AIMessage;
  steps?: SubtaskStep[];
  prompt: string;
  result?: string;
  error?: string;
}
