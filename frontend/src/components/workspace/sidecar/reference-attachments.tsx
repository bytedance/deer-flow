"use client";

import { MessageSquareQuoteIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { Tooltip } from "../tooltip";

import type { SidecarReference } from "./context";

function formatReferenceCount({
  count,
  one,
  many,
}: {
  count: number;
  one: string;
  many: string;
}) {
  return (count === 1 ? one : many).replace("{count}", String(count));
}

function formatPreviewText(content: string) {
  return content.replace(/\s+/g, " ").trim();
}

function ReferencePreview({ references }: { references: SidecarReference[] }) {
  if (references.length === 0) {
    return null;
  }

  return (
    <div className="w-72 max-w-[80vw] space-y-1.5">
      {references.map((reference) => (
        <div
          className="line-clamp-3 text-left text-sm leading-6 break-words"
          key={reference.id}
        >
          {`"${formatPreviewText(reference.context.content)}"`}
        </div>
      ))}
    </div>
  );
}

export function ReferenceAttachmentSummary({
  references,
  onClear,
  className,
  testId,
}: {
  references: SidecarReference[];
  onClear?: () => void;
  className?: string;
  testId?: string;
}) {
  const { t } = useI18n();
  if (references.length === 0) {
    return null;
  }

  const label = formatReferenceCount({
    count: references.length,
    one: t.sidecar.selectedTextFragment,
    many: t.sidecar.selectedTextFragments,
  });

  return (
    <div
      className={cn(
        "border-border bg-muted/40 text-foreground inline-flex max-w-[min(18rem,100%)] items-center gap-1.5 rounded-full border px-2.5 py-1.5 shadow-sm",
        className,
      )}
      data-testid={testId}
    >
      <Tooltip content={<ReferencePreview references={references} />}>
        <span className="flex min-w-0 cursor-default items-center gap-1.5">
          <MessageSquareQuoteIcon className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate text-sm font-medium">{label}</span>
        </span>
      </Tooltip>
      {onClear && (
        <Button
          aria-label={t.sidecar.clearReferences}
          className="text-muted-foreground hover:text-foreground size-6 rounded-full"
          size="icon-sm"
          type="button"
          variant="ghost"
          onClick={onClear}
        >
          <XIcon className="size-3.5" />
        </Button>
      )}
    </div>
  );
}
