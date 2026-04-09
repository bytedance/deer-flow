import assert from "node:assert/strict";
import test from "node:test";

const { filterPresentChildren, hasBlockLevelChildren } = await import(
  new URL("./markdown-content-utils.ts", import.meta.url).href
);

function element(type: string, props: Record<string, unknown> = {}) {
  return { type, props };
}

void test("detects block-level markdown children", () => {
  const children = [
    element("span", { children: "inline" }),
    element("div", { children: "block" }),
  ];

  assert.equal(hasBlockLevelChildren(children), true);
});

void test("detects streamdown code block containers", () => {
  const children = element("span", { "data-code-block-container": true });

  assert.equal(hasBlockLevelChildren(children), true);
});

void test("ignores inline-only children", () => {
  const children = [
    element("span", { children: "inline" }),
    "plain text",
  ];

  assert.equal(hasBlockLevelChildren(children), false);
});

void test("filters empty paragraph children when unwrapping", () => {
  const children = filterPresentChildren([
    null,
    undefined,
    "",
    "text",
    element("div", { children: "block" }),
  ]);

  assert.equal(children.length, 2);
  assert.equal(children[0], "text");
  assert.equal((children[1] as { type: string }).type, "div");
});
