"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FEEDBACK_TAG_SLUGS, type FeedbackTagSlug } from "@/core/api/feedback";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { Button } from "../../ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../ui/dialog";
import { Textarea } from "../../ui/textarea";

/** Maps language-neutral tag slugs to their i18n label keys. */
const TAG_LABEL_KEYS: Record<
  FeedbackTagSlug,
  "incorrect" | "notAsExpected" | "slow" | "styleTone" | "safetyLegal" | "other"
> = {
  incorrect: "incorrect",
  not_as_expected: "notAsExpected",
  slow: "slow",
  style_tone: "styleTone",
  safety_legal: "safetyLegal",
  other: "other",
};

/**
 * Thumbs-down follow-up dialog (ChatGPT-style): reason chips + optional
 * details. The rating itself is already stored when this opens; submitting
 * issues a second idempotent PUT that enriches the same record with
 * tags/comment. Closing without submitting keeps the plain thumbs-down.
 */
export function FeedbackDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (tags: string[], comment: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<Set<FeedbackTagSlug>>(new Set());
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const toggleTag = (slug: FeedbackTagSlug) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  };

  const canSubmit =
    (selected.size > 0 || comment.trim().length > 0) && !isSubmitting;

  // This dialog stays mounted across messages, so state has to be dropped on
  // every close path — submit, ESC, and click-outside all land here. Otherwise
  // the next thumbs-down opens pre-filled with the previous message's answers.
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setSelected(new Set());
      setComment("");
    }
    onOpenChange(next);
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      await onSubmit([...selected], comment.trim());
      handleOpenChange(false);
    } catch {
      // The rating itself is already stored; only this enrichment failed. Keep
      // the dialog open with the user's input so they can retry.
      toast.error(t.feedback.submitFailed);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.feedback.dialogTitle}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {FEEDBACK_TAG_SLUGS.map((slug) => (
            <button
              key={slug}
              type="button"
              onClick={() => toggleTag(slug)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition-colors",
                selected.has(slug)
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-foreground hover:bg-muted",
              )}
            >
              {t.feedback.tags[TAG_LABEL_KEYS[slug]]}
            </button>
          ))}
        </div>
        <Textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder={t.feedback.detailsPlaceholder}
          rows={4}
        />
        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {t.feedback.submit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
