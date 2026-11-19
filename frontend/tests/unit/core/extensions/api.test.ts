import { afterEach, expect, rs, test } from "@rstest/core";

import { fetchFrontendExtensions } from "@/core/extensions/api";
import type { FrontendContribution } from "@/core/extensions/contracts";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/static-response", () => ({ staticApiResponse: rs.fn() }));

const entry = {
  namespace: "community.bookmarks",
  module: "bookmarks.v1",
  entry: `/api/plugins/modules/bookmarks.v1/${"a".repeat(64)}.mjs`,
  title: "Bookmarks",
  description: "",
};

const documentation = {
  schema_version: 1,
  id: "company.helper",
  locales: {
    "en-US": {
      title: "Helper",
      description: "Package instructions",
      usage: [{ title: "Start", description: "Open the helper" }],
    },
  },
};

afterEach(() => {
  rs.restoreAllMocks();
});

for (const docs_url of [
  "https://example.org:bad/docs",
  "https://example.org:65536/docs",
  "https://[",
  "http://example.org/docs",
  "https://user:password@example.org/docs",
]) {
  test(`invalid optional documentation URL is isolated: ${docs_url}`, async () => {
    const healthy = { ...entry, settings: { enabled: true } };
    const helper = {
      ...healthy,
      namespace: documentation.id,
      documentation: { ...documentation, docs_url },
    };
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([healthy, helper])),
    );

    const discovered = await fetchFrontendExtensions();
    expect(discovered).toHaveLength(2);
    expect(discovered[0]).toEqual(healthy);
    expect(discovered[1]?.namespace).toBe(documentation.id);
    expect(discovered[1]?.documentation).toBeUndefined();
  });
}

test("valid HTTPS documentation with an explicit port is retained", async () => {
  const helper = {
    ...entry,
    settings: {},
    namespace: documentation.id,
    documentation: {
      ...documentation,
      docs_url: "https://example.org:8443/docs",
    },
  };
  rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([helper])),
  );
  expect((await fetchFrontendExtensions())[0]?.documentation).toEqual(
    helper.documentation,
  );
});

for (const [label, settings] of [
  ["empty", {}],
  [
    "mixed primitive",
    {
      enabled: true,
      disabled: false,
      limit: 3,
      zero: 0,
      label: "Bookmarks",
      empty: "",
    },
  ],
] as const) {
  test(`discovery preserves ${label} settings for the extension loader`, async () => {
    const request = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify([{ ...entry, settings }])),
      );

    // pnpm typecheck verifies the discovery schema's inferred public contract.
    const discovered: FrontendContribution[] = await fetchFrontendExtensions();

    expect(discovered).toEqual([{ ...entry, settings }]);
    expect(request).toHaveBeenCalledWith(
      "/api/plugins",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });
}

for (const [label, settings] of [
  ["null value", { enabled: null }],
  ["nested object", { options: { enabled: true } }],
  ["array value", { options: ["bookmarks"] }],
  ["null record", null],
  ["array record", []],
  ["string record", "enabled"],
  ["missing record", undefined],
] as const) {
  test(`discovery rejects settings with a ${label}`, async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ ...entry, settings }])),
    );

    await expect(fetchFrontendExtensions()).rejects.toMatchObject({
      name: "ZodError",
    });
  });
}
