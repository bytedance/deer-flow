// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Check, Copy } from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown, {
  type Options as ReactMarkdownOptions,
} from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

import { Button } from "~/components/ui/button";
import { rehypeSplitWordsIntoSpans } from "~/core/rehype";
import { katexOptions } from "~/core/markdown/katex";
import { autoFixMarkdown, normalizeMathForDisplay } from "~/core/utils/markdown";
import { cn } from "~/lib/utils";

import Image from "./image";
import { Tooltip } from "./tooltip";
import { Link } from "./link";
import { CitationLink, type CitationData } from "./citation";

export function Markdown({
  className,
  children,
  style,
  enableCopy,
  animated = false,
  checkLinkCredibility = false,
  citations = [],
  ...props
}: ReactMarkdownOptions & {
  className?: string;
  enableCopy?: boolean;
  style?: React.CSSProperties;
  animated?: boolean;
  checkLinkCredibility?: boolean;
  citations?: CitationData[];
}) {
  // Pre-compute normalized URL map for O(1) lookup
  const citationMap = useMemo(() => {
    const map = new Map<string, number>();
    citations?.forEach((c, index) => {
      if (!c.url) return;
      
      // Add exact match
      map.set(c.url, index);
      
      // Add decoded match
      try {
        const decoded = decodeURIComponent(c.url);
        if (decoded !== c.url) map.set(decoded, index);
      } catch {}
      
      // Add encoded match
      try {
        const encoded = encodeURI(c.url);
        if (encoded !== c.url) map.set(encoded, index);
      } catch {}
    });
    return map;
  }, [citations]);

  const components: ReactMarkdownOptions["components"] = useMemo(() => {
    return {
      a: ({ href, children }) => {
        const hrefStr = href ?? "";

        // Handle citation anchor targets (rendered in Reference list)
        // Format: [[n]](#citation-target-n)
        const targetMatch = hrefStr.match(/^#citation-target-(\d+)$/);
        if (targetMatch) {
          const index = targetMatch[1];
          return (
            <span
              id={`ref-${index}`}
              className="font-bold text-primary scroll-mt-20"
            >
              [{index}]
            </span>
          );
        }

        // Handle inline citation links (rendered in text)
        // Format: [[n]](#ref-n), [n](#ref1), [n](#1)
        const linkMatch = hrefStr.match(/^#(?:ref-?)?(\d+)$/);
        if (linkMatch) {
          return (
            <a
              href={hrefStr}
              className="text-primary hover:underline cursor-pointer marker-link"
              onClick={(e) => {
                e.preventDefault();
                const targetId = `ref-${linkMatch[1]}`;
                const element = document.getElementById(targetId);
                if (element) {
                  element.scrollIntoView({ behavior: "smooth", block: "start" });
                }
              }}
            >
              {children}
            </a>
          );
        }

        // If we have citation data, use CitationLink for enhanced display
        if (citations && citations.length > 0) {
          // Find if this URL is one of our citations
          const citationIndex = citationMap.get(hrefStr) ?? -1;

          if (citationIndex !== -1) {
            // Heuristic to determine if this is a citation target (in Reference list)
            // vs a citation link (in text).
            // Targets are usually the full title, while links are numbers like [1].
            const childrenText = Array.isArray(children)
              ? children.join("")
              : String(children);
            // Heuristic: inline citation text usually looks like a numeric marker
            // rather than a full title. We treat the following as "inline":
            //   "1", "[1]", "^1^", "[^1]" (with optional surrounding whitespace).
            // This pattern matches either:
            //   - a bracketed number: "[1]"
            //   - a caret-style number: "1", "^1", "1^", "^1^"
            // and ignores surrounding whitespace.
            const inlineCitationPattern = /^\s*(?:\[\d+\]|\^?\d+\^?)\s*$/;
            const isInline = inlineCitationPattern.test(childrenText);

            return (
              <CitationLink
                href={hrefStr}
                citations={citations}
                id={!isInline ? `ref-${citationIndex + 1}` : undefined}
              >
                {children}
              </CitationLink>
            );
          }

          return (
            <CitationLink href={hrefStr} citations={citations}>
              {children}
            </CitationLink>
          );
        }
        // Otherwise fall back to regular Link
        return (
          <Link href={href} checkLinkCredibility={checkLinkCredibility}>
            {children}
          </Link>
        );
      },
      img: ({ src, alt }) => (
        <a href={src as string} target="_blank" rel="noopener noreferrer">
          <Image className="rounded" src={src as string} alt={alt ?? ""} />
        </a>
      ),
    };
  }, [checkLinkCredibility, citations, citationMap]);

  const rehypePlugins = useMemo<NonNullable<ReactMarkdownOptions["rehypePlugins"]>>(() => {
    const plugins: NonNullable<ReactMarkdownOptions["rehypePlugins"]> = [[
      rehypeKatex,
      katexOptions,
    ]];
    if (animated) {
      plugins.push(rehypeSplitWordsIntoSpans);
    }
    return plugins;
  }, [animated]);
  return (
    <div className={cn(className, "prose dark:prose-invert")} style={style}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={rehypePlugins}
        components={components}
        {...props}
      >
        {autoFixMarkdown(
          dropMarkdownQuote(normalizeMathForDisplay(children ?? "")) ?? "",
        )}
      </ReactMarkdown>
      {enableCopy && typeof children === "string" && (
        <div className="flex">
          <CopyButton content={children} />
        </div>
      )}
    </div>
  );
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip title="Copy">
      <Button
        variant="outline"
        size="sm"
        className="rounded-full"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => {
              setCopied(false);
            }, 1000);
          } catch (error) {
            console.error(error);
          }
        }}
      >
        {copied ? (
          <Check className="h-4 w-4" />
        ) : (
          <Copy className="h-4 w-4" />
        )}{" "}
      </Button>
    </Tooltip>
  );
}



function dropMarkdownQuote(markdown?: string | null): string | null {
  if (!markdown) return null;

  const patternsToRemove = [
    { prefix: "```markdown\n", suffix: "\n```", prefixLen: 12 },
    { prefix: "```text\n", suffix: "\n```", prefixLen: 8 },
    { prefix: "```\n", suffix: "\n```", prefixLen: 4 },
  ];

  let result = markdown;
  
  for (const { prefix, suffix, prefixLen } of patternsToRemove) {
    if (result.startsWith(prefix) && !result.endsWith(suffix)) {
      result = result.slice(prefixLen);
      break;  // remove prefix without suffix only once
    }
  }
  
  let changed = true;

  while (changed) {
    changed = false;
    
    for (const { prefix, suffix, prefixLen } of patternsToRemove) {
      let startIndex = 0;
      while ((startIndex = result.indexOf(prefix, startIndex)) !== -1) {
        const endIndex = result.indexOf(suffix, startIndex + prefixLen);
        if (endIndex !== -1) {
          // only remove fully matched code blocks
          const before = result.slice(0, startIndex);
          const content = result.slice(startIndex + prefixLen, endIndex);
          const after = result.slice(endIndex + suffix.length);
          result = before + content + after;
          changed = true;
          startIndex = before.length + content.length;
        } else {
          startIndex += prefixLen;
        }
      }
    }
  }
  
  return result;
}