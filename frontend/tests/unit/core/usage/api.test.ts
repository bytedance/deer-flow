import { beforeEach, expect, rs, test } from "@rstest/core";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "https://gateway.example",
}));

import { GatewayApiError } from "@/core/api/errors";
import { fetchUsage, fetchUsageRuns } from "@/core/usage/api";

beforeEach(() => mocks.fetch.mockReset());

test("sends local-day offset and propagates cancellation to the authenticated fetcher", async () => {
  const controller = new AbortController();
  mocks.fetch.mockResolvedValue(Response.json({ days: [] }));
  await fetchUsage(30, 480, controller.signal);
  const [address, options] = mocks.fetch.mock.calls[0]!;
  const url = new URL(address as string);
  expect(url.origin).toBe("https://gateway.example");
  expect(url.pathname).toBe("/api/console/usage");
  expect(url.searchParams.get("days")).toBe("30");
  expect(url.searchParams.get("tz_offset_minutes")).toBe("480");
  expect((options as RequestInit).signal).toBe(controller.signal);
});

test("all-status pages omit the status filter; failures send the real backend status", async () => {
  mocks.fetch.mockImplementation(async () =>
    Response.json({ runs: [], has_more: false }),
  );
  await fetchUsageRuns(20, "all");
  await fetchUsageRuns(0, "timeout");
  const first = new URL(mocks.fetch.mock.calls[0]![0] as string);
  const second = new URL(mocks.fetch.mock.calls[1]![0] as string);
  expect(first.searchParams.get("offset")).toBe("20");
  expect(first.searchParams.get("limit")).toBe("20");
  expect(first.searchParams.has("status")).toBe(false);
  expect(second.searchParams.get("status")).toBe("timeout");
});

test.each([403, 404, 503])(
  "preserves HTTP %s for localized recovery UI",
  async (status) => {
    mocks.fetch.mockResolvedValue(
      Response.json({ detail: "Unavailable" }, { status }),
    );
    await expect(fetchUsage(7, 0)).rejects.toBeInstanceOf(GatewayApiError);
    mocks.fetch.mockResolvedValue(
      Response.json({ detail: "Unavailable" }, { status }),
    );
    await expect(fetchUsageRuns(0, "all")).rejects.toMatchObject({ status });
  },
);
