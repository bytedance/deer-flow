import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";

import type {
  AuditEntry,
  DomainFact,
  DomainFactCreateInput,
  MemoryFactInput,
  MemoryFactPatchInput,
  SessionMemory,
  UserMemory,
} from "./types";

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

export async function loadMemory(): Promise<UserMemory> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/memory`);
  return readMemoryResponse(response, "Failed to fetch memory");
}

export async function clearMemory(): Promise<UserMemory> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/memory`, {
    method: "DELETE",
  });
  return readMemoryResponse(response, "Failed to clear memory");
}

export async function deleteMemoryFact(factId: string): Promise<UserMemory> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
    {
      method: "DELETE",
    },
  );
  return readMemoryResponse(response, "Failed to delete memory fact");
}

export async function exportMemory(): Promise<UserMemory> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/memory/export`);
  return readMemoryResponse(response, "Failed to export memory");
}

export async function importMemory(memory: UserMemory): Promise<UserMemory> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/memory/import`, {
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
): Promise<UserMemory> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/memory/facts`, {
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
): Promise<UserMemory> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
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

async function readJsonResponse<T>(
  response: Response,
  fallbackMessage: string,
): Promise<T> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail =
      typeof errorData.detail === "string"
        ? errorData.detail
        : `${fallbackMessage}: ${response.statusText}`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Session Memory
// ---------------------------------------------------------------------------

export async function loadSessionMemory(
  threadId: string,
): Promise<SessionMemory> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/session?thread_id=${encodeURIComponent(threadId)}`,
  );
  return readJsonResponse<SessionMemory>(
    response,
    "Failed to fetch session memory",
  );
}

export async function exportSessionMemory(
  threadId: string,
): Promise<SessionMemory> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/session/export?thread_id=${encodeURIComponent(threadId)}`,
  );
  return readJsonResponse<SessionMemory>(
    response,
    "Failed to export session memory",
  );
}

export async function importSessionMemory(
  threadId: string,
  facts: SessionMemory["facts"],
): Promise<SessionMemory> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/session/import`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, facts }),
    },
  );
  return readJsonResponse<SessionMemory>(
    response,
    "Failed to import session memory",
  );
}

// ---------------------------------------------------------------------------
// Domain Memory
// ---------------------------------------------------------------------------

export async function searchDomainMemory(
  query: string,
  options?: { domain?: string; entityId?: string; topK?: number },
): Promise<DomainFact[]> {
  const params = new URLSearchParams({ query });
  if (options?.domain) params.set("domain", options.domain);
  if (options?.entityId) params.set("entity_id", options.entityId);
  if (options?.topK) params.set("top_k", String(options.topK));

  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/domain?${params.toString()}`,
  );
  return readJsonResponse<DomainFact[]>(
    response,
    "Failed to search domain memory",
  );
}

export async function createDomainFact(
  input: DomainFactCreateInput,
): Promise<DomainFact> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/domain/facts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return readJsonResponse<DomainFact>(
    response,
    "Failed to create domain fact",
  );
}

export async function exportDomainMemory(
  options?: { domain?: string; entityId?: string },
): Promise<DomainFact[]> {
  const params = new URLSearchParams();
  if (options?.domain) params.set("domain", options.domain);
  if (options?.entityId) params.set("entity_id", options.entityId);

  const qs = params.toString();
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/domain/export${qs ? `?${qs}` : ""}`,
  );
  return readJsonResponse<DomainFact[]>(
    response,
    "Failed to export domain memory",
  );
}

export async function importDomainFacts(
  facts: DomainFactCreateInput[],
): Promise<{ imported: number; total: number }> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/domain/import`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts }),
    },
  );
  return readJsonResponse<{ imported: number; total: number }>(
    response,
    "Failed to import domain facts",
  );
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export async function loadAuditLogs(
  options?: { userId?: string; action?: string; layer?: string; limit?: number },
): Promise<AuditEntry[]> {
  const params = new URLSearchParams();
  if (options?.userId) params.set("user_id", options.userId);
  if (options?.action) params.set("action", options.action);
  if (options?.layer) params.set("layer", options.layer);
  if (options?.limit) params.set("limit", String(options.limit));

  const qs = params.toString();
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/memory/audit${qs ? `?${qs}` : ""}`,
  );
  return readJsonResponse<AuditEntry[]>(
    response,
    "Failed to fetch audit logs",
  );
}
