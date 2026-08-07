import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

/**
 * Build a memory endpoint URL with the optional agent fact-bucket selector.
 * Facts are bucketed per custom agent on the backend; ``agentName`` selects
 * the bucket (null/empty selects the default bucket). Summaries are
 * user-global and shared across agents either way.
 */
function memoryUrl(path: string, agentName?: string | null): string {
  const base = `${getBackendBaseURL()}${path}`;
  return agentName
    ? `${base}?agent_name=${encodeURIComponent(agentName)}`
    : base;
}

async function readMemoryResponse(
  response: Response,
  fallbackMessage: string,
): Promise<UserMemory> {
  function formatErrorDetail(detail: unknown): string | null {
    if (typeof detail === "string") {
      return detail;
    }

    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === "string") {
            return item;
          }

          if (item && typeof item === "object") {
            const record = item as Record<string, unknown>;
            if (typeof record.msg === "string") {
              return record.msg;
            }

            try {
              return JSON.stringify(record);
            } catch {
              return null;
            }
          }

          return String(item);
        })
        .filter(Boolean);

      return parts.length > 0 ? parts.join("; ") : null;
    }

    if (detail && typeof detail === "object") {
      try {
        return JSON.stringify(detail);
      } catch {
        return null;
      }
    }

    if (
      typeof detail === "string" ||
      typeof detail === "number" ||
      typeof detail === "boolean" ||
      typeof detail === "bigint"
    ) {
      return String(detail);
    }

    if (typeof detail === "symbol") {
      return detail.description ?? null;
    }

    return null;
  }

  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detailMessage = formatErrorDetail(errorData.detail);
    throw new Error(
      detailMessage ?? `${fallbackMessage}: ${response.statusText}`,
    );
  }

  return response.json() as Promise<UserMemory>;
}

export async function loadMemory(
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(memoryUrl("/api/memory", agentName));
  return readMemoryResponse(response, "Failed to fetch memory");
}

export async function clearMemory(
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(memoryUrl("/api/memory", agentName), {
    method: "DELETE",
  });
  return readMemoryResponse(response, "Failed to clear memory");
}

export async function deleteMemoryFact(
  factId: string,
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(
    memoryUrl(`/api/memory/facts/${encodeURIComponent(factId)}`, agentName),
    {
      method: "DELETE",
    },
  );
  return readMemoryResponse(response, "Failed to delete memory fact");
}

export async function exportMemory(
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(memoryUrl("/api/memory/export", agentName));
  return readMemoryResponse(response, "Failed to export memory");
}

export async function importMemory(
  memory: UserMemory,
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(memoryUrl("/api/memory/import", agentName), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(memory),
  });
  return readMemoryResponse(response, "Failed to import memory");
}

export async function createMemoryFact(
  input: MemoryFactInput,
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(memoryUrl("/api/memory/facts", agentName), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  return readMemoryResponse(response, "Failed to create memory fact");
}

export async function updateMemoryFact(
  factId: string,
  input: MemoryFactPatchInput,
  agentName?: string | null,
): Promise<UserMemory> {
  const response = await fetch(
    memoryUrl(`/api/memory/facts/${encodeURIComponent(factId)}`, agentName),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(input),
    },
  );
  return readMemoryResponse(response, "Failed to update memory fact");
}
