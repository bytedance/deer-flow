import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  configureChannelProvider,
  connectChannelProvider,
  disconnectChannelConnection,
  disconnectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "@/core/channels/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("channels api", () => {
  test("loads provider catalog", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        enabled: true,
        providers: [
          {
            provider: "feishu",
            display_name: "Feishu",
            enabled: true,
            configured: true,
            auth_mode: "binding_code",
            connection_status: "not_connected",
            credential_values: {
              app_id: "feishu-app",
              app_secret: "********",
            },
          },
        ],
      }),
    );

    await expect(listChannelProviders()).resolves.toMatchObject({
      enabled: true,
      providers: [
        {
          provider: "feishu",
          display_name: "Feishu",
          credential_values: {
            app_id: "feishu-app",
            app_secret: "********",
          },
        },
      ],
    });
    expect(mockedFetch).toHaveBeenCalledWith("/backend/api/channels/providers");
  });

  test("loads current user's connections", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        connections: [
          {
            id: "connection-1",
            provider: "feishu",
            status: "connected",
            external_account_name: "Alice",
            scopes: [],
            metadata: {},
          },
        ],
      }),
    );

    await expect(listChannelConnections()).resolves.toMatchObject([
      { id: "connection-1", provider: "feishu", status: "connected" },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/connections",
    );
  });

  test("starts a provider connection flow", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "feishu",
        mode: "binding_code",
        url: null,
        code: "state",
        instruction: "Send /connect state to the DeerFlow Feishu bot.",
        expires_in: 600,
      }),
    );

    await expect(connectChannelProvider("feishu")).resolves.toMatchObject({
      provider: "feishu",
      url: null,
      instruction: "Send /connect state to the DeerFlow Feishu bot.",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/feishu/connect",
      { method: "POST" },
    );
  });

  test("starts a binding-code connection flow", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "dingtalk",
        mode: "binding_code",
        url: null,
        code: "abc123",
        instruction: "Send /connect abc123 to the DeerFlow DingTalk bot.",
        expires_in: 600,
      }),
    );

    await expect(connectChannelProvider("dingtalk")).resolves.toMatchObject({
      provider: "dingtalk",
      url: null,
      code: "abc123",
      instruction: "Send /connect abc123 to the DeerFlow DingTalk bot.",
    });
  });

  test("submits runtime provider configuration", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "feishu",
        display_name: "Feishu",
        enabled: true,
        configured: true,
        connectable: true,
        auth_mode: "binding_code",
        connection_status: "not_connected",
      }),
    );

    await expect(
      configureChannelProvider("feishu", {
        app_id: "feishu-ui",
        app_secret: "secret-ui",
      }),
    ).resolves.toMatchObject({
      provider: "feishu",
      configured: true,
      connectable: true,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/feishu/runtime-config",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          values: { app_id: "feishu-ui", app_secret: "secret-ui" },
        }),
      },
    );
  });

  test("disconnects a channel connection", async () => {
    mockedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(
      disconnectChannelConnection("connection-1"),
    ).resolves.toBeUndefined();
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/connections/connection-1",
      { method: "DELETE" },
    );
  });

  test("disconnects provider runtime configuration", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "feishu",
        display_name: "Feishu",
        enabled: true,
        configured: false,
        connectable: false,
        auth_mode: "binding_code",
        connection_status: "not_connected",
      }),
    );

    await expect(disconnectChannelProvider("feishu")).resolves.toMatchObject({
      provider: "feishu",
      configured: false,
      connection_status: "not_connected",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/feishu/runtime-config",
      { method: "DELETE" },
    );
  });

  test("uses backend detail for failed requests", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, { detail: "Channel provider is not configured" }),
    );

    await expect(connectChannelProvider("feishu")).rejects.toThrow(
      "Channel provider is not configured",
    );
  });
});