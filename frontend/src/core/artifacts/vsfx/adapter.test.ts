import { describe, expect, test, vi } from "vitest";

import {
  createVsfxArtifactBundleRequest,
  type VsfxArtifactBundle,
} from "./adapter";

function createJsonResponse(payload: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200,
    ...init,
  });
}

function createBundleRequest(options?: {
  artifacts?: string[];
  fetchImpl?: typeof fetch;
  filepath?: string;
  isMock?: boolean;
  threadId?: string;
}) {
  return createVsfxArtifactBundleRequest(
    options?.threadId ?? "thread-123",
    options?.filepath ?? "/artifacts/widget.vsfx",
    options?.artifacts ?? [
      "/artifacts/widget.vsfx",
      "/artifacts/widget.cda.json",
      "/artifacts/widget.Properties.json",
    ],
    options?.isMock ?? false,
    options?.fetchImpl,
  );
}

function expectHealthyPrimary(result: VsfxArtifactBundle) {
  expect(result.primaryUrl).toContain("/api/threads/thread-123/artifacts/artifacts/widget.vsfx");
  expect(result.errors.primary).toBeNull();
}

describe("createVsfxArtifactBundleRequest", () => {
  test("returns deterministic bundle data for a healthy artifact family", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);

      if (url.endsWith("/artifacts/widget.cda.json")) {
        return createJsonResponse({ nodes: [{ id: "root" }] });
      }

      if (url.endsWith("/artifacts/widget.Properties.json")) {
        return createJsonResponse({ parts: [{ handle: 7, name: "Bolt" }] });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const request = createBundleRequest({ fetchImpl });

    expect(request.initial).toMatchObject({
      cdaTree: null,
      properties: null,
      loading: true,
      errors: {
        primary: null,
        cdaTree: null,
        properties: null,
      },
    });
    expect(request.initial.primaryUrl).toContain(
      "/api/threads/thread-123/artifacts/artifacts/widget.vsfx",
    );

    const result = await request.promise;

    expectHealthyPrimary(result);
    expect(result).toEqual({
      primaryUrl: expect.stringContaining(
        "/api/threads/thread-123/artifacts/artifacts/widget.vsfx",
      ),
      cdaTree: { nodes: [{ id: "root" }] },
      properties: { parts: [{ handle: 7, name: "Bolt" }] },
      loading: false,
      errors: {
        primary: null,
        cdaTree: null,
        properties: null,
      },
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  test("degrades missing sibling metadata independently", async () => {
    const request = createBundleRequest({
      artifacts: ["/artifacts/widget.vsfx"],
      fetchImpl: vi.fn<typeof fetch>(),
    });

    const result = await request.promise;

    expectHealthyPrimary(result);
    expect(result.cdaTree).toBeNull();
    expect(result.properties).toBeNull();
    expect(result.errors.cdaTree).toMatchObject({
      code: "missing",
      filepath: "/artifacts/widget.cda.json",
    });
    expect(result.errors.properties).toMatchObject({
      code: "missing",
      filepath: "/artifacts/widget.Properties.json",
    });
  });

  test("keeps malformed sibling data local to the affected panel", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);

      if (url.endsWith("/artifacts/widget.cda.json")) {
        return new Response("{bad json", { status: 200 });
      }

      if (url.endsWith("/artifacts/widget.Properties.json")) {
        return createJsonResponse({ parts: [{ handle: 99 }] });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const result = await createBundleRequest({ fetchImpl }).promise;

    expectHealthyPrimary(result);
    expect(result.cdaTree).toBeNull();
    expect(result.properties).toEqual({ parts: [{ handle: 99 }] });
    expect(result.errors.cdaTree).toMatchObject({
      code: "invalid-json",
      filepath: "/artifacts/widget.cda.json",
    });
    expect(result.errors.properties).toBeNull();
  });

  test("keeps sibling fetch failures local to the affected panel", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);

      if (url.endsWith("/artifacts/widget.cda.json")) {
        throw new Error("network down");
      }

      if (url.endsWith("/artifacts/widget.Properties.json")) {
        return createJsonResponse({ parts: [{ handle: 123 }] });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const result = await createBundleRequest({ fetchImpl }).promise;

    expectHealthyPrimary(result);
    expect(result.cdaTree).toBeNull();
    expect(result.properties).toEqual({ parts: [{ handle: 123 }] });
    expect(result.errors.cdaTree).toMatchObject({
      code: "load-failed",
      filepath: "/artifacts/widget.cda.json",
    });
    expect(result.errors.properties).toBeNull();
  });
});
