"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";

import { cn } from "@/lib/utils";

import type { VisualizeProgressState } from "../runtime/utils";
import { Viewer } from "../runtime/Viewer";

import { VisualizeProgress } from "./VisualizeProgress";

type VisualizeViewerProps = {
  className?: string;
  onError?: (error: unknown) => void;
  onProgress?: (progress: VisualizeProgressState) => void;
  onReady?: (viewer: Viewer) => void;
};

export function VisualizeViewer({
  className,
  onError,
  onProgress,
  onReady,
}: VisualizeViewerProps) {
  const { resolvedTheme } = useTheme();
  const viewerRootRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLCanvasElement | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [progress, setProgress] = useState(0);
  const [viewerInstance, setViewerInstance] = useState<Viewer | null>(null);

  useEffect(() => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    let active = true;
    const viewer = new Viewer({ container });

    const initialize = async () => {
      try {
        await viewer.initialize({
          onProgress: (nextProgress) => {
            if (!active) {
              return;
            }
            setProgress(nextProgress.percent);
            onProgress?.(nextProgress);
          },
        });

        if (!active) {
          return;
        }

        setProgress(100);

        await new Promise<void>((resolve) => {
          window.requestAnimationFrame(() => {
            resolve();
          });
        });

        if (!active) {
          return;
        }

        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, 150);
        });

        if (!active) {
          return;
        }

        setIsLoading(false);
        setViewerInstance(viewer);
        onReady?.(viewer);
      }
      catch (error) {
        if (!active) {
          return;
        }
        setIsLoading(false);
        setViewerInstance(null);
        onError?.(error);
      }
    };

    void initialize();

    return () => {
      active = false;
      setViewerInstance(null);
      window.setTimeout(() => {
        viewer.dispose();
      }, 0);
    };
  }, [onError, onProgress, onReady]);

  useEffect(() => {
    if (!viewerInstance || !viewerRootRef.current) {
      return;
    }

    const applyBackgroundColor = () => {
      viewerInstance.setBackgroundColor(resolveViewerBackgroundColor(resolvedTheme));
    };

    applyBackgroundColor();

    const disposeOpenListener = viewerInstance.on("open", () => {
      applyBackgroundColor();
    });
    const disposeGeometryEndListener = viewerInstance.on("geometryend", () => {
      applyBackgroundColor();
    });

    return () => {
      disposeOpenListener();
      disposeGeometryEndListener();
    };
  }, [resolvedTheme, viewerInstance]);

  return (
    <div
      className={cn("bg-background relative h-full min-h-64 w-full overflow-hidden", className)}
      data-testid="vsfx-visualize-viewer"
      ref={viewerRootRef}
    >
      <canvas className="h-full w-full" data-testid="vsfx-canvas" id="canvas" ref={containerRef} />
      <VisualizeProgress loading={isLoading} value={progress} />
    </div>
  );
}

function resolveViewerBackgroundColor(theme: string | undefined) {
  if (theme === "dark") {
    return 0x18181b;
  }

  return 0xffffff;
}
