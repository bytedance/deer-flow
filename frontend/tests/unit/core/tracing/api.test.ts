import { afterEach, expect, it, rs } from "@rstest/core";

import { GatewayApiError } from "@/core/api/errors";
import { fetch as fetcher } from "@/core/api/fetcher";
import {
  loadAgentTracing,
  saveAgentTracing,
  saveTracingProfile,
} from "@/core/tracing/api";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
afterEach(() => {
  rs.resetAllMocks();
});

it("encodes agent names and forwards cancellation to tracing reads", async () => {
  const abort = new AbortController();
  rs.mocked(fetcher).mockResolvedValue(new Response("{}"));
  await loadAgentTracing("a/b", abort.signal);
  expect(fetcher).toHaveBeenCalledWith("/backend/api/agents/a%2Fb/tracing", {
    signal: abort.signal,
  });
});

it.each(["inherit", "disabled", "configured"] as const)(
  "saves the %s mode with its expected revision",
  async (mode) => {
    rs.mocked(fetcher).mockResolvedValue(new Response("{}"));
    await saveAgentTracing("research", {
      mode,
      profile_id: mode === "configured" ? "qa" : null,
      expected_revision: 4,
    });
    const [, init] = rs.mocked(fetcher).mock.calls[0]!;
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init!.body as string)).toEqual({
      mode,
      profile_id: mode === "configured" ? "qa" : null,
      expected_revision: 4,
    });
  },
);

it("creates profiles without an id and updates existing profiles on their resource", async () => {
  rs.mocked(fetcher).mockImplementation(async () => new Response("{}"));
  const body = {
    name: "QA",
    expected_revision: 0,
    providers: [],
    allowed_user_ids: ["alice"],
  };
  await saveTracingProfile(null, body);
  expect(rs.mocked(fetcher).mock.calls[0]?.[0]).toBe(
    "/backend/api/tracing/profiles",
  );
  expect(rs.mocked(fetcher).mock.calls[0]?.[1]?.method).toBe("POST");
  await saveTracingProfile("profile/id", { ...body, expected_revision: 2 });
  expect(rs.mocked(fetcher).mock.calls[1]?.[0]).toBe(
    "/backend/api/tracing/profiles/profile%2Fid",
  );
  expect(rs.mocked(fetcher).mock.calls[1]?.[1]?.method).toBe("PUT");
});

it("keeps coded revision conflicts available to the editor", async () => {
  rs.mocked(fetcher).mockResolvedValue(
    new Response(
      JSON.stringify({
        detail: { code: "revision_conflict", message: "Changed elsewhere" },
      }),
      { status: 409 },
    ),
  );
  await expect(
    saveAgentTracing("research", {
      mode: "disabled",
      profile_id: null,
      expected_revision: 1,
    }),
  ).rejects.toBeInstanceOf(GatewayApiError);
});
