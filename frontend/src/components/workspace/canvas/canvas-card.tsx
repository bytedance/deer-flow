import { LayoutGridIcon, PlayIcon } from "lucide-react";
import { useCallback } from "react";

import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useCanvasContext } from "../canvas/context";

interface CanvasCardProps {
  className?: string;
  canvasName: string;
  canvasDescription: string;
}

export function CanvasCard({
  className,
  canvasName,
  canvasDescription,
}: CanvasCardProps) {
  const { t } = useI18n();
  const { setOpen } = useCanvasContext();

  const handleClick = useCallback(() => {
    setOpen(true);
  }, [setOpen]);

  return (
    <Card
      className={cn("relative cursor-pointer p-3", className)}
      onClick={handleClick}
    >
      <CardHeader className="grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 pr-2 pl-1">
        <CardTitle className="relative min-w-0 pl-8 leading-tight [overflow-wrap:anywhere] break-words">
          <div className="min-w-0">{canvasName}</div>
          <div className="absolute top-2 -left-0.5">
            <LayoutGridIcon className="size-6 text-primary" />
          </div>
        </CardTitle>
        <CardDescription className="min-w-0 pl-8 text-xs">
          {canvasDescription || t.canvas.dataAnalysis}
        </CardDescription>
        <CardAction className="row-span-1 self-center">
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <PlayIcon className="size-4" />
            <span>{t.canvas.openCanvas}</span>
          </div>
        </CardAction>
      </CardHeader>
    </Card>
  );
}