"use client";

import {
  MessageSquareTextIcon,
  PencilIcon,
  QuoteIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  artifactSelectionContext,
  MAX_SELECTION_LENGTH,
  sourceSelectionOffsets,
  type SourceSelection,
} from "@/core/artifacts/selection";
import { readArtifactSelection } from "@/core/artifacts/selection-dom";
import { useI18n } from "@/core/i18n/hooks";

import { useMaybeSidecar } from "../sidecar/context";

type Selection = {
  text: string;
  range: SourceSelection | null;
  exact: SourceSelection | null;
  rect: { left: number; bottom: number };
};

export function useArtifactSelection(options: {
  filepath: string;
  threadId: string;
  ownerId?: string;
  source: string;
  revision: string | null;
  enabled: boolean;
  editable: boolean;
}) {
  const { t } = useI18n();
  const sidecar = useMaybeSidecar();
  const [selection, setSelection] = useState<Selection | null>(null);
  useEffect(() => {
    setSelection(null);
  }, [
    options.filepath,
    options.threadId,
    options.ownerId,
    options.source,
    options.enabled,
  ]);
  useEffect(() => {
    if (!selection) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelection(null);
    };
    const dismiss = (event: Event) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest('[data-testid="artifact-selection-toolbar"]')
      )
        setSelection(null);
    };
    document.addEventListener("keydown", escape);
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("scroll", dismiss, true);
    return () => {
      document.removeEventListener("keydown", escape);
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("scroll", dismiss, true);
    };
  }, [selection]);

  const accept = (next: Selection | null) => {
    if (!options.enabled || !sidecar || !next?.text.trim()) {
      setSelection(null);
      return;
    }
    if (next.text.length > MAX_SELECTION_LENGTH) {
      setSelection(null);
      toast.error(t.artifactSelection.limit);
      return;
    }
    setSelection(next);
  };
  const dismiss = () => {
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  };
  const context = selection
    ? artifactSelectionContext(
        options.filepath,
        options.source,
        selection.text,
        selection.exact ?? selection.range,
      )
    : null;
  const rewrite = () => {
    if (
      !selection?.exact ||
      !context ||
      !sidecar ||
      !options.editable ||
      !options.revision
    )
      return;
    sidecar.beginArtifactEdit({
      id: crypto.randomUUID(),
      context,
      filepath: options.filepath,
      threadId: options.threadId,
      ownerId: options.ownerId,
      source: options.source,
      revision: options.revision,
      ...selection.exact,
    });
    dismiss();
  };

  return {
    onTextSelection:
      options.enabled && sidecar
        ? (container: HTMLElement) =>
            accept(readArtifactSelection(container, options.source))
        : undefined,
    onSourceSelection: (
      next: (SourceSelection & { rect: Selection["rect"] }) | null,
    ) => {
      if (!next) return accept(null);
      const exact = sourceSelectionOffsets(options.source, next);
      accept({
        text: options.source.slice(exact.from, exact.to),
        range: exact,
        exact,
        rect: next.rect,
      });
    },
    toolbar:
      selection && context && sidecar && options.enabled
        ? createPortal(
            <div
              role="toolbar"
              aria-label={t.sidecar.reference}
              data-testid="artifact-selection-toolbar"
              className="bg-popover text-popover-foreground fixed z-50 flex max-w-[calc(100vw-16px)] flex-wrap gap-1 rounded-lg border p-1 shadow-lg"
              style={{
                left: Math.max(
                  8,
                  Math.min(selection.rect.left, window.innerWidth - 460),
                ),
                top: Math.max(
                  8,
                  Math.min(selection.rect.bottom + 8, window.innerHeight - 90),
                ),
              }}
              onMouseDown={(event) => event.preventDefault()}
            >
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  sidecar.addContextToConversation(context);
                  dismiss();
                }}
              >
                <QuoteIcon />
                {t.sidecar.addToConversation}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  sidecar.openContext(context);
                  dismiss();
                }}
              >
                <MessageSquareTextIcon />
                {t.sidecar.askInSideChat}
              </Button>
              {options.editable && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!selection.exact}
                  title={
                    !selection.exact
                      ? t.artifactSelection.exactRequired
                      : undefined
                  }
                  onClick={rewrite}
                >
                  <PencilIcon />
                  {t.artifactSelection.rewrite}
                </Button>
              )}
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={t.common.close}
                onClick={dismiss}
              >
                <XIcon />
              </Button>
            </div>,
            document.body,
          )
        : null,
  };
}
