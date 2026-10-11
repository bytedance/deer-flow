import { describe, expect, it } from "@rstest/core";

import {
  readKnowledgeSources,
  extractCitationSources,
} from "@/core/citations/sources";

const id = "a".repeat(32);
const ref = `#knowledge-source-${id}`;
const evidence = {
  id,
  provider: "lightrag",
  title: "docs/guide.md",
  excerpt: "Real retrieved evidence.",
};
const tool = {
  type: "tool",
  content: `[citation:Guide](${ref})\nReal retrieved evidence.`,
  artifact: { knowledge_sources_version: 1, knowledge_sources: [evidence] },
};

describe("knowledge source evidence", () => {
  it("resolves escaped document names without replacing genuine evidence titles", () => {
    const sources = readKnowledgeSources([tool]);
    expect(
      extractCitationSources(`[citation:Guide \\[draft\\]](${ref})`, sources)[0]
        ?.knowledge,
    ).toEqual(evidence);
  });
  it("resolves citations from live and replayed tool artifacts", () => {
    const sources = readKnowledgeSources([tool, tool]);
    expect(sources).toHaveLength(1);
    const citations = extractCitationSources(
      `Answer [citation:invented title](${ref})`,
      sources,
    );
    expect(citations).toHaveLength(1);
    expect(citations[0]?.title).toBe("docs/guide.md");
    expect(citations[0]?.knowledge?.excerpt).toBe("Real retrieved evidence.");
    expect(citations[0]?.knowledge?.page).toBeUndefined();
    expect(citations[0]?.knowledge?.url).toBeUndefined();
  });

  it("ignores absent evidence, assistant claims, code citations and unsupported versions", () => {
    expect(readKnowledgeSources([{ ...tool, type: "ai" }])).toEqual([]);
    expect(readKnowledgeSources([{ ...tool, content: "no evidence" }])).toEqual(
      [],
    );
    expect(
      readKnowledgeSources([
        {
          ...tool,
          artifact: { ...tool.artifact, knowledge_sources_version: 2 },
        },
      ]),
    ).toEqual([]);
    expect(extractCitationSources(`[citation:Guide](${ref})`)).toEqual([]);
    expect(
      extractCitationSources(
        `\`[citation:Guide](${ref})\``,
        readKnowledgeSources([tool]),
      ),
    ).toEqual([]);
  });

  it("rejects invalid locators instead of creating navigation links", () => {
    const forged = {
      ...tool,
      artifact: {
        ...tool.artifact,
        knowledge_sources: [{ ...evidence, url: "javascript:alert(1)" }],
      },
    };
    expect(readKnowledgeSources([forged])).toEqual([]);
  });
});
