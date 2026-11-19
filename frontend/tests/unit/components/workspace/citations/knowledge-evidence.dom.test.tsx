import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { KnowledgeEvidence } from "@/components/workspace/citations/knowledge-citation";
import { readKnowledgeSources } from "@/core/citations/sources";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

describe("registered provider evidence replay", () => {
  it("renders persisted plugin sources without fabricating pages or URLs", () => {
    const source = {
      id: "a".repeat(32),
      provider: "catalog-test-provider",
      title: "Captured manual",
      excerpt: "Actual retrieved excerpt.",
    };
    const persisted: unknown = JSON.parse(
      JSON.stringify([
        {
          type: "tool",
          name: "ext_example_search",
          content: `[citation:Captured manual](#knowledge-source-${source.id})\n${source.excerpt}`,
          artifact: {
            knowledge_sources_version: 1,
            knowledge_sources: [source],
          },
        },
      ]),
    );
    const sources = readKnowledgeSources(persisted as unknown[]);
    expect(sources).toHaveLength(1);
    render(
      <I18nProvider initialLocale="en-US">
        <KnowledgeEvidence source={sources[0]!} />
      </I18nProvider>,
    );
    expect(screen.getByText("catalog-test-provider")).toBeDefined();
    expect(screen.getByText(source.excerpt)).toBeDefined();
    expect(screen.queryByText(/Pages/)).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(
      readKnowledgeSources([
        {
          type: "tool",
          content: "unrelated",
          artifact: {
            knowledge_sources_version: 1,
            knowledge_sources: [source],
          },
        },
      ]),
    ).toEqual([]);
  });
});
