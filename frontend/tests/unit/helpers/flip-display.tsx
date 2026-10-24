import type { ComponentProps } from "react";

import type { FlipDisplay as AnimatedFlipDisplay } from "@/components/workspace/flip-display";

// Content/state tests keep real React behavior without exercising Motion's
// browser animation lifecycle in Happy DOM. Preserve keyed child remounts.
export function FlipDisplay({
  uniqueKey,
  children,
  className,
}: ComponentProps<typeof AnimatedFlipDisplay>) {
  return (
    <div className={className}>
      <div key={uniqueKey}>{children}</div>
    </div>
  );
}
