import { readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";
import type { PageMapItem } from "nextra";

import {
  buildLocalizedDocsPageMap,
  DOCS_CONTENT_ROOTS,
} from "@/components/docs/docs-page-map";

describe("buildLocalizedDocsPageMap", () => {
  it.each(["en", "zh"])(
    "keeps the %s content roots in the docs page map",
    (lang) => {
      const contentRoots = readdirSync(
        join(process.cwd(), "src/content", lang),
        {
          withFileTypes: true,
        },
      )
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort();

      expect(contentRoots).toEqual([...DOCS_CONTENT_ROOTS].sort());
    },
  );

  it("localizes content routes and removes unrelated App Router pages", () => {
    const source: PageMapItem[] = [
      { name: "index", route: "/" },
      {
        name: "application",
        route: "/application",
        children: [{ name: "quick-start", route: "/application/quick-start" }],
      },
      {
        name: "posts",
        route: "/posts",
        children: [{ name: "weekly", route: "/posts/weekly/2026-04-06" }],
      },
      {
        name: "workspace",
        route: "/workspace",
        children: [
          { name: "chats", route: "/workspace/chats" },
          {
            name: "scheduled-tasks",
            route: "/workspace/scheduled-tasks",
          },
        ],
      },
      {
        name: "blog",
        route: "/blog",
        children: [{ name: "posts", route: "/blog/posts" }],
      },
      { name: "login", route: "/login" },
      { name: "callback", route: "/auth/callback" },
    ];

    expect(buildLocalizedDocsPageMap("/en/docs", source)).toEqual([
      { name: "index", route: "/en/docs/" },
      {
        name: "application",
        route: "/en/docs/application",
        children: [
          {
            name: "quick-start",
            route: "/en/docs/application/quick-start",
          },
        ],
      },
      {
        name: "posts",
        route: "/en/docs/posts",
        children: [
          {
            name: "weekly",
            route: "/en/docs/posts/weekly/2026-04-06",
          },
        ],
      },
    ]);
    expect(source[0]).toEqual({ name: "index", route: "/" });
  });

  it("preserves routes already localized to the requested docs base", () => {
    const source: PageMapItem[] = [
      { name: "harness", route: "/zh/docs/harness" },
      { name: "not-docs", route: "/zh/docs-extra" },
    ];

    expect(buildLocalizedDocsPageMap("/zh/docs", source)).toEqual([
      { name: "harness", route: "/zh/docs/harness" },
    ]);
  });
});
