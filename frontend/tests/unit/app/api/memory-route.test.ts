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

  /**
   * Upstream the root memory proxy targets for one DELETE request. The route
   * resolves the Gateway base URL at module load, so the env is stubbed first
   * and the module is imported fresh.
   */
  async function memoryTarget(env: Record<string, string | undefined>) {
    for (const [key, value] of Object.entries(env)) {
      rs.stubEnv(key, value);
    }
    rs.resetModules();
    const { DELETE } = await import("@/app/api/memory/route");

    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const request = new NextRequest("http://deer-flow.test/api/memory", {
      method: "DELETE",
    });

    await DELETE(request);

    const [target] = fetchMock.mock.calls[0]!;
    if (!(target instanceof URL)) {
      throw new Error("Memory proxy target must be a URL");
    }
    return target;
  }

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

  it("prefers the server-only internal gateway over the public base URL", async () => {
    const target = await memoryTarget({
      DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://gateway.internal:8001",
      NEXT_PUBLIC_BACKEND_BASE_URL: "http://public.example.com:9999",
    });

    expect(target.href).toBe("http://gateway.internal:8001/api/memory");
  });

  it("falls back to the public base URL when the internal gateway is unset", async () => {
    const target = await memoryTarget({
      DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: undefined,
      NEXT_PUBLIC_BACKEND_BASE_URL: "http://public.example.com:9999",
    });

    expect(target.href).toBe("http://public.example.com:9999/api/memory");
  });
});
