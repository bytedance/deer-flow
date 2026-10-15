import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { ProjectThreadsSection } from "@/components/workspace/projects/project-threads-section";
import { I18nProvider } from "@/core/i18n/context";
import type { ProjectThreadsQueryResult } from "@/core/projects";
import type { ProjectThread } from "@/core/projects/types";

// Keep the row links inert under happy-dom; only the href wiring matters.
rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>;
  return { default: MockLink };
});

function makeThread(id: string, title: string): ProjectThread {
  return {
    thread_id: id,
    display_name: title,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

function makeQuery(threads: ProjectThread[]): ProjectThreadsQueryResult {
  return {
    data: { pages: [threads], pageParams: [0] },
    isError: false,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: rs.fn(),
  } as unknown as ProjectThreadsQueryResult;
}

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

afterEach(() => {
  cleanup();
});

describe("ProjectThreadsSection", () => {
  it("renders a divider on every row except the final one", () => {
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={makeQuery([
            makeThread("t-1", "First"),
            makeThread("t-2", "Second"),
            makeThread("t-3", "Third"),
          ])}
        />
      </Wrapper>,
    );

    const links = container.querySelectorAll<HTMLAnchorElement>("a");
    expect(links).toHaveLength(3);
    expect(links[0]?.href).toContain("/workspace/chats/t-1");
    const rowDivs = [...links].map((link) => link.firstElementChild);
    expect(rowDivs[0]?.classList.contains("border-b")).toBe(true);
    expect(rowDivs[1]?.classList.contains("border-b")).toBe(true);
    // Only the final data row drops the divider — the check must hold even
    // when virtualization mounts just a window of rows.
    expect(rowDivs[2]?.classList.contains("border-b")).toBe(false);
  });

  it("shows the untitled fallback and the load-more button for a partial page", () => {
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={
            {
              data: {
                pages: [[makeThread("t-1", "  ")]],
                pageParams: [0],
              },
              isError: false,
              isLoading: false,
              hasNextPage: true,
              isFetchingNextPage: false,
              fetchNextPage: rs.fn(),
            } as unknown as ProjectThreadsQueryResult
          }
        />
      </Wrapper>,
    );

    expect(container.textContent).toContain("Untitled");
    expect(
      container.querySelector('[data-testid="project-threads-load-more"]'),
    ).not.toBeNull();
  });
});
