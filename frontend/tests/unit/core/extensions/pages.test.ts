import { afterEach, describe, expect, rs, test } from "@rstest/core";

import type {
  FrontendExtension,
  PluginSurface,
} from "@/core/extensions/contracts";
import {
  pluginPages,
  pluginPageTitle,
  pluginPagePath,
} from "@/core/extensions/pages";
import {
  loadFrontendExtensions,
  type LoadedContribution,
} from "@/core/extensions/registry";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/api/fetcher", () => ({
  fetch: async () => new Response("export default {}"),
}));
afterEach(() => {
  rs.restoreAllMocks();
});

const library: PluginSurface = {
  id: "library",
  title: "Library",
  slot: "page",
  navigation: { label: "My bookmarks", labelZh: "我的书签" },
  mount: () => ({ dispose: () => undefined }),
};
const entry: LoadedContribution = {
  namespace: "community.bookmarks",
  module: "bookmarks.v1",
  entry: `/api/plugins/modules/bookmarks.v1/${"a".repeat(64)}.mjs`,
  title: "Bookmarks",
  description: "",
  settings: { enabled: true },
  extension: { apiVersion: 1, module: "bookmarks.v1", surfaces: [library] },
};

describe("plugin-owned pages", () => {
  test("only loaded enabled page surfaces become namespaced routes", () => {
    const entries = [
      entry,
      { ...entry, namespace: "disabled", settings: { enabled: false } },
      { ...entry, namespace: "unloaded", extension: undefined },
      {
        ...entry,
        namespace: "another.plugin",
        extension: {
          ...entry.extension!,
          surfaces: [library],
        },
      },
    ];
    const pages = pluginPages(entries);
    expect(pages.map(({ href }) => href)).toEqual([
      "/workspace/extensions/community.bookmarks/library",
      "/workspace/extensions/another.plugin/library",
    ]);
    expect(pluginPageTitle(library, "zh-CN")).toBe("我的书签");
    expect(pluginPageTitle(library, "en-US")).toBe("My bookmarks");
    expect(pluginPagePath("a/b?c", "page#one")).toBe(
      "/workspace/extensions/a%2Fb%3Fc/page%23one",
    );
  });

  test("page URLs do not require a sidebar entry", () => {
    const pages = pluginPages([
      {
        ...entry,
        extension: {
          ...entry.extension!,
          surfaces: [{ ...library, navigation: undefined }],
        },
      },
    ]);
    expect(pages).toHaveLength(1);
    expect(pluginPageTitle(pages[0]!.surface, "zh-CN")).toBe("Library");
  });

  test("invalid navigation is contained to its module", async () => {
    for (const surface of [
      { ...library, slot: "composer" },
      { ...library, navigation: { label: "" } },
      { ...library, navigation: { label: "ok", labelZh: 42 } },
      { ...library, id: "../chats" },
    ]) {
      const importer = rs.fn(async () => ({
        default: {
          ...entry.extension,
          surfaces: [surface],
        } as FrontendExtension,
      }));
      const result = await loadFrontendExtensions([entry], importer);
      expect(importer).toHaveBeenCalledTimes(1);
      expect(result[0]?.error).toBeTruthy();
      expect(pluginPages(result)).toEqual([]);
    }
  });
});
