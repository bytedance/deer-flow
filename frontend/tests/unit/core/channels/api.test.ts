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
            provider: "telegram",
            display_name: "Telegram",
            enabled: true,
            configured: true,
            auth_mode: "deep_link",
            connection_status: "not_connected",
            credential_values: {
              bot_token: "********",
              bot_username: "deerflow_bot",
            },
          },
        ],
      }),
    );

    await expect(listChannelProviders()).resolves.toMatchObject({
      enabled: true,
      providers: [
        {
          provider: "telegram",
          display_name: "Telegram",
          credential_values: {
            bot_token: "********",
            bot_username: "deerflow_bot",
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
            provider: "telegram",
            status: "connected",
            external_account_name: "Alice",
            scopes: [],
            metadata: {},
          },
        ],
      }),
    );

    await expect(listChannelConnections()).resolves.toMatchObject([
      { id: "connection-1", provider: "telegram", status: "connected" },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/connections",
    );
  });

  test("starts a provider connection flow", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "telegram",
        mode: "deep_link",
        url: "https://t.me/deerflow_bot?start=state",
        code: "state",
        instruction: "Send /start state to the DeerFlow Telegram bot.",
        expires_in: 600,
      }),
    );

    await expect(connectChannelProvider("telegram")).resolves.toMatchObject({
      provider: "telegram",
      url: "https://t.me/deerflow_bot?start=state",
      instruction: "Send /start state to the DeerFlow Telegram bot.",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/telegram/connect",
      { method: "POST" },
    );
  });

  test("starts a binding-code connection flow", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "slack",
        mode: "binding_code",
        url: null,
        code: "abc123",
        instruction: "Send /connect abc123 to the DeerFlow Slack bot.",
        expires_in: 600,
      }),
    );

    await expect(connectChannelProvider("slack")).resolves.toMatchObject({
      provider: "slack",
      url: null,
      code: "abc123",
      instruction: "Send /connect abc123 to the DeerFlow Slack bot.",
    });
  });

  test("submits runtime provider configuration", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        provider: "slack",
        display_name: "Slack",
        enabled: true,
        configured: true,
        connectable: true,
        auth_mode: "binding_code",
        connection_status: "not_connected",
      }),
    );

    await expect(
      configureChannelProvider("slack", {
        bot_token: "xoxb-ui",
        app_token: "xapp-ui",
      }),
    ).resolves.toMatchObject({
      provider: "slack",
      configured: true,
      connectable: true,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/slack/runtime-config",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          values: { bot_token: "xoxb-ui", app_token: "xapp-ui" },
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
        provider: "slack",
        display_name: "Slack",
        enabled: true,
        configured: false,
        connectable: false,
        auth_mode: "binding_code",
        connection_status: "not_connected",
      }),
    );

    await expect(disconnectChannelProvider("slack")).resolves.toMatchObject({
      provider: "slack",
      configured: false,
      connection_status: "not_connected",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/channels/slack/runtime-config",
      { method: "DELETE" },
    );
  });

  test("uses backend detail for failed requests", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, { detail: "Channel provider is not configured" }),
    );

    await expect(connectChannelProvider("slack")).rejects.toThrow(
      "Channel provider is not configured",
    );
  });
});
