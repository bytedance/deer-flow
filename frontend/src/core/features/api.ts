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

export async function fetchSubagentBatchesCapability(): Promise<SubagentBatchesCapability> {
  const feature = (await fetchFeatures()).subagent_batches;
  const legacyEnabled = feature?.enabled ?? false;
  return {
    repositoryAvailable: feature?.repository_available ?? legacyEnabled,
    workerRunning: feature?.worker_running ?? legacyEnabled,
    maxRunning: feature?.max_running ?? 0,
  };
}
