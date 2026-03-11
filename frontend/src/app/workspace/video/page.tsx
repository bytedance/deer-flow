"use client";

import {
  ChevronDownIcon,
  PlusIcon,
  SendIcon,
  VideoIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

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

// --- Inspiration categories ---

const INSPIRATION_CATEGORIES = [
  "Featured",
  "Finance and Investments",
  "Project and Event Management",
  "Data analysis",
  "Personal Productivity",
  "Education & Training",
] as const;

interface Inspiration {
  id: string;
  title: string;
  prompt: string;
  category: string;
  gradient: string;
}

const INSPIRATIONS: Inspiration[] = [
  { id: "1", title: "Product Launch Trailer", prompt: "Create a cinematic product launch video with dramatic reveals, particle effects, and bold typography for a tech product", category: "Featured", gradient: "from-violet-500 to-purple-600" },
  { id: "2", title: "Startup Pitch Deck Video", prompt: "Create a startup pitch deck video with animated statistics, market opportunity graphs, and team introduction slides", category: "Featured", gradient: "from-blue-500 to-cyan-500" },
  { id: "3", title: "Social Media Promo", prompt: "Create a fast-paced social media promotional video with trendy transitions, bold text overlays, and engaging visuals for Instagram Reels", category: "Featured", gradient: "from-pink-500 to-rose-500" },
  { id: "4", title: "Brand Story", prompt: "Create a brand story video that showcases company values, mission, and vision with cinematic footage and emotional storytelling", category: "Featured", gradient: "from-amber-500 to-orange-500" },
  { id: "5", title: "Explainer Animation", prompt: "Create an animated explainer video that breaks down a complex concept into simple visuals with smooth transitions and clear narration", category: "Featured", gradient: "from-emerald-500 to-teal-500" },
  { id: "6", title: "Event Highlight Reel", prompt: "Create a dynamic event highlight reel with fast cuts, energetic music, and key moment captures", category: "Featured", gradient: "from-red-500 to-pink-500" },
  { id: "7", title: "Financial Report Video", prompt: "Create a financial quarterly report video with animated charts, key metrics highlights, and executive commentary", category: "Finance and Investments", gradient: "from-green-500 to-emerald-500" },
  { id: "8", title: "Investment Portfolio Review", prompt: "Create a portfolio performance review video with market trends, asset allocation visuals, and ROI metrics", category: "Finance and Investments", gradient: "from-blue-600 to-indigo-600" },
  { id: "9", title: "Project Status Update", prompt: "Create a project status update video with timeline progress, milestone achievements, and team contributions", category: "Project and Event Management", gradient: "from-purple-500 to-violet-500" },
  { id: "10", title: "Data Visualization Story", prompt: "Create a data-driven storytelling video that transforms raw data into compelling visual narratives with animated charts", category: "Data analysis", gradient: "from-cyan-500 to-blue-500" },
  { id: "11", title: "Productivity Tips", prompt: "Create a productivity tips video with animated demonstrations of workflows, tool recommendations, and time management techniques", category: "Personal Productivity", gradient: "from-yellow-500 to-amber-500" },
  { id: "12", title: "Online Course Intro", prompt: "Create an engaging course introduction video with curriculum overview, learning objectives, and instructor introduction", category: "Education & Training", gradient: "from-indigo-500 to-purple-500" },
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

export default function VideoHomePage() {
  const { t } = useI18n();
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [selectedModel, setSelectedModel] = useState<VideoModel>(VIDEO_MODELS[0]!);
  const [selectedRatio, setSelectedRatio] = useState("16:9");
  const [activeCategory, setActiveCategory] = useState<string>("Featured");
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
    () => INSPIRATIONS.filter((i) => i.category === activeCategory),
    [activeCategory],
  );

  const handleSubmit = useCallback(
    (text?: string) => {
      const msg = text ?? prompt;
      if (!msg.trim()) return;
      sessionStorage.setItem("video-initial-prompt", msg);
      sessionStorage.setItem("video-model", selectedModel.id);
      sessionStorage.setItem("video-aspect-ratio", selectedRatio);
      router.push("/workspace/video/new");
    },
    [prompt, router, selectedModel, selectedRatio],
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-auto font-[family-name:var(--font-google-sans-flex)]">
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
              <div className="overflow-hidden rounded-3xl border bg-white p-3 shadow-sm dark:bg-[oklch(0.2_0_0)]">
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

          {/* Inspirations */}
          <section className="flex-1 px-6 pb-12">
            <div className="mx-auto max-w-6xl">
              <h2 className="pb-4 text-xl font-medium tracking-[0.4px]">Inspirations</h2>

              {/* Category tabs */}
              <div className="flex flex-wrap gap-2 pb-5">
                {INSPIRATION_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    className={cn(
                      "rounded-xl px-3 py-1.5 text-sm font-medium transition-colors",
                      activeCategory === cat
                        ? "bg-muted text-foreground"
                        : "border text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => setActiveCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Inspiration grid */}
              <ScrollArea className="w-full">
                <div className="grid grid-cols-2 gap-2 pb-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
                  {/* Create blank card */}
                  <button
                    onClick={() => handleSubmit("Create a blank video project")}
                    className="flex aspect-[16/10] flex-col items-center justify-center gap-2 rounded-xl border-[1.5px] border-dashed text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                  >
                    <PlusIcon className="size-4" />
                    <span className="text-sm font-medium">Create blank</span>
                  </button>

                  {/* Inspiration cards */}
                  {filteredInspirations.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => handleSubmit(item.prompt)}
                      className="group relative aspect-[16/10] overflow-hidden rounded-xl border-[1.5px]"
                    >
                      <div className={cn("absolute inset-0 bg-gradient-to-br", item.gradient)} />
                      <div className="absolute inset-0 bg-black/20 opacity-0 transition-opacity group-hover:opacity-100" />
                      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-3">
                        <p className="text-left text-xs font-medium text-white">{item.title}</p>
                      </div>
                    </button>
                  ))}

                  {filteredInspirations.length === 0 && (
                    <div className="col-span-full flex h-32 items-center justify-center text-sm text-muted-foreground">
                      No inspirations in this category yet
                    </div>
                  )}
                </div>
                <ScrollBar orientation="vertical" />
              </ScrollArea>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
