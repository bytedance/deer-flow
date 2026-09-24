import {
  BellIcon,
  BookmarkIcon,
  DownloadIcon,
  FileJsonIcon,
  FileTextIcon,
  PuzzleIcon,
  type LucideIcon,
} from "lucide-react";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { importAssetModule } from "./asset-module";
import type { FrontendContribution, FrontendExtension } from "./contracts";

export function extensionIcon(name?: string): LucideIcon {
  const icons: Record<string, LucideIcon> = {
    bell: BellIcon,
    bookmark: BookmarkIcon,
    download: DownloadIcon,
    "file-json": FileJsonIcon,
    "file-text": FileTextIcon,
  };
  return name && Object.hasOwn(icons, name) ? icons[name]! : PuzzleIcon;
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
  assetImporter: ModuleImporter = importAssetModule,
): Promise<LoadedContribution[]> {
  return Promise.all(
    entries.map(async (entry) => {
      if (entry.settings.enabled !== true || entry.module === null)
        return entry;
      try {
        let loadedModule: FrontendExtension;
        const transport = entry.transport ?? "inline-v1";
        if (transport === "assets-v1") {
          const expected = `/api/plugins/${entry.namespace}/assets/`;
          if (
            !entry.entry?.startsWith(expected) ||
            !/^[a-f0-9]{64}\/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*\/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.m?js$/.test(
              entry.entry.slice(expected.length),
            )
          )
            throw new Error("Invalid installed asset entry");
          loadedModule = (
            await assetImporter(`${getBackendBaseURL()}${entry.entry}`)
          ).default as FrontendExtension;
        } else if (transport === "inline-v1") {
          const expected = `/api/plugins/modules/${entry.module}/`;
          if (
            !entry.entry?.startsWith(expected) ||
            !/^[a-f0-9]{64}\.mjs$/.test(entry.entry.slice(expected.length))
          )
            throw new Error("Invalid installed module entry");
          const response = await fetch(`${getBackendBaseURL()}${entry.entry}`, {
            cache: "no-store",
          });
          if (!response.ok)
            throw new Error(`Plugin module unavailable (${response.status})`);
          const moduleURL = URL.createObjectURL(
            new Blob([await response.text()], { type: "text/javascript" }),
          );
          try {
            loadedModule = (await importer(moduleURL))
              .default as FrontendExtension;
          } finally {
            URL.revokeObjectURL(moduleURL);
          }
        } else {
          throw new Error("Unsupported browser asset transport");
        }
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
