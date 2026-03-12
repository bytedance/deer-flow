"use client";

import {
  ChevronDownIcon,
  ClockIcon,
  PlusIcon,
  SendIcon,
  VideoIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/hooks";
import { cn } from "@/lib/utils";

import {
  INSPIRATION_CATEGORIES,
  VIDEO_INSPIRATIONS,
} from "./inspirations";

// --- Video model definitions ---

interface VideoModel {
  id: string;
  name: string;
  icon: string;
  aspectRatios: string[];
}

const VIDEO_MODELS: VideoModel[] = [
  { id: "veo3", name: "VEO 3", icon: "G", aspectRatios: ["16:9", "9:16"] },
  { id: "kling3", name: "KLING 3", icon: "K", aspectRatios: ["16:9", "9:16", "1:1"] },
  { id: "sora2", name: "Sora 2", icon: "S", aspectRatios: ["16:9", "9:16", "1:1"] },
  { id: "grok-video", name: "Grok Video", icon: "X", aspectRatios: ["16:9", "9:16"] },
];

// --- Model icon component ---
function ModelIcon({ model }: { model: VideoModel }) {
  const colors: Record<string, string> = {
    veo3: "bg-blue-500 text-white",
    kling3: "bg-black text-white dark:bg-white dark:text-black",
    sora2: "bg-gradient-to-br from-pink-500 to-violet-500 text-white",
    "grok-video": "bg-black text-white dark:bg-white dark:text-black",
  };
  return (
    <div className={cn("flex size-5 items-center justify-center rounded text-[10px] font-bold", colors[model.id])}>
      {model.icon}
    </div>
  );
}

// --- Aspect ratio icon ---
function AspectRatioIcon({ ratio }: { ratio: string }) {
  const dims: Record<string, { w: number; h: number }> = {
    "16:9": { w: 14, h: 8 },
    "9:16": { w: 8, h: 14 },
    "1:1": { w: 10, h: 10 },
  };
  const d = dims[ratio] ?? { w: 10, h: 10 };
  return (
    <div
      className="rounded-[2px] border-[1.5px] border-current"
      style={{ width: d.w, height: d.h }}
    />
  );
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// --- Video inspiration card with hover-to-play ---
function InspirationCard({
  item,
  onSelect,
}: {
  item: (typeof VIDEO_INSPIRATIONS)[number];
  onSelect: (prompt: string, thumbnailUrl?: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseEnter = () => {
    setIsHovered(true);
    void videoRef.current?.play();
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.currentTime = 0;
    }
  };

  return (
    <button
      onClick={() => onSelect(item.prompt, `/video/thumbnails/${item.thumbnail}`)}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="group relative mb-2.5 w-full overflow-hidden rounded-[8px]"
    >
      {/* Poster image — natural dimensions, fills width, no forced aspect ratio */}
      <img
        src={`/video/thumbnails/${item.thumbnail}`}
        alt={item.title}
        className="block w-full"
        loading="lazy"
      />

      {/* Video (plays on hover, covers the thumbnail exactly) */}
      <video
        ref={videoRef}
        src={`/video/${item.filename}`}
        poster={`/video/thumbnails/${item.thumbnail}`}
        muted
        loop
        playsInline
        preload="none"
        className={cn(
          "absolute inset-0 size-full object-cover transition-opacity duration-300",
          isHovered ? "opacity-100" : "opacity-0",
        )}
      />

      {/* Bottom gradient overlay with title */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent px-3 pt-8 pb-3">
        <p className="text-left text-[12px] font-medium leading-[16px] text-white drop-shadow-sm">
          {item.title}
        </p>
      </div>
    </button>
  );
}

export default function VideoHomePage() {
  const { t } = useI18n();
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const { data: recentThreads } = useThreads({
    limit: 8,
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values"],
  });
  const [selectedModel, setSelectedModel] = useState<VideoModel>(VIDEO_MODELS[0]!);
  const [selectedRatio, setSelectedRatio] = useState("16:9");
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [ratioMenuOpen, setRatioMenuOpen] = useState(false);
  const modelBtnRef = useRef<HTMLButtonElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const ratioBtnRef = useRef<HTMLButtonElement>(null);
  const ratioMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = `AI Video - ${t.pages.appName}`;
  }, [t.pages.appName]);

  // Close dropdowns on outside click
  useEffect(() => {
    if (!modelMenuOpen && !ratioMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (modelMenuOpen && modelMenuRef.current && !modelMenuRef.current.contains(e.target as Node) && modelBtnRef.current && !modelBtnRef.current.contains(e.target as Node)) {
        setModelMenuOpen(false);
      }
      if (ratioMenuOpen && ratioMenuRef.current && !ratioMenuRef.current.contains(e.target as Node) && ratioBtnRef.current && !ratioBtnRef.current.contains(e.target as Node)) {
        setRatioMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [modelMenuOpen, ratioMenuOpen]);

  // Reset aspect ratio when model changes
  useEffect(() => {
    if (!selectedModel.aspectRatios.includes(selectedRatio)) {
      setSelectedRatio(selectedModel.aspectRatios[0]!);
    }
  }, [selectedModel, selectedRatio]);

  const filteredInspirations = useMemo(
    () => VIDEO_INSPIRATIONS.filter((i) => i.categories.includes(activeCategory)),
    [activeCategory],
  );

  const handleSubmit = useCallback(
    (text?: string, thumbnailUrl?: string) => {
      const msg = text ?? prompt;
      if (!msg.trim()) return;
      sessionStorage.setItem("video-initial-prompt", msg);
      sessionStorage.setItem("video-model", selectedModel.id);
      sessionStorage.setItem("video-aspect-ratio", selectedRatio);
      if (thumbnailUrl) {
        sessionStorage.setItem("video-reference-image", thumbnailUrl);
      }
      router.push("/workspace/video/new");
    },
    [prompt, router, selectedModel, selectedRatio],
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-auto">
          {/* Hero + Prompt */}
          <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6 pt-16 pb-8">
            <div className="flex items-center gap-3">
              <div className="flex size-7 items-center justify-center rounded-lg bg-blue-500 text-white">
                <VideoIcon className="size-4" />
              </div>
              <h1 className="text-[28px] font-normal tracking-[0.3px] text-foreground">
                What video you would want to create?
              </h1>
            </div>

            {/* Prompt Box */}
            <div className="mt-6 w-full max-w-[768px]">
              <div className="rounded-3xl border bg-white p-3 shadow-sm dark:bg-[oklch(0.2_0_0)]">
                <div className="px-1 py-1">
                  <input
                    className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground/50"
                    placeholder="Ask anything ..."
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleSubmit();
                      }
                    }}
                  />
                </div>

                {/* Action bar */}
                <div className="flex items-center gap-2 pt-3">
                  <button className="flex size-8 items-center justify-center rounded-full bg-muted text-muted-foreground transition-colors hover:bg-muted/80">
                    <PlusIcon className="size-4" />
                  </button>

                  {/* Model selector */}
                  <div className="relative">
                    <button
                      ref={modelBtnRef}
                      onClick={() => { setModelMenuOpen((v) => !v); setRatioMenuOpen(false); }}
                      className="flex h-9 items-center gap-2 rounded-full bg-muted px-3 text-sm font-medium transition-colors hover:bg-muted/80"
                    >
                      <ModelIcon model={selectedModel} />
                      {selectedModel.name}
                      <ChevronDownIcon className="size-3.5 text-muted-foreground" />
                    </button>
                    {modelMenuOpen && (
                      <div ref={modelMenuRef} className="absolute left-0 z-50 mt-1.5 w-48 overflow-hidden rounded-xl border bg-popover shadow-lg">
                        {VIDEO_MODELS.map((model) => (
                          <button
                            key={model.id}
                            onClick={() => { setSelectedModel(model); setModelMenuOpen(false); }}
                            className={cn(
                              "flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors hover:bg-muted",
                              model.id === selectedModel.id && "bg-muted font-medium",
                            )}
                          >
                            <ModelIcon model={model} />
                            {model.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Aspect ratio selector */}
                  <div className="relative">
                    <button
                      ref={ratioBtnRef}
                      onClick={() => { setRatioMenuOpen((v) => !v); setModelMenuOpen(false); }}
                      className="flex h-9 items-center gap-2 rounded-full bg-muted px-3 text-sm font-medium transition-colors hover:bg-muted/80"
                    >
                      <AspectRatioIcon ratio={selectedRatio} />
                      {selectedRatio}
                      <ChevronDownIcon className="size-3.5 text-muted-foreground" />
                    </button>
                    {ratioMenuOpen && (
                      <div ref={ratioMenuRef} className="absolute left-0 z-50 mt-1.5 w-36 overflow-hidden rounded-xl border bg-popover shadow-lg">
                        {selectedModel.aspectRatios.map((ratio) => (
                          <button
                            key={ratio}
                            onClick={() => { setSelectedRatio(ratio); setRatioMenuOpen(false); }}
                            className={cn(
                              "flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors hover:bg-muted",
                              ratio === selectedRatio && "bg-muted font-medium",
                            )}
                          >
                            <AspectRatioIcon ratio={ratio} />
                            {ratio}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex-1" />

                  {/* Submit */}
                  <button
                    onClick={() => handleSubmit()}
                    disabled={!prompt.trim()}
                    className="flex size-8 items-center justify-center rounded-full bg-foreground text-background transition-colors hover:opacity-90 disabled:opacity-30"
                  >
                    <SendIcon className="size-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Recent Threads */}
          {recentThreads && recentThreads.length > 0 && (
            <section className="px-6 pb-6">
              <div className="mx-auto max-w-6xl">
                <div className="flex items-center gap-2 pb-4">
                  <ClockIcon className="size-4 text-muted-foreground" />
                  <h2 className="text-[20px] font-medium leading-[28px] tracking-[0.4px]">Recent</h2>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {recentThreads.slice(0, 8).map((thread) => (
                    <Link
                      key={thread.thread_id}
                      href={`/workspace/video/${thread.thread_id}`}
                      className="group flex flex-col gap-2 rounded-xl border p-3 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex items-center gap-2">
                        <VideoIcon className="size-3.5 shrink-0 text-blue-500" />
                        <span className="truncate text-sm font-medium">
                          {thread.values?.title || "Untitled"}
                        </span>
                      </div>
                      <span className="text-[10px] text-muted-foreground">
                        {formatTimeAgo(new Date(thread.updated_at))}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* Inspirations */}
          <section className="flex-1 px-6 pb-12">
            <div className="mx-auto max-w-6xl">
              <h2 className="pb-4 text-[20px] font-medium leading-[28px] tracking-[0.4px]">Inspirations</h2>

              {/* Category tabs - Figma: filled for active (#ededed), outlined for inactive (border #e0e0e0), 12px rounded, 14px Medium */}
              <div className="flex flex-wrap gap-2 pb-5">
                {INSPIRATION_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    className={cn(
                      "rounded-[12px] px-3.5 py-1.5 text-[14px] font-medium leading-[20px] transition-colors",
                      activeCategory === cat
                        ? "bg-[#ededed] text-[#0f0f0f] dark:bg-[#333] dark:text-white"
                        : "border border-[#e0e0e0] text-[#525252] hover:text-[#0f0f0f] dark:border-[#444] dark:text-[#999] dark:hover:text-white",
                    )}
                    onClick={() => setActiveCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Masonry inspiration grid using CSS columns */}
              <div
                className="max-h-[700px] overflow-hidden"
                style={{ columnCount: 6, columnGap: "10px" }}
              >
                {/* Create blank card */}
                <button
                  onClick={() => handleSubmit("Create a blank video project")}
                  className="mb-2.5 flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-[8px] border-[1.5px] border-dashed border-[#ededed] bg-[#f7f7f7] text-[#525252] transition-colors hover:border-[#e0e0e0] hover:text-[#0f0f0f] dark:border-[#333] dark:bg-[#1a1a1a] dark:text-[#999] dark:hover:border-[#444] dark:hover:text-white"
                  style={{ breakInside: "avoid" }}
                >
                  <div className="flex size-10 items-center justify-center rounded-full border border-current">
                    <PlusIcon className="size-5" />
                  </div>
                  <span className="text-[13px] font-medium">Create blank</span>
                </button>

                {/* Inspiration video cards */}
                {filteredInspirations.map((item) => (
                  <div key={item.id} style={{ breakInside: "avoid" }}>
                    <InspirationCard
                      item={item}
                      onSelect={handleSubmit}
                    />
                  </div>
                ))}

                {filteredInspirations.length === 0 && (
                  <div className="flex h-32 w-full items-center justify-center text-sm text-[#525252]">
                    No inspirations in this category yet
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
