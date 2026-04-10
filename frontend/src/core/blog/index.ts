import type { Folder, MdxFile, PageMapItem } from "nextra";
import { getPageMap } from "nextra/page-map";
import { cache } from "react";

import { getLangByLocale, type Locale } from "@/core/i18n/locale";

export const BLOG_LANGS = ["zh", "en"] as const;
const RECENT_POST_LIMIT = 5;

export type BlogLang = (typeof BLOG_LANGS)[number];

export type BlogMetadata = {
  date?: string;
  description?: string;
  item: MdxFile;
  tags: string[];
  title: string;
};

type BlogMdxFile = MdxFile & {
  frontMatter?: {
    date?: string;
    description?: string;
    tags?: unknown;
    title?: string;
  };
  title?: string;
};

export type BlogPost = {
  lang: BlogLang;
  languages: BlogLang[];
  metadata: BlogMetadata;
  slug: string[];
  title: string;
};

type LocalizedBlogPost = {
  lang: BlogLang;
  metadata: BlogMetadata;
  slug: string[];
  title: string;
};

export type BlogIndexData = {
  pageMap: PageMapItem[];
  posts: BlogPost[];
  recentPosts: BlogPost[];
  tags: Array<{ name: string; count: number; posts: BlogPost[] }>;
};

function isFolder(item: PageMapItem): item is Folder {
  return "children" in item && Array.isArray(item.children);
}

function isMdxFile(item: PageMapItem): item is BlogMdxFile {
  return "name" in item && "route" in item && !isFolder(item);
}

function normalizeBlogRoute(route: string): string {
  // Posts are sourced from locale-specific content trees but exposed
  // under the single public /blog route.
  return route.replace(/^\/(en|zh)\/(?:posts|blog)(?=\/|$)/, "/blog");
}

export function getBlogRoute(slug: string[]): string {
  return slug.length === 0 ? "/blog" : `/blog/${slug.join("/")}`;
}

function getSlugFromRoute(route: string): string[] {
  return route
    .replace(/^\/blog\/?/, "")
    .split("/")
    .filter(Boolean);
}

function getSlugKey(slug: string[]): string {
  return slug.join("/");
}

function parseTags(tags: unknown): string[] {
  if (!Array.isArray(tags)) {
    return [];
  }

  return tags.filter(
    (tag): tag is string => typeof tag === "string" && tag.length > 0,
  );
}

