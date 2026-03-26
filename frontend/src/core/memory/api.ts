import { getBackendBaseURL } from "../config";

import type { UserMemory } from "./types";

async function readMemoryResponse(response: Response): Promise<UserMemory> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(
      errorData.detail ?? `Failed to update memory: ${response.statusText}`,
    );
  }

  return response.json() as Promise<UserMemory>;
}

export async function loadMemory(): Promise<UserMemory> {
  const response = await fetch(`${getBackendBaseURL()}/api/memory`);
  return readMemoryResponse(response);
}

export async function clearMemory(): Promise<UserMemory> {
  const response = await fetch(`${getBackendBaseURL()}/api/memory`, {
    method: "DELETE",
  });
  return readMemoryResponse(response);
}

export async function deleteMemoryFact(factId: string): Promise<UserMemory> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
    {
      method: "DELETE",
    },
  );
  return readMemoryResponse(response);
}
