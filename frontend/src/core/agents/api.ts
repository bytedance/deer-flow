import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "./types";

const BACKEND_UNAVAILABLE_STATUSES = new Set([502, 503, 504]);
const AGENTS_API_DISABLED_HINT = "agents_api.enabled=true";

function isAgentsApiDisabledDetail(detail: string | undefined): boolean {
  return (
    typeof detail === "string" &&
    (detail.includes(AGENTS_API_DISABLED_HINT) ||
      detail.includes("agents_api.enabled"))
  );
}

function isAgentsApiDisabledResponse(status: number, detail?: string): boolean {
  return status === 403 && isAgentsApiDisabledDetail(detail);
}

export class AgentsApiDisabledError extends Error {
  constructor(
    message = "Custom-agent management API is disabled. Set agents_api.enabled=true in config.yaml.",
  ) {
    super(message);
    this.name = "AgentsApiDisabledError";
  }
}

export class AgentNameCheckError extends Error {
  constructor(
    message: string,
    public readonly reason:
      | "api_disabled"
      | "backend_unreachable"
      | "request_failed",
  ) {
    super(message);
    this.name = "AgentNameCheckError";
  }
}

export async function getAgentsApiStatus(): Promise<{ enabled: boolean }> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/status`);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    const message = err.detail ?? (res.statusText || "Request failed");
    throw new Error(
      `Failed to load agents API status (${res.status}): ${message}`,
    );
  }
  return res.json() as Promise<{ enabled: boolean }>;
}

export async function listAgents(): Promise<Agent[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    throw new Error(err.detail ?? `Failed to load agents: ${res.statusText}`);
  }
  const data = (await res.json()) as { agents: Agent[] };
  return data.agents;
}

export async function getAgent(name: string): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    if (res.status === 404) {
      throw new Error(`Agent '${name}' not found`);
    }
    throw new Error(err.detail ?? `Failed to load agent: ${res.statusText}`);
  }
  return res.json() as Promise<Agent>;
}

export async function createAgent(request: CreateAgentRequest): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    throw new Error(err.detail ?? `Failed to create agent: ${res.statusText}`);
  }
  return res.json() as Promise<Agent>;
}

export async function updateAgent(
  name: string,
  request: UpdateAgentRequest,
): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    throw new Error(err.detail ?? `Failed to update agent: ${res.statusText}`);
  }
  return res.json() as Promise<Agent>;
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentsApiDisabledError(err.detail);
    }
    throw new Error(err.detail ?? `Failed to delete agent: ${res.statusText}`);
  }
}

export async function checkAgentName(
  name: string,
): Promise<{ available: boolean; name: string }> {
  let res: Response;
  try {
    res = await fetch(
      `${getBackendBaseURL()}/api/agents/check?name=${encodeURIComponent(name)}`,
    );
  } catch {
    throw new AgentNameCheckError(
      "Could not reach the DeerFlow backend.",
      "backend_unreachable",
    );
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (BACKEND_UNAVAILABLE_STATUSES.has(res.status)) {
      throw new AgentNameCheckError(
        "Could not reach the DeerFlow backend.",
        "backend_unreachable",
      );
    }
    if (isAgentsApiDisabledResponse(res.status, err.detail)) {
      throw new AgentNameCheckError(
        err.detail ??
          "Custom-agent management API is disabled. Set agents_api.enabled=true in config.yaml.",
        "api_disabled",
      );
    }
    throw new AgentNameCheckError(
      err.detail ?? `Failed to check agent name: ${res.statusText}`,
      "request_failed",
    );
  }
  return res.json() as Promise<{ available: boolean; name: string }>;
}
