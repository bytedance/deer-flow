import type { LocalizedText, PluginManifest } from "@/core/capabilities/types";
import type { MCPServerConfig } from "@/core/mcp/types";
export type { PluginCategory } from "@/core/capabilities/types";
export type CatalogPlugin = PluginManifest;
export const pluginCategories = [
  "office",
  "knowledge",
  "research",
  "business",
  "development",
  "custom",
] as const;
export function catalogText(text: LocalizedText, locale: string) {
  return text[locale] ?? text["en-US"] ?? Object.values(text)[0] ?? "";
}
/** Identity is explicit metadata. A display name never claims an official provider. */
export function catalogForServer(
  _name: string,
  config?: MCPServerConfig,
  catalog: PluginManifest[] = [],
) {
  const metadata = config?.capability;
  if (metadata && typeof metadata === "object" && "plugin_id" in metadata) {
    return catalog.find((item) => item.id === metadata.plugin_id);
  }
  return undefined;
}
