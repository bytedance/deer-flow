import type { Translations } from "@/core/i18n/locales/types";

import {
  bundledMetadata,
  localizeDocumentation,
  type ExtensionCategory,
} from "./documentation";
import type { LoadedContribution } from "./registry";

// Discovery metadata only: catalog entries never enter the runtime module loader.
// Ordered by scenario so each directory section lists user-facing entries first.
export const extensionCatalog = [
  {
    key: "agentTeams",
    package: "deerflow-extension-agent-teams",
    namespace: "community.agent-teams",
  },
  {
    key: "workflows",
    package: "deerflow-extension-workflows",
    namespace: "community.workflows",
  },
  {
    key: "knowledgeCenter",
    package: "deerflow-extension-knowledge-center",
    namespace: "knowledge-center",
  },
  { key: "weknora", package: "deerflow-extension-weknora", namespace: null },
  { key: "lightrag", package: "deerflow-extension-lightrag", namespace: null },
  {
    key: "knowledgePlatform",
    package: "deerflow-extension-knowledge-platform",
    namespace: "knowledge-platform",
  },
  {
    key: "knowledgeManagement",
    package: "deerflow-extension-knowledge-management",
    namespace: "knowledge-management",
  },
  {
    key: "officePreview",
    package: "deerflow-extension-office-preview",
    namespace: "office-preview",
  },
  {
    key: "workspaceSearch",
    package: "deerflow-extension-workspace-search",
    namespace: null,
  },
  {
    key: "bookmarks",
    package: "deerflow-extension-bookmarks",
    namespace: "community.bookmarks",
  },
  {
    key: "reportSections",
    package: "deerflow-extension-report-sections",
    namespace: "community.report-sections",
  },
  {
    key: "classify",
    package: "deerflow-extension-jev-classify",
    namespace: "community.jev-classify",
  },
  {
    key: "runPostmortem",
    package: "deerflow-extension-run-postmortem",
    namespace: "community.run-postmortem",
  },
  {
    key: "context",
    package: "deerflow-extension-jev-context",
    namespace: "community.jev-context",
  },
  {
    key: "screening",
    package: "deerflow-extension-jev-screening",
    namespace: null,
  },
  {
    key: "skillEvolution",
    package: "deerflow-extension-skill-evolution",
    namespace: null,
  },
  { key: "example", package: "deerflow-extension-example", namespace: null },
  {
    key: "retrieval",
    package: "deerflow-extension-retrieval",
    namespace: "example.retrieval",
  },
  {
    key: "knowledge",
    package: "deerflow-extension-knowledge",
    namespace: null,
  },
] as const;

export interface ExtensionCatalogEntry {
  id: string;
  title: string;
  description: string;
  category: ExtensionCategory;
  package?: string;
  guide?: string;
  icon?: string;
  loaded?: LoadedContribution;
  gettingStarted?: { title: string; description: string }[];
  requirements?: string[];
}

export function extensionDirectory(
  loaded: LoadedContribution[],
  copy: Translations["extensions"]["catalog"],
  locale = "en-US",
): ExtensionCatalogEntry[] {
  const entries: ExtensionCatalogEntry[] = extensionCatalog.map((item) => {
    const meta = bundledMetadata(item.package);
    return {
      id: item.namespace ?? `catalog/${item.key}`,
      ...copy[item.key],
      category: meta.category,
      package: item.package,
      guide: `https://github.com/bytedance/deer-flow/tree/main/examples/${item.package}#readme`,
      icon: meta.icon,
      loaded: loaded.find((entry) => entry.namespace === item.namespace),
    };
  });
  const known = new Set<string | null>(
    extensionCatalog.map((item) => item.namespace),
  );
  for (const entry of loaded) {
    const page =
      entry.documentation?.id === entry.namespace
        ? entry.documentation
        : undefined;
    const existing = entries.find((item) => item.id === entry.namespace);
    if (existing) {
      existing.loaded = entry;
      if (page)
        Object.assign(existing, localizeDocumentation(page, locale), {
          category: page.category ?? existing.category,
          icon: page.icon ?? existing.icon,
          guide: page.docs_url ?? existing.guide,
        });
      continue;
    }
    if (known.has(entry.namespace)) continue;
    entries.push({
      id: entry.namespace,
      title: entry.title,
      description: entry.description,
      category: page?.category ?? "other",
      icon: page?.icon,
      ...(page ? localizeDocumentation(page, locale) : {}),
      guide: page?.docs_url,
      loaded: entry,
    });
  }
  return entries;
}
