"use client";

import {
  Tooltip as TooltipPrimitive,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function Tooltip({
  children,
  content,
  contentClassName,
  ...props
}: {
  children: React.ReactNode;
  content?: React.ReactNode;
  contentClassName?: string;
}) {
  return (
    <TooltipPrimitive delayDuration={500} {...props}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className={contentClassName}>{content}</TooltipContent>
    </TooltipPrimitive>
  );
}
