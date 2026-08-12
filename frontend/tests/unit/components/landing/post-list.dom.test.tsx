import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { PostList } from "@/components/landing/post-list";
import type { BlogPost } from "@/core/blog";

afterEach(cleanup);

const posts = [
  {
    slug: ["hello-world"],
    title: "Hello World",
    lang: "en",
    languages: ["en"],
    metadata: { date: "2026-01-02", description: "First post description." },
  },
  {
    slug: ["second-post"],
    title: "Second Post",
    lang: "en",
    languages: ["en"],
    metadata: { date: "2026-01-03", description: "Second post description." },
  },
] as unknown as BlogPost[];

describe("PostList", () => {
  it("gives the page a single top-level heading", () => {
    render(<PostList title="All Posts" posts={posts} />);

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]?.textContent).toBe("All Posts");
  });

  it("exposes each entry as a heading below the page title", () => {
    render(<PostList title="All Posts" posts={posts} />);

    const entries = screen.getAllByRole("heading", { level: 2 });
    expect(entries.map((entry) => entry.textContent)).toEqual([
      "Hello World",
      "Second Post",
    ]);

    // The title stays a link inside the heading so the list is both
    // navigable by heading and clickable.
    for (const entry of entries) {
      expect(entry.querySelector("a")).toBeTruthy();
    }
  });

  it("keeps post descriptions at a readable line height on small screens", () => {
    render(<PostList title="All Posts" posts={posts} />);

    const description = screen.getByText("First post description.");
    // `leading-10` is 2.5rem of leading on 1rem text, which reads as
    // disconnected lines on a narrow viewport.
    expect(description.className).not.toContain("leading-10");
    expect(description.className).toContain("leading-7");
  });
});
