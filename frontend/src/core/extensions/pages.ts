import type { PluginSurface } from "./contracts";
import { activeFrontendExtensions, type LoadedContribution } from "./registry";

/** Longest thread id a page deep-link may carry. */
const MAX_THREAD_QUERY_LENGTH = 256;

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

/**
 * Read the addressed thread from a page's `?thread=` query parameter.
 *
 * The value is caller input, not proof of access: it only becomes
 * `context.threadId` for the surface, and every action a plugin performs with
 * it must check ownership itself. Empty, repeated and oversized values are
 * ignored so a bad link renders the page without a thread.
 */
export function threadIdFromQuery(
  value: string | string[] | undefined,
): string | undefined {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (typeof candidate !== "string") {
    return undefined;
  }
  const threadId = candidate.trim();
  if (!threadId || threadId.length > MAX_THREAD_QUERY_LENGTH) {
    return undefined;
  }
  return threadId;
}
