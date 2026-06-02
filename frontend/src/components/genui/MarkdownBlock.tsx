"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import {
  MessageResponse,
} from "@/components/ai-elements/message";
import { useBlockPersist } from "@/core/genui/block-persist-context";
import { useBlockStore, type UIBlock } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";
import { streamdownPlugins } from "@/core/streamdown";

interface MarkdownBlockProps {
  block: UIBlock;
}

export default function MarkdownBlock({ block }: MarkdownBlockProps) {
  const { t } = useI18n();
  const persist = useBlockPersist();
  const updateBlockProps = useBlockStore((state) => state.updateBlockProps);
  const storeBlock = useBlockStore(
    (state) => state.blocks.get(block.block_id),
  );
  const effectiveBlock = storeBlock ?? block;

  const block_id = effectiveBlock.block_id;
  const content = (effectiveBlock.props.content as string) ?? "";
  const title = effectiveBlock.props.title as string | undefined;

  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editContent, setEditContent] = useState(content);

  const handleStartEdit = useCallback(() => {
    setEditContent(content);
    setIsEditing(true);
  }, [content]);

  const handleSave = useCallback(async () => {
    const updates = { content: editContent };
    updateBlockProps(block_id, updates);
    if (persist) {
      setIsSaving(true);
      try {
        await persist.saveContent(block_id, editContent);
        toast.success(t.genui.saveSuccess);
        setIsEditing(false);
      } catch {
        toast.error(t.genui.saveFailed);
      } finally {
        setIsSaving(false);
      }
    } else {
      setIsEditing(false);
      toast.success(t.genui.saveSuccess);
    }
  }, [block_id, editContent, persist, t, updateBlockProps]);

  const handleCancel = useCallback(() => {
    if (editContent !== content) {
      if (!window.confirm(t.genui.discardUnsaved)) return;
    }
    setIsEditing(false);
  }, [editContent, content, t.genui.discardUnsaved]);

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
            {t.genui.edit}
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
              {t.common.cancel}
            </button>
            <button
              className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? (
                <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
              ) : null}
              {t.genui.save}
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
