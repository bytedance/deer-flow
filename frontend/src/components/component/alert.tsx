"use client";

import { AlertCircleIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Alert as UiAlert, AlertDescription } from "@/components/ui/alert";

/** Workspace presets on top of `@/components/ui/alert` — add variants here. */

export function AlertError({
  children,
  className,
  ...props
}: {
  children: ReactNode;
  className?: string;
} & React.ComponentProps<typeof UiAlert>) {
  if (!children) {
    return null;
  }
  return (
    <UiAlert variant="destructive" className={className} {...props}>
      <AlertCircleIcon />
      <AlertDescription>{children}</AlertDescription>
    </UiAlert>
  );
}
