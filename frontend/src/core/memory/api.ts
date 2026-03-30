import type { UserMemory } from "./types";

async function readMemoryResponse(
  response: Response,
  fallbackMessage: string,
): Promise<UserMemory> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(
      errorData.detail ?? `${fallbackMessage}: ${response.statusText}`,
    );
  }

  return response.json() as Promise<UserMemory>;
}

export async function loadMemory(): Promise<UserMemory> {
  const response = await fetch("/api/memory");
  return readMemoryResponse(response, "Failed to fetch memory");
}

export async function clearMemory(): Promise<UserMemory> {
  const response = await fetch("/api/memory", {
    method: "DELETE",
  });
  return readMemoryResponse(response, "Failed to clear memory");
}

export async function deleteMemoryFact(factId: string): Promise<UserMemory> {
  const response = await fetch(`/api/memory/facts/${encodeURIComponent(factId)}`, {
    method: "DELETE",
  });
  return readMemoryResponse(response, "Failed to delete memory fact");
}

export async function exportMemory(): Promise<UserMemory> {
  const response = await fetch("/api/memory/export");
  return readMemoryResponse(response, "Failed to export memory");
}

export async function importMemory(memory: UserMemory): Promise<UserMemory> {
  const response = await fetch("/api/memory/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(memory),
  });
  return readMemoryResponse(response, "Failed to import memory");
}
