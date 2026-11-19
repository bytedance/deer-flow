import type { PluginSurface } from "./contracts";
import { activeFrontendExtensions, type LoadedContribution } from "./registry";

/** Plugins register identifiers, never arbitrary host paths or external links. */
export function pluginPagePath(namespace: string, surfaceId: string) {
  return `/workspace/extensions/${encodeURIComponent(namespace)}/${encodeURIComponent(surfaceId)}`;
}

export function pluginPageTitle(surface: PluginSurface, locale: string) {
  return (
    (locale.startsWith("zh") ? surface.navigation?.labelZh : undefined) ??
    surface.navigation?.label ??
    surface.title
  );
}

export function pluginPages(entries: LoadedContribution[]) {
  return activeFrontendExtensions(entries).flatMap(
    ({ contribution, extension }) =>
      (extension.surfaces ?? [])
        .filter((surface) => surface.slot === "page")
        .map((surface) => ({
          contribution,
          surface,
          href: pluginPagePath(contribution.namespace, surface.id),
          icon: surface.navigation?.icon ?? extension.icon,
        })),
  );
}
