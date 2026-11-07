"use client";

import {
  Tooltip as TooltipPrimitive,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function Tooltip({
  children,
  content,
  ...props
}: {
  children: React.ReactNode;
  content?: React.ReactNode;
}) {
  // An empty string still mounts Radix content and shows a blank bubble.
  if (content === undefined || content === null || content === "") {
    return children;
  }
  return (
    <TooltipPrimitive delayDuration={500} {...props}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </TooltipPrimitive>
  );
}
