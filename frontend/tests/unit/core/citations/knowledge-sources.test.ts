import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  readKnowledgeSources,
  createKnowledgeSourceReader,
  retrievalSourceId,
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
  it("caches immutable messages but parses replacement objects", () => {
    const read = createKnowledgeSourceReader();
    const first = read(tool);
    expect(read(tool)).toBe(first);
    expect(read({ ...tool, content: "removed" })).toEqual([]);
    expect(read(tool)).toBe(first);
  });

  it("pins field limits and reference IDs to the cross-component schema", () => {
    const schema = JSON.parse(
      readFileSync(
        resolve(
          __dirname,
          "../../../../../contracts/knowledge_sources.v1.json",
        ),
        "utf-8",
      ),
    ) as {
      properties: { knowledge_sources_version: { const: number } };
      $defs: {
        source: {
          properties: Record<string, { maxLength?: number; pattern?: string }>;
        };
      };
    };
    expect(tool.artifact.knowledge_sources_version).toBe(
      schema.properties.knowledge_sources_version.const,
    );
    const fields = schema.$defs.source.properties;
    expect(new RegExp(fields.id!.pattern!).test(id)).toBe(true);
    expect(retrievalSourceId(ref)).toBe(id);
    expect(retrievalSourceId(`#user-content-knowledge-source-${id}`)).toBe(id);
    for (const invalid of [
      id + "a",
      id.slice(1),
      id.toUpperCase(),
      `${id}-1`,
    ]) {
      expect(retrievalSourceId(`#knowledge-source-${invalid}`)).toBeNull();
      expect(
        readKnowledgeSources([
          {
            ...tool,
            artifact: {
              ...tool.artifact,
              knowledge_sources: [{ ...evidence, id: invalid }],
            },
          },
        ]),
      ).toEqual([]);
    }
    for (const field of ["provider", "title", "excerpt", "dataset_name"]) {
      const limit = fields[field]!.maxLength!;
      for (const length of [limit, limit + 1]) {
        const candidate = { ...evidence, [field]: "x".repeat(length) };
        const message = {
          ...tool,
          content: `${ref}\n${candidate.excerpt}`,
          artifact: { ...tool.artifact, knowledge_sources: [candidate] },
        };
        expect(readKnowledgeSources([message]).length).toBe(
          length === limit ? 1 : 0,
        );
      }
    }
    const unicodeSource = { ...evidence, title: "😀".repeat(500) };
    expect(
      readKnowledgeSources([
        {
          ...tool,
          artifact: {
            ...tool.artifact,
            knowledge_sources: [unicodeSource],
          },
        },
      ]),
    ).toEqual([unicodeSource]);
  });
  it("reads unified evidence alongside native RAGFlow delegation snapshots", () => {
    const mixed = {
      ...tool,
      artifact: {
        knowledge_sources_version: 1,
        knowledge_sources: { version: 1, sources: [] },
        retrieval_sources: [evidence],
      },
    };
    expect(readKnowledgeSources([mixed])).toEqual([evidence]);
    expect(
      readKnowledgeSources([{ ...mixed, content: "unrelated report" }]),
    ).toEqual([]);
  });
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
