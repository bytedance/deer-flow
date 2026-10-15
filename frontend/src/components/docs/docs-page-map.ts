import type { PageMapItem } from "nextra";

// Nextra's generated page map also contains unrelated App Router pages. Only
// these top-level content directories belong under /{lang}/docs.
export const DOCS_CONTENT_ROOTS = [
  "application",
  "harness",
  "introduction",
  "posts",
  "reference",
  "tutorials",
] as const;

const DOCS_CONTENT_ROOT_SET = new Set<string>(DOCS_CONTENT_ROOTS);

function isLocalizedDocsRoute(route: string, base: string): boolean {
  return route === base || route.startsWith(`${base}/`);
}

function isDocsContentRoute(route: string): boolean {
  const root = route.split("/").find(Boolean);
  return root === undefined || DOCS_CONTENT_ROOT_SET.has(root);
}

export function buildLocalizedDocsPageMap(
  base: string,
  items: PageMapItem[],
): PageMapItem[] {
  return items.flatMap<PageMapItem>((item) => {
    if (!("route" in item)) {
      return [item];
    }

    const alreadyLocalized = isLocalizedDocsRoute(item.route, base);
    if (!alreadyLocalized && !isDocsContentRoute(item.route)) {
      return [];
    }

    return [
      {
        ...item,
        route: alreadyLocalized ? item.route : `${base}${item.route}`,
        ...("children" in item
          ? { children: buildLocalizedDocsPageMap(base, item.children) }
          : {}),
      },
    ];
  });
}
