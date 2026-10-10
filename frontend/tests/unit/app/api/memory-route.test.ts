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
});
