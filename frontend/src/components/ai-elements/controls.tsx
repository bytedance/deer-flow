"use client";

import { cn } from "@/lib/utils";
import { Controls as ControlsPrimitive } from "@xyflow/react";
import type { ComponentProps } from "react";

export type ControlsProps = ComponentProps<typeof ControlsPrimitive>;

export const Controls = ({ className, ...props }: ControlsProps) => (
  <ControlsPrimitive
    className={cn(
      "bg-card gap-px overflow-hidden rounded-md border p-1 shadow-none!",
      "[&>button]:hover:bg-secondary! [&>button]:rounded-md [&>button]:border-none! [&>button]:bg-transparent!",
      className,
    )}
    {...props}
  />
);
