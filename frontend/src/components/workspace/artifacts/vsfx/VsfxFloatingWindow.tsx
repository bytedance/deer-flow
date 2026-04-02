"use client";

import { Minus, PanelTopOpen } from "lucide-react";
import { type MouseEvent as ReactMouseEvent, type PropsWithChildren, useEffect, useRef } from "react";

import {
  Artifact,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type VsfxFloatingWindowProps = PropsWithChildren<{
  className?: string;
  containerElement: HTMLDivElement | null;
  contentClassName?: string;
  description?: string;
  "data-testid"?: string;
  minimized: boolean;
  offset: { x: number; y: number };
  onOffsetChange: (offset: { x: number; y: number }) => void;
  onToggleMinimized: () => void;
  title: string;
}>;

export function VsfxFloatingWindow({
  children,
  className,
  containerElement,
  contentClassName,
  description,
  minimized,
  offset,
  onOffsetChange,
  onToggleMinimized,
  title,
  ...props
}: VsfxFloatingWindowProps) {
  const { "data-testid": dataTestId, ...artifactProps } = props;
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerStartX: number;
    pointerStartY: number;
    startOffsetX: number;
    startOffsetY: number;
  } | null>(null);
  const offsetRef = useRef(offset);

  useEffect(() => {
    offsetRef.current = offset;
  }, [offset]);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      const activeDrag = dragStateRef.current;
      const containerRect = containerElement?.getBoundingClientRect();
      const windowRect = windowRef.current?.getBoundingClientRect();
      const currentOffset = offsetRef.current;

      if (!activeDrag || !containerRect || !windowRect) {
        return;
      }

      const baseLeft = windowRect.left - currentOffset.x;
      const baseTop = windowRect.top - currentOffset.y;
      const minOffsetX = containerRect.left - baseLeft;
      const maxOffsetX = containerRect.right - (baseLeft + windowRect.width);
      const minOffsetY = containerRect.top - baseTop;
      const maxOffsetY = containerRect.bottom - (baseTop + windowRect.height);
      const nextOffsetX = activeDrag.startOffsetX + (event.clientX - activeDrag.pointerStartX);
      const nextOffsetY = activeDrag.startOffsetY + (event.clientY - activeDrag.pointerStartY);

      onOffsetChange({
        x: clamp(nextOffsetX, minOffsetX, maxOffsetX),
        y: clamp(nextOffsetY, minOffsetY, maxOffsetY),
      });
    };

    const handleMouseUp = () => {
      dragStateRef.current = null;
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [containerElement, onOffsetChange]);

  const handleTitleBarMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }

    dragStateRef.current = {
      pointerStartX: event.clientX,
      pointerStartY: event.clientY,
      startOffsetX: offsetRef.current.x,
      startOffsetY: offsetRef.current.y,
    };
  };

  const toggleButtonLabel = `${minimized ? "Restore" : "Minimize"} ${title}`;

  return (
    <div
      data-state={minimized ? "minimized" : "expanded"}
        data-testid={dataTestId}
        className={cn(
          "pointer-events-auto absolute top-4 right-4 z-20 flex min-h-0 w-80 flex-col overflow-hidden border shadow-xl",
          minimized ? "h-auto max-h-none" : "h-auto max-h-[calc(100%-2rem)]",
          className,
        )}
        ref={windowRef}
        style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
        {...artifactProps}
      >
      <Artifact className="min-h-0 max-h-full border-0 shadow-none">
        <ArtifactHeader
          className="flex cursor-move items-start justify-between gap-3 px-3 py-2"
          data-testid={dataTestId ? `${dataTestId}-titlebar` : undefined}
          onMouseDown={handleTitleBarMouseDown}
        >
          <div className="min-w-0 flex-1">
            <ArtifactTitle>{title}</ArtifactTitle>
            {description && !minimized ? (
              <ArtifactDescription className="mt-1 text-xs">
                {description}
              </ArtifactDescription>
            ) : null}
          </div>
          <Button
            aria-label={toggleButtonLabel}
            onClick={onToggleMinimized}
            onMouseDown={(event) => {
              event.stopPropagation();
            }}
            size="icon"
            type="button"
            variant="ghost"
          >
            {minimized ? <PanelTopOpen /> : <Minus />}
          </Button>
        </ArtifactHeader>
        {!minimized ? (
          <ArtifactContent className={cn("min-h-0 flex-1 p-0", contentClassName)}>
            {children}
          </ArtifactContent>
        ) : null}
      </Artifact>
    </div>
  );
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}
