"use client";

import { InfoIcon, XIcon } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { useStreamTierNotice } from "@/core/threads/use-stream-tier";
import { cn } from "@/lib/utils";

const DISMISS_KEY = "stream-tier-notice-dismissed";

export function StreamTierNoticeBanner() {
  const notice = useStreamTierNotice();
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    if (!notice) return;
    const stored = typeof window !== "undefined" ? sessionStorage.getItem(DISMISS_KEY) : null;
    setDismissed(stored === "1");
  }, [notice]);

  if (!notice || dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    if (typeof window !== "undefined") {
      sessionStorage.setItem(DISMISS_KEY, "1");
    }
  };

  return (
    <div
      role="status"
      className={cn(
        "mx-auto flex max-w-3xl items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
      )}
    >
      <InfoIcon className="size-4 shrink-0" />
      <span className="flex-1">{notice.message}</span>
      <button
        type="button"
        onClick={handleDismiss}
        className="shrink-0 rounded p-0.5 hover:bg-blue-200/50 dark:hover:bg-blue-800/50"
        aria-label="关闭提示"
      >
        <XIcon className="size-3.5" />
      </button>
    </div>
  );
}
