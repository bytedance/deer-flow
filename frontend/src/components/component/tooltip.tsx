"use client";

import type { ComponentProps, ReactNode } from "react";

import {
  Tooltip as TooltipPrimitive,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function Tooltip({
  children,
  content,
  delayDuration = 500,
  ...props
}: {
  children: ReactNode;
  content?: ReactNode;
  delayDuration?: number;
} & Omit<ComponentProps<typeof TooltipPrimitive>, "children">) {
  return (
    <TooltipPrimitive delayDuration={delayDuration} {...props}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </TooltipPrimitive>
  );
}
