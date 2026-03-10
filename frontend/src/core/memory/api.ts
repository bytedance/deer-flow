import { getBackendBaseURL } from "../config";

import type { MemoryConfig, UserMemory } from "./types";

export async function loadMemory() {
  const memory = await fetch(`${getBackendBaseURL()}/api/memory`);
  const json = await memory.json();
  return json as UserMemory;
}

export async function loadMemoryConfig(): Promise<MemoryConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/config`);
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
  return res.json() as Promise<MemoryConfig>;
}

export async function deleteMemoryFact(factId: string): Promise<void> {
  await fetch(`${getBackendBaseURL()}/api/memory/facts/${factId}`, {
    method: "DELETE",
  });
}
