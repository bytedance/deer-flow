"use client";

import {
    ChevronLeftIcon,
    ChevronRightIcon,
    DownloadIcon,
    MaximizeIcon,
    MinimizeIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SlideData {
    index: number;
    slide: string;
}

export interface PresentationData {
    title: string;
    theme: {
        bgColor?: string;
        textColor?: string;
        secondaryColor?: string;
        titleFont?: string;
        bodyFont?: string;
    };
    slides: SlideData[];
}

interface PresentationWorkspaceProps {
    className?: string;
    presentation?: PresentationData | null;
    threadId?: string;
}

function buildSlideDoc(html: string, theme: PresentationData["theme"]): string {
    return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 100%; height: 100%;
    overflow: hidden;
    font-family: '${theme.bodyFont || "Inter"}', sans-serif;
    background: ${theme.bgColor || "#ffffff"};
    color: ${theme.textColor || "#000000"};
  }
  body { display: flex; align-items: center; justify-content: center; padding: 40px 60px; }
  h1, h2, h3 { font-family: '${theme.titleFont || "Inter"}', sans-serif; margin-bottom: 0.5em; }
  h1 { font-size: 2.5em; font-weight: 800; }
  h2 { font-size: 1.8em; font-weight: 700; }
  h3 { font-size: 1.3em; font-weight: 600; }
  p { font-size: 1.05em; line-height: 1.6; margin-bottom: 0.6em; }
  ul, ol { padding-left: 1.5em; margin-bottom: 0.8em; }
  li { margin-bottom: 0.3em; }
  li p { margin-bottom: 0; }
  a { color: ${theme.secondaryColor || "#3b82f6"}; }
  strong { font-weight: 700; }
  code { background: rgba(127,127,127,0.15); padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.9em; }
  img { max-width: 100%; height: auto; border-radius: 8px; }
  row { display: flex; gap: 24px; width: 100%; align-items: flex-start; }
  column { flex: 1; min-width: 0; }
  slide-settings { display: none; }
  chart { display: block; width: 100%; min-height: 200px; background: rgba(127,127,127,0.08); border-radius: 8px; padding: 16px; text-align: center; color: #888; }
  chart::after { content: "Chart"; font-size: 14px; }
  [data-pill] {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    background: ${theme.secondaryColor || "#3b82f6"}22;
    color: ${theme.secondaryColor || "#3b82f6"};
    font-size: 0.85em; font-weight: 500;
  }
</style>
</head>
<body>${html}</body>
</html>`;
}

export function PresentationWorkspace({
    className,
    presentation,
    threadId,
}: PresentationWorkspaceProps) {
    const [currentSlide, setCurrentSlide] = useState(0);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const slides = useMemo(() => presentation?.slides ?? [], [presentation]);
    const theme = useMemo(
        () => presentation?.theme ?? {},
        [presentation],
    );

    const totalSlides = slides.length;

    const goToSlide = useCallback(
        (index: number) => {
            if (index >= 0 && index < totalSlides) {
                setCurrentSlide(index);
            }
        },
        [totalSlides],
    );

    const nextSlide = useCallback(() => goToSlide(currentSlide + 1), [currentSlide, goToSlide]);
    const prevSlide = useCallback(() => goToSlide(currentSlide - 1), [currentSlide, goToSlide]);

    // Keyboard navigation — skip when user is typing in an input
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            const tag = (e.target as HTMLElement)?.tagName;
            const editable = (e.target as HTMLElement)?.isContentEditable;
            if (tag === "INPUT" || tag === "TEXTAREA" || editable) return;

            if (e.key === "ArrowRight" || e.key === " ") {
                e.preventDefault();
                nextSlide();
            } else if (e.key === "ArrowLeft") {
                e.preventDefault();
                prevSlide();
            } else if (e.key === "Escape" && isFullscreen) {
                setIsFullscreen(false);
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, [nextSlide, prevSlide, isFullscreen]);

    // Reset to first slide when presentation changes
    useEffect(() => {
        setCurrentSlide(0);
    }, [presentation]);

    const toggleFullscreen = useCallback(() => {
        if (!isFullscreen) {
            containerRef.current?.requestFullscreen?.();
        } else {
            document.exitFullscreen?.();
        }
        setIsFullscreen(!isFullscreen);
    }, [isFullscreen]);

    if (!presentation || totalSlides === 0) {
        return (
            <div
                className={cn(
                    "flex size-full flex-col items-center justify-center gap-3 text-muted-foreground",
                    className,
                )}
            >
                <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
                    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="2" y="3" width="20" height="14" rx="2" />
                        <path d="M8 21h8" />
                        <path d="M12 17v4" />
                    </svg>
                </div>
                <p className="text-sm">Presentation will appear here</p>
                <p className="text-xs text-muted-foreground/60">Ask the AI to create a presentation</p>
            </div>
        );
    }

    const currentSlideData = slides[currentSlide];
    const slideDoc = currentSlideData
        ? buildSlideDoc(currentSlideData.slide, theme)
        : "";

    return (
        <div
            ref={containerRef}
            className={cn(
                "flex size-full flex-col bg-background",
                isFullscreen && "fixed inset-0 z-50",
                className,
            )}
        >
            {/* Header */}
            <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
                <div className="flex items-center gap-2">
                    <h2 className="text-sm font-medium truncate max-w-[200px]">
                        {presentation.title}
                    </h2>
                    <span className="text-xs text-muted-foreground">
                        {currentSlide + 1} / {totalSlides}
                    </span>
                </div>
                <div className="flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        onClick={toggleFullscreen}
                    >
                        {isFullscreen ? (
                            <MinimizeIcon className="size-4" />
                        ) : (
                            <MaximizeIcon className="size-4" />
                        )}
                    </Button>
                </div>
            </div>

            {/* Main Slide Area */}
            <div className="relative flex min-h-0 flex-1 items-center justify-center p-6">
                {/* Prev Button */}
                <Button
                    variant="ghost"
                    size="icon"
                    className="absolute left-2 z-10 size-10 rounded-full bg-background/80 shadow-sm backdrop-blur"
                    disabled={currentSlide === 0}
                    onClick={prevSlide}
                >
                    <ChevronLeftIcon className="size-5" />
                </Button>

                {/* Slide iframe */}
                <div className="relative w-full max-w-4xl overflow-hidden rounded-xl border shadow-lg" style={{ aspectRatio: "16/9" }}>
                    <iframe
                        className="size-full"
                        title={`Slide ${currentSlide + 1}`}
                        srcDoc={slideDoc}
                        sandbox="allow-same-origin"
                        style={{ border: "none" }}
                    />
                </div>

                {/* Next Button */}
                <Button
                    variant="ghost"
                    size="icon"
                    className="absolute right-2 z-10 size-10 rounded-full bg-background/80 shadow-sm backdrop-blur"
                    disabled={currentSlide === totalSlides - 1}
                    onClick={nextSlide}
                >
                    <ChevronRightIcon className="size-5" />
                </Button>
            </div>

            {/* Thumbnail Strip */}
            <div className="flex shrink-0 gap-2 overflow-x-auto border-t p-3">
                {slides.map((slide, i) => (
                    <button
                        key={slide.index}
                        className={cn(
                            "relative shrink-0 overflow-hidden rounded-lg border-2 transition-all",
                            i === currentSlide
                                ? "border-primary shadow-md"
                                : "border-transparent opacity-60 hover:opacity-90",
                        )}
                        style={{ width: 120, aspectRatio: "16/9" }}
                        onClick={() => goToSlide(i)}
                    >
                        <iframe
                            className="pointer-events-none size-full"
                            title={`Thumbnail ${i + 1}`}
                            srcDoc={buildSlideDoc(slide.slide, theme)}
                            sandbox=""
                            tabIndex={-1}
                            style={{
                                border: "none",
                                transform: "scale(0.15)",
                                transformOrigin: "top left",
                                width: "667%",
                                height: "667%",
                            }}
                        />
                        <div className="absolute bottom-0 left-0 right-0 bg-black/40 px-1 py-0.5 text-center text-[9px] font-medium text-white">
                            {i + 1}
                        </div>
                    </button>
                ))}
            </div>
        </div>
    );
}
