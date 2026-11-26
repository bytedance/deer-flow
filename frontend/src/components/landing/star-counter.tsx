"use client";

import { StarFilledIcon } from "@radix-ui/react-icons";
import { useEffect, useState } from "react";

import { NumberTicker } from "@/components/ui/number-ticker";
import { cn } from "@/lib/utils";

export type StarCounterProps = {
  className?: string;
};

/**
 * Add the runtime star count to a prerendered header without a client-side token.
 * Hides the optional count while unavailable and cancels the request on unmount.
 */
export function StarCounter({ className }: StarCounterProps) {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // The root layout has no query provider; this one-shot decorative request
    // leaves homepage rendering static and GitHub caching on the server.
    void fetch("/github-stars", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok || response.status === 204) return;
        const data = (await response.json()) as { stars?: unknown };
        if (
          !controller.signal.aborted &&
          typeof data.stars === "number" &&
          Number.isSafeInteger(data.stars) &&
          data.stars >= 0
        ) {
          setStars(data.stars);
        }
      })
      .catch(() => {
        // An unavailable optional counter must not break the GitHub link.
      });
    return () => controller.abort();
  }, []);

  if (stars === null) return null;
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <StarFilledIcon
        className="size-3.5 text-[var(--df-accent)] transition-colors duration-150 group-hover:text-[var(--df-accent-strong)]"
        aria-hidden="true"
      />
      <NumberTicker
        className="font-mono text-xs font-medium text-inherit tabular-nums"
        value={stars}
      />
    </span>
  );
}
