import { useMDXComponents as getThemeComponents } from "nextra-theme-docs"; // nextra-theme-blog or your custom theme

import { LocalizedCards } from "@/components/docs/localized-cards";
import { LocalizedDocsLink } from "@/components/docs/localized-mdx-components";

// Get the default MDX components
const themeComponents = getThemeComponents();

// Merge components
export function useMDXComponents() {
  return {
    ...themeComponents,
    a: LocalizedDocsLink,
    Cards: LocalizedCards,
  };
}
