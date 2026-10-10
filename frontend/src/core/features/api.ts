import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface FeaturesResponse {
  agents_api: { enabled: boolean };
  browser_control?: { enabled: boolean };
  mcp_tasks?: { enabled: boolean };
  subagent_batches?: {
    enabled?: boolean;
    repository_available?: boolean;
    worker_running?: boolean;
    max_running?: number;
  };
  conversation_references?: {
    enabled?: boolean;
    max_references?: number;
  };
  knowledge_base?: {
    scope_selection_enabled?: boolean;
  };
  scheduled_tasks?: {
    available?: boolean;
    running?: boolean;
    tool_enabled?: boolean;
    min_interval_seconds?: number;
  };
  thread_activity?: {
    available?: boolean;
  };
  image_generation_management?: { enabled: boolean };
}

export interface ScheduledTasksFeature {
  /** The scheduled-task APIs exist on this server. */
  available: boolean;
  /** This Gateway's scheduler is running: tasks run on schedule and new tasks can be created. */
  running: boolean;
  /** Chats can create and manage tasks, and runs can pause their own schedule. */
  toolEnabled: boolean;
  /** Shortest interval and earliest one-time delay, in seconds. */
  minIntervalSeconds: number;
}

/**
 * Assumed when the backend sends no `scheduled_tasks` block (an older backend
 * or a test mock): the page keeps working as before, and chat-only copy (stop
 * conditions, "ask in any chat") stays hidden.
 */
export const DEFAULT_SCHEDULED_TASKS_FEATURE: ScheduledTasksFeature = {
  available: true,
  running: true,
  toolEnabled: false,
  minIntervalSeconds: 60,
};

export interface ThreadActivityFeature {
  /**
   * The activity feed, read markers and unread state exist (SQL persistence).
   * When false the sidebar does not poll and chats are never marked read.
   */
  available: boolean;
}

/** Assumed while loading, on error, and when an older backend sends no block. */
export const DEFAULT_THREAD_ACTIVITY_FEATURE: ThreadActivityFeature = {
  available: false,
};

export interface ConversationReferencesCapability {
  enabled: boolean;
  maxReferences: number;
}

export interface SubagentBatchesCapability {
  repositoryAvailable: boolean;
  workerRunning: boolean;
  maxRunning: number;
}

export async function fetchFeatures(): Promise<FeaturesResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/features`);
  if (!res.ok) {
    throw new Error(`Failed to load features: ${res.statusText}`);
  }
  return (await res.json()) as FeaturesResponse;
}

export async function fetchAgentsApiEnabled(): Promise<boolean> {
  return (await fetchFeatures()).agents_api.enabled;
}

export async function fetchBrowserControlEnabled(): Promise<boolean> {
  return (await fetchFeatures()).browser_control?.enabled ?? false;
}

export async function fetchMcpTasksEnabled(): Promise<boolean> {
  return (await fetchFeatures()).mcp_tasks?.enabled ?? false;
}

export async function fetchImageGenerationManagementEnabled(): Promise<boolean> {
  // Gateways without this flag also lack the image-management routes.
  return (await fetchFeatures()).image_generation_management?.enabled ?? false;
}

export async function fetchSubagentBatchesCapability(): Promise<SubagentBatchesCapability> {
  const feature = (await fetchFeatures()).subagent_batches;
  const legacyEnabled = feature?.enabled ?? false;
  return {
    repositoryAvailable: feature?.repository_available ?? legacyEnabled,
    workerRunning: feature?.worker_running ?? legacyEnabled,
    maxRunning: feature?.max_running ?? 0,
  };
}

export async function fetchConversationReferencesCapability(): Promise<ConversationReferencesCapability> {
  const features = await fetchFeatures();
  const capability = features.conversation_references;
  const maxReferences = capability?.max_references;
  return {
    enabled: capability?.enabled === true,
    maxReferences:
      typeof maxReferences === "number" &&
      Number.isInteger(maxReferences) &&
      maxReferences > 0
        ? maxReferences
        : 0,
  };
}

export async function fetchKnowledgeBaseFeature(): Promise<{
  scopeSelectionEnabled: boolean;
}> {
  const feature = (await fetchFeatures()).knowledge_base;
  return {
    scopeSelectionEnabled: feature?.scope_selection_enabled ?? false,
  };
}

export async function fetchScheduledTasksFeature(): Promise<ScheduledTasksFeature> {
  const feature = (await fetchFeatures()).scheduled_tasks;
  const defaults = DEFAULT_SCHEDULED_TASKS_FEATURE;
  const minInterval = feature?.min_interval_seconds;
  return {
    available:
      typeof feature?.available === "boolean"
        ? feature.available
        : defaults.available,
    running:
      typeof feature?.running === "boolean"
        ? feature.running
        : defaults.running,
    toolEnabled:
      typeof feature?.tool_enabled === "boolean"
        ? feature.tool_enabled
        : defaults.toolEnabled,
    minIntervalSeconds:
      typeof minInterval === "number" &&
      Number.isInteger(minInterval) &&
      minInterval > 0
        ? minInterval
        : defaults.minIntervalSeconds,
  };
}

export async function fetchThreadActivityFeature(): Promise<ThreadActivityFeature> {
  const feature = (await fetchFeatures()).thread_activity;
  return {
    available: feature?.available === true,
  };
}
