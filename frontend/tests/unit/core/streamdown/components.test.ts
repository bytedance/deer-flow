import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { SafeParagraph } from "@/core/streamdown/components";

const imageNodeProps = {
  node: { tagName: "img" },
} as Record<string, unknown>;

function TestImage(_props: Record<string, unknown>) {
  return createElement("img", {
    alt: "diagram",
    src: "/diagram.png",
  });
}

test("SafeParagraph treats whitespace-only siblings as empty for image-only paragraphs", () => {
  const html = renderToStaticMarkup(
    createElement(
      SafeParagraph,
      null,
      "\n",
      createElement(TestImage, imageNodeProps),
      " ",
    ),
  );

  expect(html).toContain('<img alt="diagram" src="/diagram.png"/>');
  expect(html).not.toContain("<p");
});

test("SafeParagraph drops whitespace-only chunks around block children", () => {
  const html = renderToStaticMarkup(
    createElement(
      SafeParagraph,
      null,
      "\n",
      createElement("div", null, "block"),
      " ",
    ),
  );

  expect(html).toBe("<div>block</div>");
});

test("SafeParagraph omits unique attributes when splitting into multiple paragraphs", () => {
  const html = renderToStaticMarkup(
    createElement(
      SafeParagraph,
      {
        id: "message",
        "aria-describedby": "description",
        "aria-labelledby": "label",
        className: "content",
      },
      "before",
      createElement("div", null, "block"),
      "after",
    ),
  );

  expect(html).toBe(
    '<p class="content">before</p><div>block</div><p class="content">after</p>',
  );
});
