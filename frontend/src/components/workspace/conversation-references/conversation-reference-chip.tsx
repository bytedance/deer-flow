import { MessagesSquareIcon, XIcon } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Shared visual for an attached conversation: a removable chip in the
 * composer, and a read-only chip (linking to the source) in the transcript.
 */
const CHIP_BASE_CLASS =
  "border-border bg-muted text-foreground inline-flex h-6 max-w-60 shrink-0 items-center gap-1 rounded-md border px-1.5 text-xs leading-none font-medium shadow-xs";

export function ConversationReferenceChip({
  title,
  href,
  className,
  onRemove,
  removeLabel,
}: {
  title: string;
  /** When provided (and the chip is not removable), the chip links to the source conversation. */
  href?: string;
  className?: string;
  /** When provided, the chip renders as a removable button with a close icon. */
  onRemove?: () => void;
  removeLabel?: string;
}) {
  const body = (
    <>
      <MessagesSquareIcon className="text-muted-foreground size-3 shrink-0" />
      <span className="min-w-0 truncate">{title}</span>
    </>
  );
  if (onRemove) {
    return (
      <button
        aria-label={removeLabel ?? `Remove ${title}`}
        className={cn(
          CHIP_BASE_CLASS,
          "hover:bg-accent cursor-pointer transition-colors",
          className,
        )}
        data-testid="conversation-reference-chip"
        onClick={onRemove}
        type="button"
      >
        {body}
        <XIcon className="text-muted-foreground size-2.5 shrink-0" />
      </button>
    );
  }
  if (href) {
    return (
      <Link
        className={cn(
          CHIP_BASE_CLASS,
          "hover:bg-accent transition-colors",
          className,
        )}
        data-testid="conversation-reference-chip"
        href={href}
        title={title}
      >
        {body}
      </Link>
    );
  }
  return (
    <span
      className={cn(CHIP_BASE_CLASS, className)}
      data-testid="conversation-reference-chip"
      title={title}
    >
      {body}
    </span>
  );
}
