"use client";

import { LayoutGrid } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useCanvasContext } from "./context";

export function CanvasTrigger() {
  const { open, setOpen, canvas } = useCanvasContext();

  // 与 ArtifactTrigger 一致：只在有 canvas 数据时才显示
  if (!canvas) {
    return null;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setOpen(!open)}
            className={open ? "bg-accent" : ""}
          >
            <LayoutGrid className="h-5 w-5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{open ? "Close Canvas" : "Open Canvas"}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
