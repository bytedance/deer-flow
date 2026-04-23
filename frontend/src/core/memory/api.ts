import { gatewayFetch } from "@/core/api/gateway-fetch";

import { getBackendBaseURL } from "../config";

import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

function withThreadQuery(url: string, threadId: string): string {
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}thread_id=${encodeURIComponent(threadId)}`;
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

export async function loadMemory(threadId: string): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(`${getBackendBaseURL()}/api/memory`, threadId),
  );
  return readMemoryResponse(response, "Failed to fetch memory");
}

export async function clearMemory(threadId: string): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(`${getBackendBaseURL()}/api/memory`, threadId),
    {
      method: "DELETE",
    },
  );
  return readMemoryResponse(response, "Failed to clear memory");
}

export async function deleteMemoryFact(
  threadId: string,
  factId: string,
): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(
      `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
      threadId,
    ),
    {
      method: "DELETE",
    },
  );
  return readMemoryResponse(response, "Failed to delete memory fact");
}

export async function exportMemory(threadId: string): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(`${getBackendBaseURL()}/api/memory/export`, threadId),
  );
  return readMemoryResponse(response, "Failed to export memory");
}

export async function importMemory(
  threadId: string,
  memory: UserMemory,
): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(`${getBackendBaseURL()}/api/memory/import`, threadId),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(memory),
    },
  );
  return readMemoryResponse(response, "Failed to import memory");
}

export async function createMemoryFact(
  threadId: string,
  input: MemoryFactInput,
): Promise<UserMemory> {
  const response = await gatewayFetch(
    `${getBackendBaseURL()}/api/memory/facts`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ thread_id: threadId, ...input }),
    },
  );
  return readMemoryResponse(response, "Failed to create memory fact");
}

export async function updateMemoryFact(
  threadId: string,
  factId: string,
  input: MemoryFactPatchInput,
): Promise<UserMemory> {
  const response = await gatewayFetch(
    withThreadQuery(
      `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
      threadId,
    ),
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
