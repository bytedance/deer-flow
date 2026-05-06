"use client";

import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { submitFeedback } from "@/core/feedback/api";

const CATEGORY_OPTIONS = [
  { key: "inaccurate", label: "Inaccurate" },
  { key: "incomplete", label: "Incomplete" },
  { key: "unsafe", label: "Unsafe" },
  { key: "formatting", label: "Formatting Issue" },
  { key: "other", label: "Other" },
];

export function FeedbackButtons({
  threadId,
  messageId,
}: {
  threadId: string;
  messageId: string;
}) {
  const [rating, setRating] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleThumbsUp() {
    if (submitting) return;
    setSubmitting(true);
    try {
      await submitFeedback({ thread_id: threadId, message_id: messageId, rating: 5 });
      setRating(5);
      toast.success("Thanks for your feedback!");
    } catch {
      toast.error("Failed to submit feedback");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleThumbsDown(categories: string[], comment: string) {
    if (submitting) return;
    setSubmitting(true);
    try {
      await submitFeedback({
        thread_id: threadId,
        message_id: messageId,
        rating: 1,
        categories,
        comment,
      });
      setRating(1);
      toast.success("Thanks for your feedback!");
    } catch {
      toast.error("Failed to submit feedback");
    } finally {
      setSubmitting(false);
    }
  }

  if (rating !== null) {
    return (
      <div className="text-muted-foreground flex items-center gap-1 text-xs">
        {rating >= 4 ? (
          <ThumbsUpIcon className="size-3.5" />
        ) : (
          <ThumbsDownIcon className="size-3.5" />
        )}
        <span>Feedback sent</span>
      </div>
    );
  }

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="size-7"
        onClick={handleThumbsUp}
        disabled={submitting}
        aria-label="Thumbs up"
      >
        <ThumbsUpIcon className="size-3.5" />
      </Button>
      <ThumbsDownPopover onSubmit={handleThumbsDown} disabled={submitting} />
    </>
  );
}

function ThumbsDownPopover({
  onSubmit,
  disabled,
}: {
  onSubmit: (categories: string[], comment: string) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  function toggleCategory(key: string) {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }

  function handleSubmit() {
    onSubmit(selected, comment);
    setOpen(false);
    setSelected([]);
    setComment("");
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          disabled={disabled}
          aria-label="Thumbs down"
        >
          <ThumbsDownIcon className="size-3.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3" align="end">
        <p className="mb-2 text-sm font-medium">What went wrong?</p>
        <div className="mb-2 flex flex-wrap gap-1.5">
          {CATEGORY_OPTIONS.map((cat) => (
            <button
              key={cat.key}
              type="button"
              onClick={() => toggleCategory(cat.key)}
              className={`rounded-full px-2.5 py-0.5 text-xs transition-colors ${
                selected.includes(cat.key)
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
        <textarea
          className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-xs resize-none"
          rows={2}
          placeholder="Optional comment..."
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <Button
          size="sm"
          className="mt-2 w-full"
          onClick={handleSubmit}
          disabled={disabled}
        >
          Submit
        </Button>
      </PopoverContent>
    </Popover>
  );
}
