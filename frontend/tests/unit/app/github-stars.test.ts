import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { GET, revalidate } from "@/app/github-stars/route";

const { env } = rs.hoisted(() => ({ env: { GITHUB_OAUTH_TOKEN: "" } }));
rs.mock("@/env", () => ({ env }));

beforeEach(() => {
  env.GITHUB_OAUTH_TOKEN = "";
});
afterEach(() => {
  rs.restoreAllMocks();
});

describe("runtime GitHub stars", () => {
  it("does not prerender or fetch when no runtime token is configured", async () => {
    const fetch = rs.spyOn(globalThis, "fetch");
    const response = await GET();
    expect(revalidate).toBe(0);
    expect(response.status).toBe(204);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("reads the server token at request time and exposes only the count", async () => {
    env.GITHUB_OAUTH_TOKEN = "runtime-test-token";
    const fetch = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        stargazers_count: 43210,
        private_data: "not-for-the-client",
      }),
    );
    const response = await GET();
    expect(fetch).toHaveBeenCalledWith(
      "https://api.github.com/repos/bytedance/deer-flow",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer runtime-test-token",
        }),
        next: { revalidate: 3600 },
      }),
    );
    expect(await response.json()).toEqual({ stars: 43210 });
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("hides the count when GitHub rejects the token", async () => {
    env.GITHUB_OAUTH_TOKEN = "invalid-test-token";
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 401 }),
    );
    expect((await GET()).status).toBe(204);
  });

  it("hides the count on network failure without returning error details", async () => {
    env.GITHUB_OAUTH_TOKEN = "runtime-test-token";
    rs.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("private upstream details"),
    );
    const response = await GET();
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
  });

  it.each([{}, { stargazers_count: -1 }, { stargazers_count: "81900" }])(
    "hides invalid GitHub data: %j",
    async (body) => {
      env.GITHUB_OAUTH_TOKEN = "runtime-test-token";
      rs.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(body));
      expect((await GET()).status).toBe(204);
    },
  );
});
