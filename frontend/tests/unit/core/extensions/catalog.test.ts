import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@rstest/core";

import {
  extensionCatalog,
  extensionDirectory,
} from "@/core/extensions/catalog";
import type { LoadedContribution } from "@/core/extensions/registry";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const contribution: LoadedContribution = {
  namespace: "community.bookmarks",
  module: null,
  entry: null,
  title: "Deployment bookmarks",
  description: "Configured bookmarks",
  settings: { enabled: false },
};

test("catalog covers every bundled extension package even without runtime registrations", () => {
  const packages = readdirSync(resolve(process.cwd(), "../examples")).filter(
    (name) => name.startsWith("deerflow-extension-"),
  );
  expect(extensionCatalog.map((entry) => entry.package).sort()).toEqual(
    packages.sort(),
  );
  const entries = extensionDirectory([], enUS.extensions.catalog);
  expect(entries).toHaveLength(packages.length);
  expect(entries.every((entry) => entry.loaded === undefined)).toBe(true);
});

test("catalog merge namespaces match the corresponding bundled plugin declarations", () => {
  for (const entry of extensionCatalog) {
    const directory = resolve(process.cwd(), "../examples", entry.package);
    const namespaces = readdirSync(directory, { recursive: true })
      .filter((path) => typeof path === "string" && path.endsWith(".py"))
      .flatMap((path) =>
        [
          ...readFileSync(resolve(directory, String(path)), "utf8").matchAll(
            /\b(?:namespace|NAMESPACE)\s*=\s*["']([^"']+)["']/g,
          ),
        ].map((match) => match[1]),
      );
    expect(namespaces, entry.package).toEqual(
      entry.namespace === null ? [] : [entry.namespace],
    );
  }
});

test("team catalog metadata stays localized and merges only its runtime registration", () => {
  const team: LoadedContribution = {
    ...contribution,
    namespace: "community.agent-teams",
    title: "Deployment team title",
    settings: { enabled: true },
  };
  for (const [copy, title] of [
    [enUS.extensions.catalog, "Agent teams"],
    [zhCN.extensions.catalog, "Agent 团队"],
  ] as const) {
    const catalogOnly = extensionDirectory([], copy).find(
      (entry) => entry.package === "deerflow-extension-agent-teams",
    );
    expect(catalogOnly).toMatchObject({
      id: team.namespace,
      title,
      guide:
        "https://github.com/bytedance/deer-flow/tree/main/examples/deerflow-extension-agent-teams#readme",
    });
    expect(catalogOnly?.description).toBeTruthy();
    expect(catalogOnly?.loaded).toBeUndefined();
    const matches = extensionDirectory([team], copy).filter(
      (entry) => entry.id === team.namespace,
    );
    expect(matches).toHaveLength(1);
    expect(matches[0]?.title).toBe(title);
    expect(matches[0]?.loaded).toBe(team);
  }
});

test("merges by namespace without duplicating catalog entries or guessing backend-only status", () => {
  const entries = extensionDirectory([contribution], enUS.extensions.catalog);
  expect(entries).toHaveLength(extensionCatalog.length);
  expect(
    entries.find((entry) => entry.id === contribution.namespace)?.loaded
      ?.settings.enabled,
  ).toBe(false);
  expect(
    entries.find(
      (entry) => entry.package === "deerflow-extension-jev-screening",
    )?.loaded,
  ).toBeUndefined();
});

test("preserves custom deployment extensions and module failures", () => {
  const failed = {
    ...contribution,
    namespace: "company.custom",
    error: "module failed",
  };
  const entries = extensionDirectory([failed], enUS.extensions.catalog);
  expect(entries).toHaveLength(extensionCatalog.length + 1);
  expect(entries.find((entry) => entry.id === failed.namespace)?.loaded).toBe(
    failed,
  );
  expect(entries.find((entry) => entry.id === failed.namespace)?.title).toBe(
    failed.title,
  );
});
