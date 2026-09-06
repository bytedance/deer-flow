import { XIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Shared visual for a `/skill` activation, used both as a removable chip in the
 * composer and as a read-only chip in the chat transcript. Keeping a single
 * source of truth means the two stay in lockstep instead of drifting apart in
 * their Tailwind classes.
 */
const CHIP_BASE_CLASS =
  "border-primary/20 bg-primary/10 text-primary inline-flex h-6 shrink-0 items-center rounded-md border px-1.5 font-mono text-xs leading-none font-medium shadow-xs";

export function SlashSkillChip({
  name,
  className,
  onRemove,
  removeLabel,
}: {
  name: string;
  className?: string;
  /** When provided, the chip renders as a removable button with a close icon. */
  onRemove?: () => void;
  removeLabel?: string;
}) {
  if (onRemove) {
    return (
      <button
        aria-label={removeLabel ?? `Remove /${name}`}
        className={cn(
          CHIP_BASE_CLASS,
          "hover:bg-primary/20 cursor-pointer gap-1 transition-colors",
          className,
        )}
        onClick={onRemove}
        type="button"
      >
        <span className="min-w-0 truncate">/{name}</span>
        <XIcon className="text-primary/70 size-2.5 shrink-0" />
      </button>
    );
  }

  return (
    <span className={cn(CHIP_BASE_CLASS, "max-w-full", className)}>
      /{name}
    </span>
  );
}
