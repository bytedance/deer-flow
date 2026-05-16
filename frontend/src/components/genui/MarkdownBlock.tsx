"use client";

import { useState, useCallback } from "react";
import { toast } from "sonner";

import {
  MessageResponse,
} from "@/components/ai-elements/message";
import { useBlockStore, type UIBlock } from "@/core/genui/store";
import { streamdownPlugins } from "@/core/streamdown";

interface MarkdownBlockProps {
  block: UIBlock;
}

export default function MarkdownBlock({ block }: MarkdownBlockProps) {
  // Subscribe directly to the specific block from the store so edits
  // are reflected immediately regardless of parent re-render timing.
  const storeBlock = useBlockStore(
    (state) => state.blocks.get(block.block_id),
  );
  const effectiveBlock = storeBlock ?? block;

  const block_id = effectiveBlock.block_id;
  const content = (effectiveBlock.props.content as string) ?? "";
  const title = effectiveBlock.props.title as string | undefined;

  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(content);

  const handleStartEdit = useCallback(() => {
    setEditContent(content);
    setIsEditing(true);
  }, [content]);

  const handleSave = useCallback(() => {
    useBlockStore.getState().updateBlockProps(block_id, { content: editContent });
    setIsEditing(false);
    toast.success("保存成功");
  }, [block_id, editContent]);

  const handleCancel = useCallback(() => {
    if (editContent !== content) {
      if (!window.confirm("放弃未保存的更改？")) return;
    }
    setIsEditing(false);
  }, [editContent, content]);

  if (!content) return null;

  return (
    <div className="daily-report mx-auto w-full max-w-[800px] rounded-lg border bg-card p-6">
      <div className="mb-2 flex items-start justify-between gap-2">
        {title && <h3 className="text-sm font-medium">{title}</h3>}
        {!isEditing && (
          <button
            className="shrink-0 rounded px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            onClick={handleStartEdit}
          >
            编辑
          </button>
        )}
      </div>
      {isEditing ? (
        <div className="flex flex-col gap-3">
          <textarea
            className="min-h-[400px] w-full rounded border bg-background p-4 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <button
              className="rounded px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              onClick={handleCancel}
            >
              取消
            </button>
            <button
              className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={handleSave}
            >
              保存
            </button>
          </div>
        </div>
      ) : (
        <MessageResponse
          remarkPlugins={streamdownPlugins.remarkPlugins}
          rehypePlugins={streamdownPlugins.rehypePlugins}
        >
          {content}
        </MessageResponse>
      )}
    </div>
  );
}
