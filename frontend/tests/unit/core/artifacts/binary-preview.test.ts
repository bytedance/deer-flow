import { afterEach, expect, rs, test } from "@rstest/core";

import {
  MAX_BINARY_PREVIEW_BYTES,
  readPreviewFile,
} from "@/core/artifacts/binary-preview";

rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/static-response", () => ({ staticApiResponse: rs.fn() }));
afterEach(() => {
  rs.restoreAllMocks();
});

test("reads authenticated bytes without a Content-Length", async () => {
  const request = rs
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(new Uint8Array([1, 2, 3])));
  const signal = new AbortController().signal;
  const result = await readPreviewFile("/protected-file", signal);
  expect(new Uint8Array(result.bytes)).toEqual(new Uint8Array([1, 2, 3]));
  expect(result.etag).toBeNull();
  expect(request).toHaveBeenCalledWith(
    "/protected-file",
    expect.objectContaining({
      credentials: "include",
      signal,
      cache: "no-store",
    }),
  );
});

test("preserves the Gateway ETag alongside bounded bytes", async () => {
  rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(new Uint8Array([4, 5]), {
      headers: { ETag: '"gateway-version"' },
    }),
  );
  const result = await readPreviewFile("/file", new AbortController().signal);
  expect(result.etag).toBe('"gateway-version"');
  expect(new Uint8Array(result.bytes)).toEqual(new Uint8Array([4, 5]));
});

test("rejects authorization errors without consuming their body", async () => {
  const response = new Response("private", { status: 403 });
  rs.spyOn(globalThis, "fetch").mockResolvedValue(response);
  await expect(
    readPreviewFile("/file", new AbortController().signal),
  ).rejects.toThrow("403");
  expect(response.bodyUsed).toBe(false);
});

test("cancels a declared oversized response before reading it", async () => {
  const cancel = rs.fn();
  const body = new ReadableStream({ cancel });
  rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(body, {
      headers: { "content-length": String(MAX_BINARY_PREVIEW_BYTES + 1) },
    }),
  );
  await expect(
    readPreviewFile("/file", new AbortController().signal),
  ).rejects.toThrow("too large");
  expect(cancel).toHaveBeenCalled();
});

for (const declared of [undefined, "1"]) {
  test(`enforces the streamed limit with declared size ${declared ?? "absent"}`, async () => {
    const cancel = rs.fn();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_BINARY_PREVIEW_BYTES));
        controller.enqueue(new Uint8Array(1));
      },
      cancel,
    });
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        headers: declared ? { "content-length": declared } : {},
      }),
    );
    await expect(
      readPreviewFile("/file", new AbortController().signal),
    ).rejects.toThrow("too large");
    expect(cancel).toHaveBeenCalled();
    expect(body.locked).toBe(false);
  });
}

test("an obsolete preview does not fetch", async () => {
  const request = rs.spyOn(globalThis, "fetch");
  const controller = new AbortController();
  controller.abort();
  await expect(readPreviewFile("/file", controller.signal)).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
});
