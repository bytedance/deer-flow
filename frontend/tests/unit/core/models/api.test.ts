import { afterEach, expect, test, rs } from "@rstest/core";

import { UnauthorizedError } from "@/core/api/errors";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("loadModels includes credentials for authenticated gateway requests", async () => {
  let requestedInit: RequestInit | undefined;
  const fetchMock = rs.fn(
    async (_input: RequestInfo | URL, init?: RequestInit) => {
      requestedInit = init;
      return new Response(
        JSON.stringify({
          models: [
            {
              id: "model-1",
              name: "model-1",
              model: "model-1",
              display_name: "Model 1",
            },
          ],
          token_usage: { enabled: true },
        }),
        { status: 200 },
      );
    },
  );
  rs.stubGlobal("fetch", fetchMock);

  const { loadModels } = await import("@/core/models/api");

  await expect(loadModels()).resolves.toMatchObject({
    models: [{ id: "model-1" }],
    token_usage: { enabled: true },
  });
  expect(requestedInit?.credentials).toBe("include");
});

test("loadModels rejects unsuccessful gateway responses", async () => {
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Model registry unavailable" }), {
          status: 503,
          statusText: "Service Unavailable",
        }),
    ),
  );

  const { loadModels } = await import("@/core/models/api");

  await expect(loadModels()).rejects.toThrow("Model registry unavailable");
});

test("loadModels exposes the typed 401 redirect error", async () => {
  const location = { href: "", pathname: "/workspace/chats" };
  rs.stubGlobal("window", { location });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => new Response(null, { status: 401 })),
  );

  const { loadModels } = await import("@/core/models/api");

  await expect(loadModels()).rejects.toBeInstanceOf(UnauthorizedError);
  expect(location.href).toBe("/login?next=%2Fworkspace%2Fchats");
});

test("loadModels includes the status code when statusText is empty", async () => {
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response("upstream unavailable", {
          status: 503,
          statusText: "",
        }),
    ),
  );

  const { loadModels } = await import("@/core/models/api");

  await expect(loadModels()).rejects.toThrow("Failed to load models: 503");
});
