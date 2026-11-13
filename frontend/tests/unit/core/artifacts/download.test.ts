import { afterEach, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: (url: string, init: RequestInit) => globalThis.fetch(url, init),
}));
import {
  MAX_BUFFERED_DOWNLOAD_BYTES,
  prepareArtifactDownload,
} from "@/core/artifacts/download";

afterEach(() => {
  rs.unstubAllGlobals();
});

it("authenticates a bounded download, preserves MIME and rejects failed responses", async () => {
  const fetch = rs
    .fn()
    .mockResolvedValueOnce(
      new Response("report", { headers: { "content-type": "text/plain" } }),
    )
    .mockResolvedValueOnce(new Response("error", { status: 403 }));
  rs.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  const blob = await prepareArtifactDownload("/report", signal);
  expect(await blob!.text()).toBe("report");
  expect(blob!.type).toBe("text/plain");
  expect(fetch).toHaveBeenCalledWith("/report", { signal, cache: "no-store" });
  await expect(prepareArtifactDownload("/denied", signal)).rejects.toThrow(
    "403",
  );
});

it("cancels oversized bodies with and without Content-Length for browser disk handoff", async () => {
  for (const declared of [true, false]) {
    const cancel = rs.fn();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_BUFFERED_DOWNLOAD_BYTES + 1));
      },
      cancel,
    });
    rs.stubGlobal(
      "fetch",
      rs.fn().mockResolvedValue(
        new Response(body, {
          headers: declared
            ? { "content-length": String(MAX_BUFFERED_DOWNLOAD_BYTES + 1) }
            : {},
        }),
      ),
    );
    expect(
      await prepareArtifactDownload("/large", new AbortController().signal),
    ).toBeNull();
    expect(cancel).toHaveBeenCalledTimes(1);
  }
});

it("aborted reads never return a download blob", async () => {
  const controller = new AbortController();
  controller.abort();
  rs.stubGlobal("fetch", rs.fn().mockResolvedValue(new Response("data")));
  await expect(
    prepareArtifactDownload("/report", controller.signal),
  ).rejects.toThrow();
});
