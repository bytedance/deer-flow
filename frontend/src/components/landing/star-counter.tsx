"use client";

import { StarFilledIcon } from "@radix-ui/react-icons";
import { useEffect, useState } from "react";

import { NumberTicker } from "@/components/ui/number-ticker";

/**
 * Add the runtime star count to a prerendered header without a client-side token.
 * No props; hides the optional count while unavailable and cancels on unmount.
 */
export function StarCounter() {
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
    <>
      <StarFilledIcon className="size-4 transition-colors duration-300 group-hover:text-yellow-500" />
      <NumberTicker className="font-mono tabular-nums" value={stars} />
    </>
  );
}
