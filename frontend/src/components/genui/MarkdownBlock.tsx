"use client";

import {
  MessageResponse,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";

interface MarkdownBlockProps {
  block: {
    props: {
      content: string;
      title?: string;
    };
  };
}

export default function MarkdownBlock({ block }: MarkdownBlockProps) {
  const { props } = block;
  const { content, title } = props;

  if (!content) return null;

  return (
    <div className="rounded-lg border bg-card p-4">
      {title && <h3 className="mb-2 text-sm font-medium">{title}</h3>}
      <MessageResponse
        remarkPlugins={streamdownPlugins.remarkPlugins}
        rehypePlugins={streamdownPlugins.rehypePlugins}
      >
        {content}
      </MessageResponse>
    </div>
  );
}
