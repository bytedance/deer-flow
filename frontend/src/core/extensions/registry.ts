import {
  BellIcon,
  BookmarkIcon,
  DownloadIcon,
  FileJsonIcon,
  FileTextIcon,
  PuzzleIcon,
  type LucideIcon,
} from "lucide-react";

import type { FrontendContribution, FrontendExtension } from "./contracts";

export function extensionIcon(name?: string): LucideIcon {
  return (
    (
      {
        bell: BellIcon,
        bookmark: BookmarkIcon,
        download: DownloadIcon,
        "file-json": FileJsonIcon,
        "file-text": FileTextIcon,
      } as Record<string, LucideIcon>
    )[name ?? ""] ?? PuzzleIcon
  );
}
export type LoadedContribution = FrontendContribution & {
  extension?: FrontendExtension;
  error?: string;
};
export type ModuleImporter = (url: string) => Promise<{ default: unknown }>;
const importModule: ModuleImporter = (url) =>
  import(/* webpackIgnore: true */ url) as Promise<{ default: unknown }>;

export async function loadFrontendExtensions(
  entries: FrontendContribution[],
  importer: ModuleImporter = importModule,
): Promise<LoadedContribution[]> {
  return Promise.all(
    entries.map(async (entry) => {
      if (entry.settings.enabled !== true || entry.module === null)
        return entry;
      try {
        // Code may only come from the authenticated same-origin Gateway asset route.
        const expected = `/api/plugins/modules/${entry.module}/`;
        if (
          !entry.entry?.startsWith(expected) ||
          !/^[a-f0-9]{64}\.mjs$/.test(entry.entry.slice(expected.length))
        )
          throw new Error("Invalid installed module entry");
        const loadedModule = (await importer(entry.entry))
          .default as FrontendExtension;
        if (
          loadedModule?.apiVersion !== 1 ||
          loadedModule.module !== entry.module ||
          (loadedModule.conversationActions !== undefined &&
            typeof loadedModule.conversationActions !== "function")
        )
          throw new Error("Incompatible browser extension");
        if (loadedModule.surfaces !== undefined) {
          const seen = new Set<string>();
          if (
            !Array.isArray(loadedModule.surfaces) ||
            loadedModule.surfaces.length > 16
          )
            throw new Error("Invalid plugin surfaces");
          for (const surface of loadedModule.surfaces) {
            if (
              !surface ||
              !/^[a-z][a-z0-9-]{0,63}$/.test(surface.id) ||
              seen.has(surface.id) ||
              surface.slot !== "page" ||
              typeof surface.title !== "string" ||
              !surface.title.trim() ||
              typeof surface.mount !== "function"
            )
              throw new Error("Invalid plugin surface");
            if (surface.navigation !== undefined) {
              const nav = surface.navigation;
              if (
                surface.slot !== "page" ||
                !nav ||
                typeof nav.label !== "string" ||
                !nav.label.trim() ||
                nav.label.length > 120 ||
                (nav.labelZh !== undefined &&
                  (typeof nav.labelZh !== "string" ||
                    !nav.labelZh.trim() ||
                    nav.labelZh.length > 120)) ||
                (nav.icon !== undefined && typeof nav.icon !== "string")
              )
                throw new Error("Invalid plugin navigation");
            }
            seen.add(surface.id);
          }
        }
        return { ...entry, extension: loadedModule };
      } catch (error) {
        console.warn(`Browser extension ${entry.module} unavailable`, error);
        return {
          ...entry,
          extension: undefined,
          error: "Module failed to load. Reload the page to retry.",
        };
      }
    }),
  );
}
export function activeFrontendExtensions(entries: LoadedContribution[]) {
  return entries.flatMap((contribution) =>
    contribution.settings.enabled === true && contribution.extension
      ? [{ contribution, extension: contribution.extension }]
      : [],
  );
}
