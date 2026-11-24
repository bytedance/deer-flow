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

test("workflow metadata is localized and merges its registration", () => {
  const workflow: LoadedContribution = {
    ...contribution,
    namespace: "community.workflows",
    title: "Deployment workflow title",
    settings: { enabled: true },
  };
  for (const [copy, title, limitations] of [
    [
      enUS.extensions.catalog,
      "Script workflows",
      "review retained output versions",
    ],
    [zhCN.extensions.catalog, "脚本工作流", "按保留版本确认成果"],
  ] as const) {
    const catalogOnly = extensionDirectory([], copy).find(
      (entry) => entry.package === "deerflow-extension-workflows",
    );
    expect(catalogOnly).toMatchObject({
      id: workflow.namespace,
      title,
      guide:
        "https://github.com/bytedance/deer-flow/tree/main/examples/deerflow-extension-workflows#readme",
    });
    expect(catalogOnly?.description).toContain(limitations);
    expect(catalogOnly?.loaded).toBeUndefined();
    const matches = extensionDirectory([workflow], copy).filter(
      (entry) => entry.id === workflow.namespace,
    );
    expect(matches).toHaveLength(1);
    expect(matches[0]?.title).toBe(title);
    expect(matches[0]?.loaded).toBe(workflow);
  }
});

test("WeKnora discovery is localized without implying runtime activation", () => {
  for (const [copy, title] of [
    [enUS.extensions.catalog, "WeKnora knowledge retrieval"],
    [zhCN.extensions.catalog, "WeKnora 知识检索"],
  ] as const) {
    const entry = extensionDirectory([], copy).find(
      (item) => item.package === "deerflow-extension-weknora",
    );
    expect(entry).toMatchObject({
      id: "catalog/weknora",
      title,
      guide:
        "https://github.com/bytedance/deer-flow/tree/main/examples/deerflow-extension-weknora#readme",
    });
    expect(entry?.description).toBeTruthy();
    expect(entry?.loaded).toBeUndefined();
  }
});

test("LightRAG discovery is localized without claiming a runtime registration", () => {
  for (const copy of [enUS.extensions.catalog, zhCN.extensions.catalog]) {
    const entry = extensionDirectory([], copy).find(
      (item) => item.package === "deerflow-extension-lightrag",
    );
    expect(entry?.title).toBe("LightRAG");
    expect(entry?.description).toBe(copy.lightrag.description);
    expect(entry?.loaded).toBeUndefined();
  }
});

test("knowledge management discovery merges its namespace without implying activation", () => {
  const management = { ...contribution, namespace: "knowledge-management" };
  for (const [copy, title] of [
    [enUS.extensions.catalog, "Knowledge ingestion and processing"],
    [zhCN.extensions.catalog, "知识入库与处理"],
  ] as const) {
    const entry = extensionDirectory([], copy).find(
      (item) => item.package === "deerflow-extension-knowledge-management",
    );
    expect(entry?.id).toBe(management.namespace);
    expect(entry?.title).toBe(title);
    expect(entry?.loaded).toBeUndefined();
    const matches = extensionDirectory([management], copy).filter(
      (item) => item.id === management.namespace,
    );
    expect(matches).toHaveLength(1);
    expect(matches[0]?.loaded).toBe(management);
  }
});

test("knowledge platform discovery is localized and does not imply a management page", () => {
  for (const [copy, title] of [
    [enUS.extensions.catalog, "Knowledge spaces and connections"],
    [zhCN.extensions.catalog, "知识空间与连接"],
  ] as const) {
    const entry = extensionDirectory([], copy).find(
      (item) => item.package === "deerflow-extension-knowledge-platform",
    );
    expect(entry?.id).toBe("knowledge-platform");
    expect(entry?.title).toBe(title);
    expect(entry?.description).toBe(copy.knowledgePlatform.description);
    expect(entry?.guide).toBe(
      "https://github.com/bytedance/deer-flow/tree/main/examples/deerflow-extension-knowledge-platform#readme",
    );
    expect(entry?.loaded).toBeUndefined();
  }
});

test("installed documentation clears bundled requirements while retaining the README fallback", () => {
  for (const requirements of [undefined, []]) {
    const loaded = {
      ...contribution,
      documentation: {
        schema_version: 1 as const,
        id: contribution.namespace,
        locales: {
          en: {
            title: "Installed",
            description: "Current package",
            usage: [{ title: "Start", description: "Use the package" }],
            ...(requirements ? { requirements } : {}),
          },
        },
      },
    };
    const entry = extensionDirectory([loaded], enUS.extensions.catalog).find(
      (item) => item.id === loaded.namespace,
    )!;
    expect(entry.title).toBe("Installed");
    expect(entry.requirements ?? []).toEqual([]);
    expect(entry.guide).toContain("deerflow-extension-bookmarks#readme");
  }
});

test("documentation matches language tags by case-insensitive exact match then language", () => {
  const page = {
    ...contribution,
    documentation: {
      schema_version: 1 as const,
      id: contribution.namespace,
      locales: {
        "en-us": {
          title: "English",
          description: "English",
          usage: [{ title: "Start", description: "Start" }],
        },
        zh: {
          title: "中文",
          description: "中文",
          usage: [{ title: "开始", description: "开始" }],
        },
        "zh-cn": {
          title: "简体",
          description: "简体",
          usage: [{ title: "开始", description: "开始" }],
        },
      },
    },
  };
  for (const [locale, title] of [
    ["en-US", "English"],
    ["zh-CN", "简体"],
    ["zh-TW", "中文"],
    ["fr-FR", "English"],
  ]) {
    expect(
      extensionDirectory([page], enUS.extensions.catalog, locale).find(
        (item) => item.id === page.namespace,
      )?.title,
    ).toBe(title);
  }
});
