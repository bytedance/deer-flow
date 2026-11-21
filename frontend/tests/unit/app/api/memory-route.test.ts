import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { NextRequest } from "next/server";

import { POST as postMemoryPath } from "@/app/api/memory/[...path]/route";
import { DELETE as deleteMemory } from "@/app/api/memory/route";

describe("memory API proxy", () => {
  afterEach(() => {
    rs.restoreAllMocks();
  });

  it("preserves the selected agent on root destructive requests", async () => {
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const request = new NextRequest(
      "http://deer-flow.test/api/memory?agent_name=Research-Agent",
      { method: "DELETE" },
    );

    await deleteMemory(request);

    const [target] = fetchMock.mock.calls[0]!;
    expect(target).toBeInstanceOf(URL);
    if (!(target instanceof URL)) {
      throw new Error("Memory proxy target must be a URL");
    }
    expect(target.href).toBe(
      "http://127.0.0.1:8001/api/memory?agent_name=Research-Agent",
    );
  });

  it("preserves the full query string on nested memory requests", async () => {
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const request = new NextRequest(
      "http://deer-flow.test/api/memory/import?agent_name=Research-Agent&mode=facts%2Bmetadata",
      {
        method: "POST",
        body: JSON.stringify({ facts: [] }),
      },
    );

    await postMemoryPath(request, {
      params: Promise.resolve({ path: ["import"] }),
    });

    const [target] = fetchMock.mock.calls[0]!;
    expect(target).toBeInstanceOf(URL);
    if (!(target instanceof URL)) {
      throw new Error("Memory proxy target must be a URL");
    }
    expect(target.href).toBe(
      "http://127.0.0.1:8001/api/memory/import?agent_name=Research-Agent&mode=facts%2Bmetadata",
    );
  });

  it("proxies to the Gateway configured for the /api rewrites", async () => {
    const saved = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = "http://gateway:8001/";
    rs.resetModules();
    try {
      const { GET: getMemory } = await import("@/app/api/memory/route");
      const { GET: getMemoryPath } =
        await import("@/app/api/memory/[...path]/route");
      const fetchMock = rs
        .spyOn(globalThis, "fetch")
        .mockImplementation(async () => new Response("{}", { status: 200 }));

      await getMemory(new NextRequest("http://deer-flow.test/api/memory"));
      await getMemoryPath(
        new NextRequest("http://deer-flow.test/api/memory/export"),
        { params: Promise.resolve({ path: ["export"] }) },
      );

      const targets = fetchMock.mock.calls.map(([target]) =>
        target instanceof URL ? target.href : target,
      );
      expect(targets).toEqual([
        "http://gateway:8001/api/memory",
        "http://gateway:8001/api/memory/export",
      ]);
    } finally {
      if (saved === undefined) {
        delete process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
      } else {
        process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = saved;
      }
      rs.resetModules();
    }
  });

  it("trims surrounding whitespace from the public Gateway override", async () => {
    const saved = process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
    process.env.NEXT_PUBLIC_BACKEND_BASE_URL = " http://gateway:8001/ ";
    rs.resetModules();
    try {
      const { DELETE: deleteMemoryAt } = await import("@/app/api/memory/route");
      const { POST: postMemoryPathAt } =
        await import("@/app/api/memory/[...path]/route");
      const fetchMock = rs
        .spyOn(globalThis, "fetch")
        .mockImplementation(async () => new Response("{}", { status: 200 }));

      await deleteMemoryAt(
        new NextRequest("http://deer-flow.test/api/memory", {
          method: "DELETE",
        }),
      );
      await postMemoryPathAt(
        new NextRequest("http://deer-flow.test/api/memory/export", {
          method: "POST",
          body: "{}",
        }),
        { params: Promise.resolve({ path: ["export"] }) },
      );

      const targets = fetchMock.mock.calls.map(([target]) =>
        target instanceof URL ? target.href : target,
      );
      expect(targets).toEqual([
        "http://gateway:8001/api/memory",
        "http://gateway:8001/api/memory/export",
      ]);
    } finally {
      if (saved === undefined) {
        delete process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
      } else {
        process.env.NEXT_PUBLIC_BACKEND_BASE_URL = saved;
      }
      rs.resetModules();
    }
  });

  it.each([
    "http://gateway:8001/private-gateway",
    "http://gateway:8001/private-gateway/",
  ])("keeps the path prefix of the Gateway base %s", async (baseUrl) => {
    const saved = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = baseUrl;
    rs.resetModules();
    try {
      const { DELETE: deleteMemoryAt } = await import("@/app/api/memory/route");
      const { POST: postMemoryPathAt } =
        await import("@/app/api/memory/[...path]/route");
      const fetchMock = rs
        .spyOn(globalThis, "fetch")
        .mockImplementation(async () => new Response("{}", { status: 200 }));

      await deleteMemoryAt(
        new NextRequest(
          "http://deer-flow.test/api/memory?agent_name=Research-Agent",
          { method: "DELETE" },
        ),
      );
      await postMemoryPathAt(
        new NextRequest(
          "http://deer-flow.test/api/memory/import?agent_name=Research-Agent",
          { method: "POST", body: "{}" },
        ),
        { params: Promise.resolve({ path: ["import"] }) },
      );

      const targets = fetchMock.mock.calls.map(([target]) =>
        target instanceof URL ? target.href : target,
      );
      expect(targets).toEqual([
        "http://gateway:8001/private-gateway/api/memory?agent_name=Research-Agent",
        "http://gateway:8001/private-gateway/api/memory/import?agent_name=Research-Agent",
      ]);
    } finally {
      if (saved === undefined) {
        delete process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
      } else {
        process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = saved;
      }
      rs.resetModules();
    }
  });
});
