import type { Translations } from "@/core/i18n/locales/types";

import { localizeDocumentation } from "./documentation";
import type { LoadedContribution } from "./registry";

// Discovery metadata only: catalog entries never enter the runtime module loader.
export const extensionCatalog = [
  {
    key: "agentTeams",
    icon: "users",
    package: "deerflow-extension-agent-teams",
    namespace: "community.agent-teams",
  },
  {
    key: "bookmarks",
    package: "deerflow-extension-bookmarks",
    namespace: "community.bookmarks",
    icon: "bookmark",
  },
  {
    key: "context",
    package: "deerflow-extension-jev-context",
    namespace: "community.jev-context",
  },
  {
    key: "classify",
    package: "deerflow-extension-jev-classify",
    namespace: "community.jev-classify",
  },
  {
    key: "screening",
    package: "deerflow-extension-jev-screening",
    namespace: null,
  },
  {
    key: "workflows",
    package: "deerflow-extension-workflows",
    namespace: "community.workflows",
  },
  {
    key: "reportSections",
    package: "deerflow-extension-report-sections",
    namespace: "community.report-sections",
  },
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
  {
    key: "knowledgeManagement",
    package: "deerflow-extension-knowledge-management",
    namespace: "knowledge-management",
  },
  {
    key: "knowledgePlatform",
    package: "deerflow-extension-knowledge-platform",
    namespace: "knowledge-platform",
  },
  {
    key: "knowledgeCenter",
    package: "deerflow-extension-knowledge-center",
    namespace: "knowledge-center",
  },
  { key: "lightrag", package: "deerflow-extension-lightrag", namespace: null },
  { key: "weknora", package: "deerflow-extension-weknora", namespace: null },
  { key: "example", package: "deerflow-extension-example", namespace: null },
] as const;

export interface ExtensionCatalogEntry {
  id: string;
  title: string;
  description: string;
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
  const entries: ExtensionCatalogEntry[] = extensionCatalog.map((item) => ({
    id: item.namespace ?? `catalog/${item.key}`,
    ...copy[item.key],
    package: item.package,
    guide: `https://github.com/bytedance/deer-flow/tree/main/examples/${item.package}#readme`,
    icon: "icon" in item ? item.icon : undefined,
    loaded: loaded.find((entry) => entry.namespace === item.namespace),
  }));
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
          guide: page.docs_url ?? existing.guide,
        });
      continue;
    }
    if (known.has(entry.namespace)) continue;
    entries.push({
      id: entry.namespace,
      title: entry.title,
      description: entry.description,
      ...(page ? localizeDocumentation(page, locale) : {}),
      guide: page?.docs_url,
      loaded: entry,
    });
  }
  return entries;
}
