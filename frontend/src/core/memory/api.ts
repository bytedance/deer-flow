import { getBackendBaseURL } from "../config";

import type { MemoryConfig, UserMemory } from "./types";

export async function loadMemory() {
  const memory = await fetch(`${getBackendBaseURL()}/api/memory`);
  const json = await memory.json();
  return json as UserMemory;
}

export async function loadMemoryConfig(): Promise<MemoryConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/config`);
  if (!res.ok) {
    throw new Error(`Failed to load memory config: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<MemoryConfig>;
}

export async function updateMemoryConfig(
  updates: Partial<MemoryConfig>,
): Promise<MemoryConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    throw new Error(`Failed to update memory config: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<MemoryConfig>;
}

export async function deleteMemoryFact(factId: string): Promise<void> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/facts/${factId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Failed to delete memory fact "${factId}": ${res.status} ${res.statusText}`);
  }
}
