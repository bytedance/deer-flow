import type { AIMessage, Message } from "@langchain/langgraph-sdk";

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  latestMessage?: AIMessage;
  prompt: string;
  result?: string;
  error?: string;

  // Agent Swarm visualization fields
  agentName: string;
  agentIndex: number;
  messageIndex: number;
  totalMessages: number;
  /** Full trajectory including both AI and tool messages */
  messageHistory: Message[];
  createdAt: number;
}
