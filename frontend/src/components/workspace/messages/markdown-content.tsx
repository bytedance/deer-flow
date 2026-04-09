"use client";

import { useMemo } from "react";
import {
  Children,
  isValidElement,
  type AnchorHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
};

const BLOCK_TAGS = new Set([
  "blockquote",
  "code",
  "div",
  "dl",
  "dt",
  "dd",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "ol",
  "p",
  "pre",
  "section",
  "table",
  "thead",
  "tbody",
  "tr",
  "ul",
]);

function isBlockCodeNode(node: unknown): boolean {
  if (!node || typeof node !== "object") {
    return false;
  }

  const tagName = "tagName" in node ? node.tagName : undefined;
  if (tagName !== "code") {
    return false;
  }

  const position = "position" in node ? node.position : undefined;
  if (!position || typeof position !== "object") {
    return false;
  }

  const start = "start" in position ? position.start : undefined;
  const end = "end" in position ? position.end : undefined;
  const startLine =
    start && typeof start === "object" && "line" in start ? start.line : undefined;
  const endLine =
    end && typeof end === "object" && "line" in end ? end.line : undefined;

  return typeof startLine === "number" && typeof endLine === "number"
    ? startLine !== endLine
    : false;
}

function hasBlockDescendant(children: ReactNode): boolean {
  return Children.toArray(children).some((child) => {
    if (!isValidElement(child)) {
      return false;
    }

    if (child.type === "div" || child.type === "pre") {
      return true;
    }

    const props = child.props as {
      children?: ReactNode;
      node?: { tagName?: string };
    };
    const tagName = props.node?.tagName;

    if ((tagName && BLOCK_TAGS.has(tagName)) || isBlockCodeNode(props.node)) {
      return true;
    }

    return hasBlockDescendant(props.children);
  });
}

function Paragraph(props: HTMLAttributes<HTMLParagraphElement>) {
  const { children, ...rest } = props;
  const Tag = hasBlockDescendant(children) ? "div" : "p";
  return <Tag {...rest}>{children}</Tag>;
}

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
}: MarkdownContentProps) {
  const components = useMemo(() => {
    return {
      a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => {
        if (typeof props.children === "string") {
          const match = /^citation:(.+)$/.exec(props.children);
          if (match) {
            const [, text] = match;
            return <CitationLink {...props}>{text}</CitationLink>;
          }
        }
        const { className, target, rel, ...rest } = props;
        const external = isExternalUrl(props.href);
        return (
          <a
            {...rest}
            className={cn(
              "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
              className,
            )}
            target={target ?? (external ? "_blank" : undefined)}
            rel={rel ?? (external ? "noopener noreferrer" : undefined)}
          />
        );
      },
      p: Paragraph,
      ...componentsFromProps,
    };
  }, [componentsFromProps]);

  if (!content) return null;

  return (
    <MessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {content}
    </MessageResponse>
  );
}
