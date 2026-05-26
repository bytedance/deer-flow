import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/core/api", () => ({
  fetchGateway: vi.fn(),
}));

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://localhost:8000",
}));

import { fetchGateway } from "@/core/api";
import {
  createDomainFact,
  exportDomainMemory,
  exportSessionMemory,
  importDomainFacts,
  loadAuditLogs,
  loadSessionMemory,
  searchDomainMemory,
} from "@/core/memory/api";

const mockFetch = vi.mocked(fetchGateway);

beforeEach(() => {
  mockFetch.mockReset();
});

function mockJsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockErrorResponse(detail: string, status = 400) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Session Memory API", () => {
  it("loads session memory for a thread", async () => {
    const sessionData = { thread_id: "t1", facts: [{ id: "f1", content: "test", category: "ctx", confidence: 0.9 }] };
    mockFetch.mockResolvedValue(mockJsonResponse(sessionData));

    const result = await loadSessionMemory("t1");
    expect(result).toEqual(sessionData);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/memory/session?thread_id=t1",
    );
  });

  it("throws on session memory error", async () => {
    mockFetch.mockResolvedValue(mockErrorResponse("Thread not found", 404));
    await expect(loadSessionMemory("bad")).rejects.toThrow("Thread not found");
  });

  it("exports session memory", async () => {
    const data = { thread_id: "t1", facts: [] };
    mockFetch.mockResolvedValue(mockJsonResponse(data));

    const result = await exportSessionMemory("t1");
    expect(result).toEqual(data);
  });
});

describe("Domain Memory API", () => {
  it("searches domain memory with query", async () => {
    const facts = [{ id: "d1", content: "pump A", domain: "equipment", entity_id: "pump_a" }];
    mockFetch.mockResolvedValue(mockJsonResponse(facts));

    const result = await searchDomainMemory("pump");
    expect(result).toEqual(facts);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("query=pump"),
    );
  });

  it("searches with domain and entity filters", async () => {
    mockFetch.mockResolvedValue(mockJsonResponse([]));

    await searchDomainMemory("test", { domain: "equip", entityId: "p1" });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain("domain=equip");
    expect(url).toContain("entity_id=p1");
  });

  it("creates a domain fact", async () => {
    const fact = { id: "d2", content: "new fact", domain: "test", entity_id: "e1", confidence: 0.8 };
    mockFetch.mockResolvedValue(mockJsonResponse(fact));

    const result = await createDomainFact({
      content: "new fact",
      domain: "test",
      entity_id: "e1",
      confidence: 0.8,
    });
    expect(result).toEqual(fact);
  });

  it("exports domain memory with filters", async () => {
    mockFetch.mockResolvedValue(mockJsonResponse([]));

    await exportDomainMemory({ domain: "equip" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("domain=equip"),
    );
  });

  it("imports domain facts", async () => {
    mockFetch.mockResolvedValue(mockJsonResponse({ imported: 2, total: 2 }));

    const result = await importDomainFacts([
      { content: "f1", domain: "d", entity_id: "e", confidence: 0.5 },
      { content: "f2", domain: "d", entity_id: "e", confidence: 0.5 },
    ]);
    expect(result).toEqual({ imported: 2, total: 2 });
  });
});

describe("Audit Logs API", () => {
  it("loads audit logs with filters", async () => {
    const logs = [{ id: 1, action: "create", layer: "user", user_id: "u1" }];
    mockFetch.mockResolvedValue(mockJsonResponse(logs));

    const result = await loadAuditLogs({ action: "create", userId: "u1" });
    expect(result).toEqual(logs);
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain("action=create");
    expect(url).toContain("user_id=u1");
  });

  it("loads audit logs without filters", async () => {
    mockFetch.mockResolvedValue(mockJsonResponse([]));

    await loadAuditLogs();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/memory/audit",
    );
  });
});
