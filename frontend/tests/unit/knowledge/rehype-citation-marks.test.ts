/**
 * rehype-citation-marks (phase-2 batch-1, P2): splits ``[n]`` markers inside
 * hast text nodes into ``<sup data-citation-index="n">n</sup>`` elements so
 * the markdown renderer can swap them for superscript citation marks. Text
 * inside code/pre subtrees is never touched (a ``[1]`` in a code block is
 * not a citation). Applied only after streaming ends (the chat panel gates
 * the plugin on ``isLoading``) so a half-typed ``[`` never flickers.
 */
import { describe, expect, test } from "@rstest/core";

import { rehypeCitationMarks } from "@/core/knowledge/rehype-citation-marks";

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

function paragraph(...children: HastNode[]): HastNode {
  return { type: "element", tagName: "p", children };
}

function text(value: string): HastNode {
  return { type: "text", value };
}

function run(tree: HastNode): HastNode {
  rehypeCitationMarks()(tree);
  return tree;
}

describe("rehypeCitationMarks", () => {
  test("rewrites [n] into a sup carrying data-citation-index", () => {
    const tree = run(paragraph(text("依据文档 [1] 可知")));
    const children = tree.children ?? [];
    expect(children).toHaveLength(3);
    expect(children[0]).toEqual(text("依据文档 "));
    expect(children[1]).toMatchObject({
      type: "element",
      tagName: "sup",
      properties: { dataCitationIndex: 1 },
      children: [text("1")],
    });
    expect(children[2]).toEqual(text(" 可知"));
  });

  test("leaves plain text untouched", () => {
    const tree = run(paragraph(text("没有引用的句子")));
    expect(tree.children).toEqual([text("没有引用的句子")]);
  });

  test("never touches code/pre subtrees", () => {
    const code: HastNode = { type: "element", tagName: "code", children: [text("arr[1] = 0")] };
    const tree = run(paragraph(text("见代码 "), code));
    expect(tree.children?.[1]).toEqual(code);
  });

  test("merges consecutive marks into one data-citation-indices sup (一句多标容错)", () => {
    const tree = run(paragraph(text("结论[1][2]。")));
    const children = tree.children ?? [];
    expect(children.filter((node) => node.tagName === "sup")).toHaveLength(1);
    expect(children[1]).toMatchObject({
      type: "element",
      tagName: "sup",
      properties: { dataCitationIndices: "1 2" },
      children: [text("1,2")],
    });
  });

  test("merges whitespace-separated runs ([7] [5] → one sup, model order kept)", () => {
    const tree = run(paragraph(text("超时自动放弃）[7] [5]")));
    const children = tree.children ?? [];
    expect(children.filter((node) => node.tagName === "sup")).toHaveLength(1);
    expect(children[1]).toMatchObject({ properties: { dataCitationIndices: "7 5" } });
  });

  test("does not merge across real text or punctuation (裁定①: 只有空白才算相邻)", () => {
    const withWords = run(paragraph(text("[1] 依据 [2]")));
    expect(withWords.children?.filter((node) => node.tagName === "sup")).toHaveLength(2);
    const withPunct = run(paragraph(text("[1]；[2]")));
    expect(withPunct.children?.filter((node) => node.tagName === "sup")).toHaveLength(2);
  });

  test("does not merge across element boundaries", () => {
    const tree = run(paragraph(text("a[1] "), { type: "element", tagName: "strong", children: [text("[2]")] }));
    const children = tree.children ?? [];
    expect(children.filter((node) => node.tagName === "sup")).toHaveLength(1);
    expect(children[1]).toMatchObject({ properties: { dataCitationIndex: 1 } });
    const strong = children.find((node) => node.tagName === "strong");
    expect(strong?.children?.[0]).toMatchObject({ properties: { dataCitationIndex: 2 } });
  });

  test("never merges hand-written sup elements", () => {
    const handwritten: HastNode = { type: "element", tagName: "sup", children: [text("†")] };
    const tree = run(paragraph(text("x[1] "), handwritten, text(" [2]")));
    const children = tree.children ?? [];
    // the hand-written sup separates the two marks into single marks
    expect(children.filter((node) => node.tagName === "sup")).toHaveLength(3);
    expect(children.filter((node) => node.properties?.dataCitationIndices !== undefined)).toHaveLength(0);
  });

  test("ignores three-digit brackets (not a citation)", () => {
    const tree = run(paragraph(text("编号 [123] 不是引用")));
    expect(tree.children).toEqual([text("编号 [123] 不是引用")]);
  });

  test("recurses into nested elements like list items", () => {
    const tree = run({
      type: "element",
      tagName: "ul",
      children: [{ type: "element", tagName: "li", children: [text("条目 [2]")] }],
    });
    const li = tree.children?.[0];
    expect(li?.children?.[1]).toMatchObject({ tagName: "sup", properties: { dataCitationIndex: 2 } });
  });
});
