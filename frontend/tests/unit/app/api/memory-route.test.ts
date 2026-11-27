import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { NextRequest } from "next/server";

import { POST as postMemoryPath } from "@/app/api/memory/[...path]/route";
import { DELETE as deleteMemory } from "@/app/api/memory/route";

describe("memory API proxy", () => {
  afterEach(() => {
    rs.restoreAllMocks();
    rs.unstubAllEnvs();
    rs.resetModules();
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

  it.each([
    ["http://internal:8001", "http://internal:8001/api/memory"],
    ["   ", "http://public:9999/api/memory"],
  ])("resolves the gateway upstream from %p", async (internal, expected) => {
    rs.stubEnv("DEER_FLOW_INTERNAL_GATEWAY_BASE_URL", internal);
    rs.stubEnv("NEXT_PUBLIC_BACKEND_BASE_URL", "http://public:9999");
    // The route resolves its upstream at module load, so import it after the
    // environment is in place.
    rs.resetModules();
    const { DELETE } = await import("@/app/api/memory/route");
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));

    await DELETE(
      new NextRequest("http://deer-flow.test/api/memory", { method: "DELETE" }),
    );

    const [target] = fetchMock.mock.calls[0]!;
    expect(target).toBeInstanceOf(URL);
    expect((target as URL).href).toBe(expected);
  });
});
