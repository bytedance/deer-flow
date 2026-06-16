/**
 * Tests for the error-handling behaviour of the MCP config API client.
 *
 * Issue #3527: when a non-admin user opens Settings → Tools, the gateway
 * returns 403 `{detail: "Admin privileges required to manage MCP
 * configuration."}` for `GET /api/mcp/config`. The previous client
 * silently treated the 403 body as a valid `MCPConfig`, so the UI then
 * crashed with `Cannot convert undefined or null to object` when it tried
 * `Object.entries(config.mcp_servers)`.
 *
 * These tests pin the contract that non-2xx responses are surfaced as
 * `MCPConfigRequestError` carrying the HTTP status and backend `detail`,
 * so the React Query hook's `error` branch can render a friendly empty
 * state (admin-required for 403) instead of crashing.
 */
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/core/api/fetcher", () => ({
  fetch: vi.fn(),
}));

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  MCPConfigRequestError,
  loadMCPConfig,
  updateMCPConfig,
} from "@/core/mcp/api";

const mockedFetch = vi.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("loadMCPConfig", () => {
  test("returns parsed config on 200", async () => {
    const config = { mcp_servers: { foo: { enabled: true } } };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, config));
    await expect(loadMCPConfig()).resolves.toEqual(config);
  });

  test("throws MCPConfigRequestError with isAdminRequired on 403 (issue #3527)", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail: "Admin privileges required to manage MCP configuration.",
      }),
    );
    await expect(loadMCPConfig()).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 403,
      isAdminRequired: true,
      message: "Admin privileges required to manage MCP configuration.",
    });
  });

  test("throws MCPConfigRequestError with isAdminRequired=false on non-403 errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(loadMCPConfig()).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 500,
      isAdminRequired: false,
      message: "Failed to load MCP configuration",
    });
  });

  test("the rejected value is an instance of MCPConfigRequestError", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "nope" }));
    await expect(loadMCPConfig()).rejects.toBeInstanceOf(MCPConfigRequestError);
  });
});

describe("updateMCPConfig", () => {
  test("returns parsed body on 200", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    await expect(updateMCPConfig({ mcp_servers: {} })).resolves.toEqual({
      ok: true,
    });
  });

  test("throws MCPConfigRequestError with isAdminRequired on 403", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail: "Admin privileges required to manage MCP configuration.",
      }),
    );
    await expect(updateMCPConfig({ mcp_servers: {} })).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 403,
      isAdminRequired: true,
      message: "Admin privileges required to manage MCP configuration.",
    });
  });

  test("falls back to generic message on non-403 errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(updateMCPConfig({ mcp_servers: {} })).rejects.toMatchObject({
      name: "MCPConfigRequestError",
      status: 500,
      isAdminRequired: false,
      message: "Failed to update MCP configuration",
    });
  });
});
