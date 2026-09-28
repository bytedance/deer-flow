import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";

import { fetchFrontendExtensions } from "@/core/extensions/api";
import { loadFrontendExtensions } from "@/core/extensions/registry";

const config = rs.hoisted(() => ({ backend: "" }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => config.backend }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/static-response", () => ({ staticApiResponse: rs.fn() }));

const entry = {
  namespace: "community.bookmarks",
  module: "bookmarks.v1",
  entry: `/api/plugins/modules/bookmarks.v1/${"a".repeat(64)}.mjs`,
  title: "Bookmarks",
  description: "",
  settings: { enabled: true },
};
const extension = { apiVersion: 1, module: entry.module };
const code = "export default {apiVersion: 1, module: 'bookmarks.v1'};";

beforeEach(() => {
  config.backend = "";
  rs.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  rs.restoreAllMocks();
});

for (const backend of [
  "",
  "https://backend.example",
  "https://backend.example/deerflow",
  "/gateway",
]) {
  test(`loads authenticated code with backend base ${backend || "same origin"}`, async () => {
    config.backend = backend;
    const request = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(code));
    const revoke = rs.spyOn(URL, "revokeObjectURL");
    const importer = rs.fn(async (url: string) => {
      expect(url.startsWith("blob:")).toBe(true);
      // Read the actual blob without using the spied HTTP fetch.
      const { resolveObjectURL } = await import("node:buffer");
      expect(await resolveObjectURL(url)?.text()).toBe(code);
      expect(revoke).not.toHaveBeenCalled();
      return { default: extension };
    });
    const result = await loadFrontendExtensions([entry], importer);
    expect(result[0]?.extension).toEqual(extension);
    expect(request).toHaveBeenCalledWith(
      `${backend}${entry.entry}`,
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
    expect(importer).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith(importer.mock.calls[0]![0]);
  });
}

test("rejected HTTP responses never execute as modules", async () => {
  const request = rs.spyOn(globalThis, "fetch");
  const create = rs.spyOn(URL, "createObjectURL");
  const importer = rs.fn();
  for (const status of [403, 404, 500]) {
    request.mockResolvedValue(new Response("not javascript", { status }));
    const result = await loadFrontendExtensions([entry], importer);
    expect(result[0]?.error).toBeTruthy();
    expect(result[0]?.extension).toBeUndefined();
  }
  expect(create).not.toHaveBeenCalled();
  expect(importer).not.toHaveBeenCalled();
});

test("failed import releases its blob and does not prevent another plugin loading", async () => {
  rs.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response(code),
  );
  const revoke = rs.spyOn(URL, "revokeObjectURL");
  const importer = rs
    .fn()
    .mockRejectedValueOnce(new Error("module failed"))
    .mockResolvedValueOnce({ default: extension });
  const result = await loadFrontendExtensions([entry, entry], importer);
  expect(result[0]?.error).toBeTruthy();
  expect(result[1]?.extension).toEqual(extension);
  expect(revoke).toHaveBeenCalledTimes(2);
  for (const [url] of importer.mock.calls)
    expect(revoke).toHaveBeenCalledWith(url);
});

test("disabled, backend-only and invalid entries never fetch or import", async () => {
  const request = rs.spyOn(globalThis, "fetch");
  const importer = rs.fn();
  await loadFrontendExtensions(
    [
      { ...entry, settings: { enabled: false } },
      { ...entry, module: null, entry: null },
      { ...entry, entry: "https://untrusted.example/code.mjs" },
      { ...entry, entry: `${entry.entry}?redirect=elsewhere` },
    ],
    importer,
  );
  expect(request).not.toHaveBeenCalled();
  expect(importer).not.toHaveBeenCalled();
});

for (const backend of ["", "https://backend.example/prefix", "/gateway"]) {
  test(`packaged entries preserve resource URLs with base ${backend}`, async () => {
    config.backend = backend;
    const assets = {
      ...entry,
      transport: "assets-v1" as const,
      entry: `/api/plugins/${entry.namespace}/assets/${"b".repeat(64)}/static/dist/index.mjs`,
    };
    const importer = rs.fn();
    const assetImporter = rs.fn(async () => ({ default: extension }));
    const result = await loadFrontendExtensions(
      [assets],
      importer,
      assetImporter,
    );
    expect(result[0]?.extension).toEqual(extension);
    expect(assetImporter).toHaveBeenCalledWith(backend + assets.entry);
    expect(importer).not.toHaveBeenCalled();
    assetImporter.mockClear();
    for (const path of [
      "../index.mjs",
      "%2e%2e/index.mjs",
      "index.mjs?x",
      "index.css",
    ]) {
      const invalid = {
        ...assets,
        entry: `/api/plugins/${entry.namespace}/assets/${"b".repeat(64)}/${path}`,
      };
      expect(
        (await loadFrontendExtensions([invalid], importer, assetImporter))[0]
          ?.error,
      ).toBeTruthy();
    }
    expect(assetImporter).not.toHaveBeenCalled();
  });
}

test("unknown transports and failing packaged plugins are isolated", async () => {
  const importer = rs.fn();
  const assetImporter = rs
    .fn()
    .mockRejectedValueOnce(new Error("missing chunk"))
    .mockResolvedValueOnce({ default: extension });
  const assets = {
    ...entry,
    transport: "assets-v1" as const,
    entry: `/api/plugins/${entry.namespace}/assets/${"b".repeat(64)}/index.mjs`,
  };
  const unknown = { ...entry, transport: "future-v9" as "assets-v1" };
  const result = await loadFrontendExtensions(
    [unknown, assets, assets],
    importer,
    assetImporter,
  );
  expect(result.map((item) => !!item.extension)).toEqual([false, false, true]);
  expect(importer).not.toHaveBeenCalled();
  expect(assetImporter).toHaveBeenCalledTimes(2);
});

test("discovery preserves transport negotiation through parsing and isolates newer transports", async () => {
  const assets = {
    ...entry,
    transport: "assets-v1",
    entry: `/api/plugins/${entry.namespace}/assets/${"b".repeat(64)}/index.mjs`,
  };
  rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify([assets, { ...assets, transport: "future-v9" }]),
    ),
  );
  const discovered = await fetchFrontendExtensions();
  expect(discovered.map((item) => item.transport)).toEqual([
    "assets-v1",
    "future-v9",
  ]);
  const assetImporter = rs.fn(async () => ({ default: extension }));
  const loaded = await loadFrontendExtensions(
    discovered,
    rs.fn(),
    assetImporter,
  );
  expect(loaded[0]?.extension).toEqual(extension);
  expect(loaded[1]?.error).toBeTruthy();
  expect(assetImporter).toHaveBeenCalledTimes(1);
});
