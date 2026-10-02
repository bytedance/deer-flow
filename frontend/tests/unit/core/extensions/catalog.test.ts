import { readdirSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@rstest/core";

import {
  extensionCatalog,
  extensionDirectory,
} from "@/core/extensions/catalog";
import type { LoadedContribution } from "@/core/extensions/registry";
import { enUS } from "@/core/i18n/locales/en-US";

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
