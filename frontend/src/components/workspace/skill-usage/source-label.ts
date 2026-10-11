import { type Translations } from "@/core/i18n/locales/types";

export function skillSourceLabel(category: string, t: Translations) {
  switch (category) {
    case "public":
      return t.skillUsage.builtIn;
    case "custom":
      return t.skillUsage.custom;
    case "integrations":
      return t.skillUsage.integration;
    case "legacy":
      return t.skillUsage.legacy;
    default:
      return category;
  }
}
