/**
 * Tests for the memory API client's agent fact-bucket selector.
 *
 * Facts are bucketed per custom agent on the backend; the memory endpoints
 * accept an optional `agent_name` query parameter selecting the bucket
 * (omitted selects the default bucket; summaries stay user-global). These
 * tests pin the URL contract: a null/empty selector sends no query parameter,
 * a provided selector is appended URL-encoded, and every endpoint that
 * touches facts (or exports/imports the bucket view) carries it.
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  exportMemory,
  importMemory,
  loadMemory,
  updateMemoryFact,
} from "@/core/memory/api";
import type { UserMemory } from "@/core/memory/types";

const mockedFetch = rs.mocked(fetcher);

const EMPTY_MEMORY: UserMemory = {
  version: "1.0",
  lastUpdated: "",
  user: {
    workContext: { summary: "", updatedAt: "" },
    personalContext: { summary: "", updatedAt: "" },
    topOfMind: { summary: "", updatedAt: "" },
  },
  history: {
    recentMonths: { summary: "", updatedAt: "" },
    earlierContext: { summary: "", updatedAt: "" },
    longTermBackground: { summary: "", updatedAt: "" },
  },
  facts: [],
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestedUrl(callIndex: number): string {
  const call = mockedFetch.mock.calls[callIndex];
  if (!call) {
    throw new Error(`Expected fetch call #${callIndex} to exist`);
  }
  const input = call[0];
  if (typeof input !== "string") {
    throw new Error("Expected fetch to be called with a string URL");
  }
  return input;
}

beforeEach(() => {
  mockedFetch.mockReset();
  // A Response body can only be consumed once, so hand out a fresh instance
  // per call instead of sharing one across the test.
  mockedFetch.mockImplementation(() =>
    Promise.resolve(jsonResponse(EMPTY_MEMORY)),
  );
});

describe("memory api agent_name selector", () => {
  test("loadMemory omits the query parameter by default", async () => {
    await loadMemory();
    expect(requestedUrl(0)).toBe("/api/memory");
  });

  test("loadMemory omits the query parameter for null and empty selectors", async () => {
    await loadMemory(null);
    await loadMemory("");
    expect(requestedUrl(0)).toBe("/api/memory");
    expect(requestedUrl(1)).toBe("/api/memory");
  });

  test("loadMemory appends the agent_name query parameter", async () => {
    await loadMemory("coding-agent");
    expect(requestedUrl(0)).toBe("/api/memory?agent_name=coding-agent");
  });

  test("loadMemory URL-encodes the agent name", async () => {
    await loadMemory("Team Agent");
    expect(requestedUrl(0)).toBe("/api/memory?agent_name=Team%20Agent");
  });

  test("fact CRUD endpoints append the agent_name query parameter", async () => {
    await createMemoryFact(
      { content: "fact", category: "context", confidence: 0.8 },
      "coding-agent",
    );
    expect(requestedUrl(0)).toBe("/api/memory/facts?agent_name=coding-agent");

    await updateMemoryFact("fact_1", { content: "edited" }, "coding-agent");
    expect(requestedUrl(1)).toBe(
      "/api/memory/facts/fact_1?agent_name=coding-agent",
    );

    await deleteMemoryFact("fact_1", "coding-agent");
    expect(requestedUrl(2)).toBe(
      "/api/memory/facts/fact_1?agent_name=coding-agent",
    );
  });

  test("bulk endpoints append the agent_name query parameter", async () => {
    await clearMemory("coding-agent");
    expect(requestedUrl(0)).toBe("/api/memory?agent_name=coding-agent");

    await exportMemory("coding-agent");
    expect(requestedUrl(1)).toBe("/api/memory/export?agent_name=coding-agent");

    await importMemory(EMPTY_MEMORY, "coding-agent");
    expect(requestedUrl(2)).toBe("/api/memory/import?agent_name=coding-agent");
  });

  test("fact endpoints omit the query parameter by default", async () => {
    await createMemoryFact({
      content: "fact",
      category: "context",
      confidence: 0.8,
    });
    await deleteMemoryFact("fact_1");
    expect(requestedUrl(0)).toBe("/api/memory/facts");
    expect(requestedUrl(1)).toBe("/api/memory/facts/fact_1");
  });
});
