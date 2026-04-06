"use client";

import { useMemo } from "react";
import type { AnchorHTMLAttributes, ImgHTMLAttributes } from "react";
import { useParams } from "next/navigation";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import {
  isArtifactVirtualPath,
  resolveArtifactURL,
} from "@/core/artifacts/utils";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

function resolveThreadAssetURL(src: string | undefined, threadId?: string) {
  if (!src || !threadId || !isArtifactVirtualPath(src)) {
    return src;
  }
  return resolveArtifactURL(src, threadId);
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
};

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
}: MarkdownContentProps) {
  const { thread_id } = useParams<{ thread_id?: string }>();
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
        const href = resolveThreadAssetURL(props.href, thread_id);
        const external = isExternalUrl(href);
        return (
          <a
            {...rest}
            href={href}
            className={cn(
              "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
              className,
            )}
            target={target ?? (external ? "_blank" : undefined)}
            rel={rel ?? (external ? "noopener noreferrer" : undefined)}
          />
        );
      },
      img: (props: ImgHTMLAttributes<HTMLImageElement>) => {
        const { className: imageClassName, src, alt, ...rest } = props;
        const resolvedSrc =
          typeof src === "string" ? resolveThreadAssetURL(src, thread_id) : src;

        if (!resolvedSrc) {
          return null;
        }

        if (typeof resolvedSrc !== "string") {
          return (
            <img
              {...rest}
              alt={alt}
              src={resolvedSrc}
              className={cn(
                "my-3 max-w-[90%] overflow-hidden rounded-lg",
                imageClassName,
              )}
            />
          );
        }

        return (
          <a href={resolvedSrc} target="_blank" rel="noopener noreferrer">
            <img
              {...rest}
              alt={alt}
              src={resolvedSrc}
              className={cn(
                "my-3 max-w-[90%] overflow-hidden rounded-lg",
                imageClassName,
              )}
            />
          </a>
        );
      },
      ...componentsFromProps,
    };
  }, [componentsFromProps, thread_id]);

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
