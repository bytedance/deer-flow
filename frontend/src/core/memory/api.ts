import { getBackendBaseURL } from "../config";

import type { UserMemory } from "./types";

export async function loadMemory() {
  const memory = await fetch(`${getBackendBaseURL()}/api/memory`);
  const json = await memory.json();
  return json as UserMemory;
}

export async function deleteMemoryFact(factId: string) {
  const res = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(`Failed to delete fact: ${res.statusText}`);
  }
  return res.json() as Promise<{ success: boolean }>;
}

export async function clearAllMemory() {
  const res = await fetch(`${getBackendBaseURL()}/api/memory`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Failed to clear memory: ${res.statusText}`);
  }
  return res.json() as Promise<UserMemory>;
}
