import { beforeEach, expect, test, rs } from "@rstest/core";

import { GatewayApiError } from "@/core/api/errors";
import { fetch as fetcher } from "@/core/api/fetcher";
import {
  loadChannelNotificationPreferences,
  updateChannelNotificationPreference,
} from "@/core/channels/notification-preferences";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

const defaults = { feishu: true, wecom: true, wechat: true, qq: true };
beforeEach(() => {
  rs.mocked(fetcher).mockReset();
});

test("loads effective preferences with an expected-owner fence and consumed signal", async () => {
  rs.mocked(fetcher).mockResolvedValue(new Response(JSON.stringify(defaults)));
  const signal = new AbortController().signal;
  expect(await loadChannelNotificationPreferences("default", signal)).toEqual(
    defaults,
  );
  expect(rs.mocked(fetcher)).toHaveBeenCalledWith(
    "/backend/api/channels/notification-preferences",
    expect.objectContaining({
      method: "GET",
      signal,
      headers: expect.objectContaining({ "X-Expected-User-Id": "default" }),
    }),
  );
});

test("updates exactly one provider, preserving false and the authenticated viewer header", async () => {
  rs.mocked(fetcher).mockResolvedValue(
    new Response(JSON.stringify({ ...defaults, qq: false })),
  );
  const signal = new AbortController().signal;
  expect(
    (await updateChannelNotificationPreference("alice", "qq", false, signal))
      .qq,
  ).toBe(false);
  expect(rs.mocked(fetcher)).toHaveBeenCalledWith(
    "/backend/api/channels/notification-preferences",
    expect.objectContaining({
      method: "PATCH",
      signal,
      body: '{"qq":false}',
      headers: expect.objectContaining({ "X-Expected-User-Id": "alice" }),
    }),
  );
});

test.each([{ feishu: true }, { ...defaults, qq: "false" }, null])(
  "rejects malformed effective preferences instead of inventing defaults",
  async (body) => {
    rs.mocked(fetcher).mockResolvedValue(new Response(JSON.stringify(body)));
    await expect(
      loadChannelNotificationPreferences("alice", new AbortController().signal),
    ).rejects.toThrow();
  },
);

test("keeps an unavailable endpoint distinguishable from valid default values", async () => {
  rs.mocked(fetcher).mockResolvedValue(
    new Response('{"detail":"Not found"}', { status: 404 }),
  );
  await expect(
    loadChannelNotificationPreferences("alice", new AbortController().signal),
  ).rejects.toBeInstanceOf(GatewayApiError);
});

test("updates a runtime notification event key and parses optional event fields", async () => {
  rs.mocked(fetcher).mockResolvedValue(
    new Response(
      JSON.stringify({
        ...defaults,
        run_completed: true,
        run_failed: false,
        human_input_requested: true,
      }),
    ),
  );
  const signal = new AbortController().signal;
  const updated = await updateChannelNotificationPreference(
    "alice",
    "human_input_requested",
    true,
    signal,
  );
  expect(updated.human_input_requested).toBe(true);
  expect(updated.run_completed).toBe(true);
  expect(updated.run_failed).toBe(false);
  expect(rs.mocked(fetcher)).toHaveBeenCalledWith(
    "/backend/api/channels/notification-preferences",
    expect.objectContaining({
      method: "PATCH",
      signal,
      body: '{"human_input_requested":true}',
      headers: expect.objectContaining({ "X-Expected-User-Id": "alice" }),
    }),
  );
});