function parseDate(value: string | undefined): number {
  if (!value) {
    return 0;
  }

  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function selectPreferredLanguage(
  languages: BlogLang[],
  preferredLang?: BlogLang,
): BlogLang | null {
  if (preferredLang && languages.includes(preferredLang)) {
    return preferredLang;
  }

  // Keep fallback order stable so merged posts resolve predictably
  // when the preferred locale is unavailable.
  for (const lang of BLOG_LANGS) {
    if (languages.includes(lang)) {
      return lang;
    }
  }

  return null;
}

function collectLocalizedBlogPosts(
  items: PageMapItem[],
  lang: BlogLang,
): LocalizedBlogPost[] {
  const posts: LocalizedBlogPost[] = [];

  for (const item of items) {
    if (isFolder(item)) {
      posts.push(...collectLocalizedBlogPosts(item.children, lang));
      continue;
    }

    if (!isMdxFile(item)) {
      continue;
    }

    const route = normalizeBlogRoute(item.route);
    const slug = getSlugFromRoute(route);

    if (slug.length === 0) {
      continue;
    }

    const title = item.frontMatter?.title ?? item.title ?? item.name;

    posts.push({
      lang,
      metadata: {
        date: item.frontMatter?.date,
        description:
          typeof item.frontMatter?.description === "string"
            ? item.frontMatter.description
            : undefined,
        item: {
          ...item,
          route,
        },
        tags: parseTags(item.frontMatter?.tags),
        title,
      },
      slug,
      title,
    });
  }

  return posts;
}

function mergePostsBySlug(
  posts: LocalizedBlogPost[],
  preferredLang?: BlogLang,
): BlogPost[] {
  const postsBySlug = new Map<string, LocalizedBlogPost[]>();

  for (const post of posts) {
    const key = getSlugKey(post.slug);
    const group = postsBySlug.get(key) ?? [];
    group.push(post);
    postsBySlug.set(key, group);
  }

  return [...postsBySlug.values()]
    .flatMap((group): BlogPost[] => {
      const languages = group.map((post) => post.lang);
      const selectedLang = selectPreferredLanguage(languages, preferredLang);
      const primary =
        group.find((post) => post.lang === selectedLang) ?? group[0];

      if (!primary) {
        return [];
      }

      const mergedTags = new Set<string>();
      for (const post of group) {
        for (const tag of post.metadata.tags) {
          mergedTags.add(tag);
        }
      }

      return [
        {
          ...primary,
          languages,
          metadata: {
            ...primary.metadata,
            tags: [...mergedTags],
          },
        },
      ];
    })
    .sort((a, b) => parseDate(b.metadata.date) - parseDate(a.metadata.date));
}

function createFolder(
  name: string,
  route: string,
  title: string,
  children: PageMapItem[],
): Folder {
  return {
    children,
    name,
    route,
    title,
  } as Folder;
}

function createPostItem(post: BlogPost): MdxFile {
  return {
    ...post.metadata.item,
    name: post.title,
    route: getBlogRoute(post.slug),
  };
}

export function normalizeTagSlug(tag: string): string {
  return tag.toLowerCase().replace(/\s+/g, "-");
}

export function formatTagName(tag: string): string {
  return tag
    .split("-")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

export function getPreferredBlogLang(locale: Locale): BlogLang | undefined {
  const lang = getLangByLocale(locale);
  return BLOG_LANGS.find((value) => value === lang);
}

function matchTags(tags: string[], slug: string): boolean {
  for (const tag of tags) {
    if (normalizeTagSlug(tag) === slug) {
      return true;
    }
  }
  return false;
}

export const getAllPosts = cache(async function getAllPosts(
  preferredLang?: BlogLang,
): Promise<BlogPost[]> {
  const localizedPageMaps = await Promise.all(
    BLOG_LANGS.map(async (lang) => ({
      items: await getPageMap(`/${lang}/posts`),
      lang,
    })),
  );

  const localizedPosts = localizedPageMaps.flatMap(({ items, lang }) =>
    collectLocalizedBlogPosts(items, lang),
  );

  return mergePostsBySlug(localizedPosts, preferredLang);
});

export async function getBlogIndexData(
  preferredLang?: BlogLang,
  filters?: {
    tag?: string;
  },
): Promise<BlogIndexData> {
  const posts = await getAllPosts(preferredLang);
  const tagFilter = filters?.tag;
  const filteredPosts = tagFilter
    ? posts.filter((post) => matchTags(post.metadata.tags, tagFilter))
    : posts;
  const recentPosts = posts.slice(0, RECENT_POST_LIMIT);
  const postsByTag = new Map<string, BlogPost[]>();

  for (const post of posts) {
    for (const tag of post.metadata.tags) {
      const group = postsByTag.get(tag) ?? [];
      group.push(post);
      postsByTag.set(tag, group);
    }
  }

  const tags = [...postsByTag.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, tagPosts]) => ({
      count: tagPosts.length,
      name,
      posts: [...tagPosts].sort(
        (a, b) => parseDate(b.metadata.date) - parseDate(a.metadata.date),
      ),
    }));

  const pageMap: PageMapItem[] = [
    {
      data: {
        posts: { title: "All Posts", type: "Page" },
        recent_posts: { title: "Recent Posts" },
        tags: { title: "Tags" },
      },
    },
    {
      name: "All Posts",
      route: "/blog/posts",
      title: "All Posts",
      frontMatter: {
        title: "All Posts",
        filePath: "blog/index.mdx",
      },
    } as MdxFile,
    createFolder(
      "recent_posts",
      "/blog/recent-posts",
      "Recent Posts",
      recentPosts.map(createPostItem),
    ),
  ];

  if (tags.length > 0) {
    pageMap.push(
      createFolder(
        "tags",
        "/blog/tags",
        "Tags",
        tags.map((tag) => {
          return {
            name: tag.name,
            title: `${tag.name} (${tag.count})`,
            route: `/blog/tags/${normalizeTagSlug(tag.name)}`,
          };
        }),
      ),
    );
  }

  return {
    pageMap,
    posts: filteredPosts,
    recentPosts,
    tags,
  };
}
