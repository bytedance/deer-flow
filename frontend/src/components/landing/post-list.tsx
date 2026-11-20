import Link from "next/link";

import { getBlogRoute, normalizeTagSlug, type BlogPost } from "@/core/blog";
import { cn } from "@/lib/utils";

type PostListProps = {
  description?: string;
  posts: BlogPost[];
  title: string;
};

type PostMetaProps = {
  currentLang?: string;
  date?: string | null;
  languages?: string[];
  pathname?: string;
};

function formatDate(date?: string): string | null {
  if (!date) {
    return null;
  }

  const value = new Date(date);
  if (Number.isNaN(value.getTime())) {
    return date;
  }

  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(value);
}

export function PostMeta({
  currentLang,
  date,
  languages,
  pathname,
}: PostMetaProps) {
  const formattedDate = formatDate(date ?? undefined);
  const availableLanguages = Array.isArray(languages)
    ? languages.filter((lang): lang is string => typeof lang === "string")
    : [];

  if (!formattedDate && availableLanguages.length <= 1) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-8 text-sm">
      {formattedDate ? (
        <p className="text-muted-foreground">{formattedDate}</p>
      ) : null}

      {pathname && availableLanguages.length > 1 ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-secondary-foreground text-sm">Language:</span>
          {availableLanguages.map((lang) => {
            const isActive = lang === currentLang;
            return (
              <Link
                key={lang}
                href={`${pathname}?lang=${lang}`}
                className={
                  isActive
                    ? "text-foreground text-sm font-medium"
                    : "text-muted-foreground hover:text-foreground text-sm transition-colors"
                }
              >
                {lang.toUpperCase()}
              </Link>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function PostTags({
  tags,
  className,
}: {
  tags?: unknown;
  className?: string;
}) {
  if (!Array.isArray(tags)) {
    return null;
  }

  const validTags = tags.filter(
    (tag): tag is string => typeof tag === "string" && tag.length > 0,
  );

  if (validTags.length === 0) {
    return null;
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-3", className)}>
      <span className="text-secondary-foreground text-sm">Tags:</span>
      {validTags.map((tag) => (
        <Link
          key={tag}
          href={`/blog/tags/${normalizeTagSlug(tag)}`}
          className="border-border text-secondary-foreground hover:text-foreground rounded-xl border px-2 py-1 text-sm transition-colors"
        >
          {tag}
        </Link>
      ))}
    </div>
  );
}

export function PostList({ description, posts, title }: PostListProps) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-12 px-6">
      <header className="space-y-4">
        <h2 className="text-foreground text-4xl font-semibold tracking-tight">
          {title}
        </h2>
        {description ? (
          <p className="text-secondary-foreground">{description}</p>
        ) : null}
      </header>

      <div className="space-y-12">
        {posts.map((post) => {
          return (
            <article
              key={post.slug.join("/")}
              className="border-border space-y-5 border-b pb-12 last:border-b-0 last:pb-0"
            >
              <div className="space-y-3">
                <PostMeta
                  currentLang={post.lang}
                  date={post.metadata.date}
                  languages={post.languages}
                  pathname={getBlogRoute(post.slug)}
                />
                <Link
                  href={getBlogRoute(post.slug)}
                  className="text-foreground hover:text-primary block text-2xl font-semibold tracking-tight transition-colors"
                >
                  {post.title}
                </Link>
              </div>

              {post.metadata.description ? (
                <p className="text-secondary-foreground leading-10">
                  {post.metadata.description}
                </p>
              ) : null}
              <PostTags tags={post.metadata.tags} />
            </article>
          );
        })}
      </div>
    </div>
  );
}
