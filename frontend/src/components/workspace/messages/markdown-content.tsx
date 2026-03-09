"use client";

import { memo, useMemo, type ComponentProps, type HTMLAttributes } from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

import { CollapsibleCodeBlock } from "./collapsible-code-block";
import { ScrollableTable } from "./scrollable-table";

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
};

/** Renders markdown content. */
export const MarkdownContent = memo(function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
}: MarkdownContentProps) {
  const components = useMemo(() => {
    return {
      table: (props: HTMLAttributes<HTMLTableElement>) => (
        <ScrollableTable {...props} />
      ),
      a: (props: ComponentProps<"a">) => {
        if (typeof props.children === "string") {
          const match = /^citation:(.+)$/.exec(props.children);
          if (match) {
            const [, text] = match;
            return <CitationLink {...props}>{text}</CitationLink>;
          }
        }
        const { className: linkClassName, href, ...linkProps } = props;

        return (
          <a
            {...linkProps}
            href={href}
            rel="noopener noreferrer"
            target="_blank"
            className={cn(
              "inline rounded-sm bg-primary/10 px-1 py-0.5 text-primary underline decoration-primary/80 decoration-2 underline-offset-4 transition-colors",
              "hover:bg-primary/15 hover:text-primary hover:decoration-primary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              linkClassName,
            )}
          />
        );
      },
      pre: (props: HTMLAttributes<HTMLPreElement>) => (
        <CollapsibleCodeBlock {...props} />
      ),
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
});
