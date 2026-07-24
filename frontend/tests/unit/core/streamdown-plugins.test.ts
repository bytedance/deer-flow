import { expect, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { artifactMarkdownPlugins } from "@/components/workspace/artifacts/markdown-preview-plugins";
import { ArtifactLink } from "@/components/workspace/citations/artifact-link";
import {
  SafeStreamdown,
  streamdownPlugins,
  toStreamdownComponents,
} from "@/core/streamdown";

function renderArtifactMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(
      SafeStreamdown,
      {
        ...artifactMarkdownPlugins,
        components: toStreamdownComponents({ a: ArtifactLink }),
      },
      content,
    ),
  );
}

function renderSharedMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(SafeStreamdown, streamdownPlugins, content),
  );
}

test("adds GitHub-style heading anchors to artifact markdown previews", () => {
  const html = renderArtifactMarkdown(
    ["[概述](#概述)", "", "## 概述"].join("\n"),
  );

  expect(html).toContain('href="#%E6%A6%82%E8%BF%B0"');
  expect(html).toContain('id="概述"');
  expect(html).not.toContain("target=");
});

test("does not add heading anchors to the shared streamdown plugin config", () => {
  const html = [
    renderSharedMarkdown("## Summary"),
    renderSharedMarkdown("## Summary"),
  ].join("");

  expect(html).not.toContain('id="summary"');
});
