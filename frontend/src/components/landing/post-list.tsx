import Link from "next/link";

import { getBlogRoute, normalizeTagSlug, type BlogPost } from "@/core/blog";

type PostListProps = {
  description?: string;
  posts: BlogPost[];
  title: string;
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

export function PostList({ description, posts, title }: PostListProps) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-12 px-6">
      <header className="space-y-4">
        <h2 className="text-foreground text-4xl font-semibold tracking-tight">
          {title}
        </h2>
        {description ? <p className="text-muted-foreground">{description}</p> : null}
      </header>

      <div className="space-y-12">
        {posts.map((post) => {
          const date = formatDate(post.metadata.date);

          return (
            <article
              key={post.slug.join("/")}
              className="border-border space-y-5 border-b pb-12 last:border-b-0 last:pb-0"
            >
              <div className="space-y-2">
                {date ? <p className="text-muted-foreground">{date}</p> : null}
                <Link
                  href={getBlogRoute(post.slug)}
                  className="text-foreground hover:text-primary block text-2xl font-semibold tracking-tight transition-colors"
                >
                  {post.title}
                </Link>
              </div>

              {post.metadata.description ? (
                <p className="text-muted-foreground leading-10">
                  {post.metadata.description}
                </p>
              ) : null}

              {post.metadata.tags.length > 0 ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-foreground font-semibold">Tags:</span>
                  {post.metadata.tags.map((tag) => (
                    <Link
                      key={tag}
                      href={`/blog/tags/${normalizeTagSlug(tag)}`}
                      className="border-border text-muted-foreground hover:text-foreground rounded-xl border px-2 py-1 text-sm transition-colors"
                    >
                      {tag}
                    </Link>
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
