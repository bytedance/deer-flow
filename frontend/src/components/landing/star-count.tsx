"use client";

import { NumberTicker } from "@/components/ui/number-ticker";
import { usePrefersReducedMotion } from "@/core/dom/render-activity";

/**
 * Star count for the shared site header.
 *
 * The header is reused by the docs and blog layouts, so the landing page's
 * count-up animation follows it onto pages that are otherwise still. This
 * renders the plain number when the user prefers reduced motion; `NumberTicker`
 * starts from 0 and springs upward, which would otherwise animate on every
 * docs navigation.
 */
export function StarCount({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  const reducedMotion = usePrefersReducedMotion();

  if (reducedMotion) {
    return <span className={className}>{value.toLocaleString()}</span>;
  }

  return <NumberTicker className={className} value={value} />;
}
