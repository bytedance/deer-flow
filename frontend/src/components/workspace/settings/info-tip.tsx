import { Info } from "lucide-react";

import { Tooltip } from "@/components/workspace/tooltip";

/**
 * Descriptive copy lives behind this ⓘ (2026-09-15): a screen of explanatory paragraphs read as
 * clutter beside the controls they described, and hovering is how a reader asks for one. The
 * icon's accessible name *is* that sentence, so it stays reachable by keyboard and assertable
 * by tests.
 *
 * `text` is that accessible name; `content` overrides what the bubble *renders* when one
 * sentence is really two (a section, not a control) and reads better as paragraphs. Callers
 * that pass only `text` get the same string in both places.
 *
 * The bubble is capped and **unbalanced** (2026-09-16). `TooltipContent` ships `text-balance`,
 * which evens a paragraph's lines inside whatever width the cap allows — the box stayed at the
 * cap while the evened lines fell short of it, so a two-line sentence rendered in the left half
 * with the right half empty. Dropping the balance lets each line run to the cap and leaves only
 * the usual short last line.
 */
export function InfoTip({
  text,
  content,
}: {
  text: string;
  content?: React.ReactNode;
}) {
  return (
    <Tooltip content={content ?? text} contentClassName="max-w-xs text-wrap">
      <button
        type="button"
        aria-label={text}
        className="text-muted-foreground inline-flex align-middle"
      >
        <Info className="size-3.5" />
      </button>
    </Tooltip>
  );
}
