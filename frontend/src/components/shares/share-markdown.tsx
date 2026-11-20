"use client";

import { useMemo } from "react";
import { visit } from "unist-util-visit";

import { shareArtifactURL, type SharedArtifact } from "@/core/shares/api";
import { resolveShareArtifact, sharedLink } from "@/core/shares/links";
import {
  SafeMessageResponse,
  streamdownPluginsWithoutRawHtml,
  toStreamdownComponents,
} from "@/core/streamdown";

// Normalize only Markdown URL nodes before the existing sanitizer runs. Code
// blocks and ordinary prose retain their original text and schemes stay denied.
type MarkdownNode = { type: string; url?: string; children?: MarkdownNode[] };
function remarkOutputLinks() {
  return (tree: MarkdownNode) => {
    visit(tree, (node) => {
      if (
        (node.type === "link" ||
          node.type === "image" ||
          node.type === "definition") &&
        node.url?.startsWith("sandbox:/mnt/user-data/outputs/")
      ) {
        node.url = node.url.slice("sandbox:".length);
      }
    });
  };
}

export function ShareMarkdown({
  content,
  token,
  artifacts,
  basePath = "",
}: {
  content: string;
  token: string;
  artifacts: SharedArtifact[];
  basePath?: string;
}) {
  const components = useMemo(
    () =>
      toStreamdownComponents({
        a: ({ href, children }) => {
          const target = href
            ? sharedLink(href, token, artifacts, basePath)
            : undefined;
          return target ? (
            <a
              href={target}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              className="underline"
            >
              {children}
            </a>
          ) : (
            <span>{children}</span>
          );
        },
        img: ({ src, alt }) => {
          const artifact =
            typeof src === "string"
              ? resolveShareArtifact(src, artifacts, basePath)
              : undefined;
          // Do not load third-party tracking images or live private file endpoints.
          return artifact ? (
            <img
              src={shareArtifactURL(token, artifact.path)}
              alt={alt ?? ""}
              referrerPolicy="no-referrer"
              className="max-w-full"
            />
          ) : (
            <span>{alt}</span>
          );
        },
      }),
    [token, artifacts, basePath],
  );
  return (
    <SafeMessageResponse
      mode="static"
      components={components}
      {...streamdownPluginsWithoutRawHtml}
      remarkPlugins={[
        ...(streamdownPluginsWithoutRawHtml.remarkPlugins ?? []),
        remarkOutputLinks,
      ]}
    >
      {content}
    </SafeMessageResponse>
  );
}
