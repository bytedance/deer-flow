"use client";

import type { JSONContent } from "@tiptap/react";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  GridIcon,
  MaximizeIcon,
  MinimizeIcon,
  XIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { cn } from "@/lib/utils";

import DashboardEditorRaw from "./editor/dashboard-editor-raw";

interface PresentSlide {
  name: string;
  content: JSONContent;
}

interface PresentModeProps {
  slides: PresentSlide[];
  startIndex?: number;
  threadId?: string;
  onExit: () => void;
}

type TransitionDirection = "next" | "prev" | null;

export function PresentMode({
  slides,
  startIndex = 0,
  threadId,
  onExit,
}: PresentModeProps) {
  const [currentSlide, setCurrentSlide] = useState(startIndex);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showGrid, setShowGrid] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [transition, setTransition] = useState<TransitionDirection>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const totalSlides = slides.length;
  const progress = totalSlides > 1 ? ((currentSlide + 1) / totalSlides) * 100 : 100;

  const goToSlide = useCallback(
    (index: number, direction?: TransitionDirection) => {
      if (index < 0 || index >= totalSlides) return;
      setTransition(direction ?? (index > currentSlide ? "next" : "prev"));
      setTimeout(() => {
        setCurrentSlide(index);
        setTransition(null);
      }, 200);
    },
    [currentSlide, totalSlides],
  );

  const goNext = useCallback(() => {
    if (currentSlide < totalSlides - 1) goToSlide(currentSlide + 1, "next");
  }, [currentSlide, totalSlides, goToSlide]);

  const goPrev = useCallback(() => {
    if (currentSlide > 0) goToSlide(currentSlide - 1, "prev");
  }, [currentSlide, goToSlide]);

  // Fullscreen
  const toggleFullscreen = useCallback(async () => {
    if (!containerRef.current) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      setIsFullscreen(false);
    } else {
      await containerRef.current.requestFullscreen();
      setIsFullscreen(true);
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (showGrid) {
        if (e.key === "Escape") setShowGrid(false);
        return;
      }

      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
        case " ":
          e.preventDefault();
          goNext();
          break;
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          goPrev();
          break;
        case "Escape":
          onExit();
          break;
        case "Home":
          e.preventDefault();
          goToSlide(0, "prev");
          break;
        case "End":
          e.preventDefault();
          goToSlide(totalSlides - 1, "next");
          break;
        case "g":
          setShowGrid((prev) => !prev);
          break;
        case "f":
          void toggleFullscreen();
          break;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goNext, goPrev, goToSlide, onExit, showGrid, totalSlides, toggleFullscreen]);

  // Auto-hide controls
  const resetHideTimer = useCallback(() => {
    setShowControls(true);
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => setShowControls(false), 3000);
  }, []);

  useEffect(() => {
    resetHideTimer();
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, [resetHideTimer]);

  // Click navigation (left/right halves)
  const handleSlideClick = useCallback(
    (e: React.MouseEvent) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      if (x < rect.width / 3) {
        goPrev();
      } else if (x > (rect.width * 2) / 3) {
        goNext();
      }
      resetHideTimer();
    },
    [goNext, goPrev, resetHideTimer],
  );

  const slideContent = useMemo(() => slides[currentSlide]?.content, [slides, currentSlide]);

  if (showGrid) {
    return (
      <div
        ref={containerRef}
        className="fixed inset-0 z-[100] flex flex-col bg-black/95"
      >
        {/* Grid header */}
        <div className="flex h-14 shrink-0 items-center justify-between px-6">
          <h2 className="text-sm font-medium text-white/80">All Slides</h2>
          <button
            onClick={() => setShowGrid(false)}
            className="flex size-9 items-center justify-center rounded-xl text-white/60 transition-colors hover:bg-white/10 hover:text-white"
          >
            <XIcon className="size-5" />
          </button>
        </div>

        {/* Grid of slides */}
        <div className="flex-1 overflow-auto px-6 pb-6">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {slides.map((slide, i) => (
              <button
                key={i}
                onClick={() => {
                  goToSlide(i);
                  setShowGrid(false);
                }}
                className={cn(
                  "group relative flex flex-col overflow-hidden rounded-xl border-2 transition-all hover:scale-[1.02]",
                  i === currentSlide
                    ? "border-blue-500 shadow-lg shadow-blue-500/20"
                    : "border-white/10 hover:border-white/30",
                )}
              >
                {/* Slide preview */}
                <div className="aspect-[16/10] w-full overflow-hidden bg-white dark:bg-[oklch(0.24_0_0)]">
                  <div className="pointer-events-none origin-top-left scale-[0.25] [width:400%]">
                    <DashboardEditorRaw
                      content={slide.content}
                      readOnly
                    />
                  </div>
                </div>
                {/* Slide label */}
                <div className="flex items-center gap-2 bg-black/60 px-3 py-2">
                  <span className="text-xs font-medium text-white/50">
                    {i + 1}
                  </span>
                  <span className="truncate text-xs text-white/80">
                    {slide.name}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[100] flex flex-col bg-white dark:bg-[oklch(0.13_0_0)]"
      onMouseMove={resetHideTimer}
    >
      {/* Progress bar */}
      <div className="absolute top-0 right-0 left-0 z-20 h-1 bg-black/5 dark:bg-white/5">
        <div
          className="h-full bg-blue-500 transition-all duration-500 ease-out"
          style={{ width: `${String(progress)}%` }}
        />
      </div>

      {/* Slide content */}
      <div
        className="relative flex min-h-0 flex-1 cursor-pointer items-center justify-center"
        onClick={handleSlideClick}
      >
        {/* Transition wrapper */}
        <div
          className={cn(
            "size-full transition-all duration-200 ease-out",
            transition === "next" && "translate-x-[-20px] opacity-0",
            transition === "prev" && "translate-x-[20px] opacity-0",
            !transition && "translate-x-0 opacity-100",
          )}
        >
          <div className="mx-auto h-full max-w-[1200px] overflow-y-auto px-12 py-16">
            {slideContent && (
              <DashboardEditorRaw
                key={currentSlide}
                content={slideContent}
                readOnly
                threadId={threadId}
              />
            )}
          </div>
        </div>

        {/* Left/Right navigation arrows (edges) */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            goPrev();
          }}
          disabled={currentSlide === 0}
          className={cn(
            "absolute left-4 top-1/2 z-10 flex size-12 -translate-y-1/2 items-center justify-center rounded-full bg-black/5 text-foreground/60 backdrop-blur-sm transition-all dark:bg-white/5",
            showControls ? "opacity-100" : "opacity-0",
            currentSlide === 0
              ? "cursor-not-allowed opacity-20"
              : "hover:bg-black/10 hover:text-foreground dark:hover:bg-white/10",
          )}
        >
          <ChevronLeftIcon className="size-6" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            goNext();
          }}
          disabled={currentSlide === totalSlides - 1}
          className={cn(
            "absolute right-4 top-1/2 z-10 flex size-12 -translate-y-1/2 items-center justify-center rounded-full bg-black/5 text-foreground/60 backdrop-blur-sm transition-all dark:bg-white/5",
            showControls ? "opacity-100" : "opacity-0",
            currentSlide === totalSlides - 1
              ? "cursor-not-allowed opacity-20"
              : "hover:bg-black/10 hover:text-foreground dark:hover:bg-white/10",
          )}
        >
          <ChevronRightIcon className="size-6" />
        </button>
      </div>

      {/* Bottom controls bar */}
      <div
        className={cn(
          "absolute right-0 bottom-0 left-0 z-20 flex h-14 items-center justify-between px-6 transition-opacity duration-300",
          showControls ? "opacity-100" : "opacity-0",
        )}
      >
        {/* Slide counter */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-foreground/70">
            {currentSlide + 1}
            <span className="text-foreground/30"> / {totalSlides}</span>
          </span>
        </div>

        {/* Center: slide dots */}
        {totalSlides <= 20 && (
          <div className="flex items-center gap-1.5">
            {slides.map((_, i) => (
              <button
                key={i}
                onClick={() => goToSlide(i)}
                className={cn(
                  "rounded-full transition-all",
                  i === currentSlide
                    ? "h-2 w-6 bg-blue-500"
                    : "size-2 bg-foreground/20 hover:bg-foreground/40",
                )}
              />
            ))}
          </div>
        )}

        {/* Right controls */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowGrid(true)}
            className="flex size-9 items-center justify-center rounded-xl text-foreground/50 transition-colors hover:bg-black/5 hover:text-foreground dark:hover:bg-white/5"
            title="Grid view (G)"
          >
            <GridIcon className="size-4" />
          </button>
          <button
            onClick={() => void toggleFullscreen()}
            className="flex size-9 items-center justify-center rounded-xl text-foreground/50 transition-colors hover:bg-black/5 hover:text-foreground dark:hover:bg-white/5"
            title="Fullscreen (F)"
          >
            {isFullscreen ? (
              <MinimizeIcon className="size-4" />
            ) : (
              <MaximizeIcon className="size-4" />
            )}
          </button>
          <button
            onClick={onExit}
            className="flex size-9 items-center justify-center rounded-xl text-foreground/50 transition-colors hover:bg-black/5 hover:text-foreground dark:hover:bg-white/5"
            title="Exit (Esc)"
          >
            <XIcon className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
