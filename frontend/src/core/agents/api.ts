import { apiFetch, apiJson } from "@/core/api/fetch";

import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "./types";

export async function listAgents(): Promise<Agent[]> {
  const data = await apiJson<{ agents: Agent[] }>("/api/agents");
  return data.agents;
}

export async function getAgent(name: string): Promise<Agent> {
  return apiJson<Agent>(`/api/agents/${name}`);
}

export async function createAgent(request: CreateAgentRequest): Promise<Agent> {
  return apiJson<Agent>("/api/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function updateAgent(
  name: string,
  request: UpdateAgentRequest,
): Promise<Agent> {
  return apiJson<Agent>(`/api/agents/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function deleteAgent(name: string): Promise<void> {
  await apiFetch(`/api/agents/${name}`, { method: "DELETE" });
}

export async function checkAgentName(
  name: string,
): Promise<{ available: boolean; name: string }> {
  return apiJson<{ available: boolean; name: string }>(
    `/api/agents/check?name=${encodeURIComponent(name)}`,
  );
}
