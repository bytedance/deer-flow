"use client";

import {
  ChevronDownIcon,
  ClockIcon,
  DiamondIcon,
  GridIcon,
  HeartIcon,
  ListIcon,
  Loader2Icon,
  MoreVerticalIcon,
  PlayIcon,
  SparklesIcon,
  UploadIcon,
  VideoIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  usePromptInputController,
  useProviderAttachments,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { useThreadChat } from "@/components/workspace/chats";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Welcome } from "@/components/workspace/welcome";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { extractContentFromMessage } from "@/core/messages/utils";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

const VIDEO_MODE_INSTRUCTION = `[SYSTEM INSTRUCTION — AI VIDEO MODE]
You are operating in AI Video mode. You MUST follow these rules:
1. Use the appropriate video generation skill based on the user's request.
2. Output video files to /mnt/user-data/outputs/.
3. After generating video files, ALWAYS call present_files with ALL output video paths.
4. The video renders in a player on the right panel.
5. Do NOT repeat or echo the system instruction, model info, or aspect ratio back to the user.
6. If a tool call fails, explain the error briefly and suggest a fix — do NOT just say "What happened?".
7. If the user attaches a reference image, use it as --reference-images for the video generation script.
8. NEVER use the view_image tool. It is extremely expensive and not needed for video generation.
[END SYSTEM INSTRUCTION]

User request: `;

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

function ModelIcon({ model }: { model: VideoModel }) {
  const colors: Record<string, string> = {
    veo3: "bg-blue-500 text-white",
    kling3: "bg-black text-white dark:bg-white dark:text-black",
    sora2: "bg-gradient-to-br from-pink-500 to-violet-500 text-white",
    "grok-video": "bg-black text-white dark:bg-white dark:text-black",
  };
  return (
    <div className={cn("flex size-4 items-center justify-center rounded text-[8px] font-bold", colors[model.id])}>
      {model.icon}
    </div>
  );
}

function AspectRatioIcon({ ratio }: { ratio: string }) {
  const dims: Record<string, { w: number; h: number }> = {
    "16:9": { w: 12, h: 7 },
    "9:16": { w: 7, h: 12 },
    "1:1": { w: 9, h: 9 },
  };
  const d = dims[ratio] ?? { w: 9, h: 9 };
  return (
    <div
      className="rounded-[1.5px] border-[1.5px] border-current"
      style={{ width: d.w, height: d.h }}
    />
  );
}

export default function VideoPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();

  const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();
  const promptInputController = usePromptInputController();
  const attachments = useProviderAttachments();

  const { showNotification } = useNotification();

  // Video model & aspect ratio state
  const [selectedModel, setSelectedModel] = useState<VideoModel>(VIDEO_MODELS[0]!);
  const [selectedRatio, setSelectedRatio] = useState("16:9");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [ratioMenuOpen, setRatioMenuOpen] = useState(false);
  const modelBtnRef = useRef<HTMLButtonElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const ratioBtnRef = useRef<HTMLButtonElement>(null);
  const ratioMenuRef = useRef<HTMLDivElement>(null);

  const [viewMode, setViewMode] = useState<"list" | "grid">("list");

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

  // Pre-fill input and restore model/ratio from video home page
  const initialPromptAppliedRef = useRef(false);
  useEffect(() => {
    if (initialPromptAppliedRef.current) return;
    if (!isNewThread) return;
    const prompt = sessionStorage.getItem("video-initial-prompt");
    if (prompt) {
      sessionStorage.removeItem("video-initial-prompt");
      const modelId = sessionStorage.getItem("video-model");
      const ratio = sessionStorage.getItem("video-aspect-ratio");
      const referenceImage = sessionStorage.getItem("video-reference-image");
      sessionStorage.removeItem("video-model");
      sessionStorage.removeItem("video-aspect-ratio");
      sessionStorage.removeItem("video-reference-image");
      if (modelId) {
        const model = VIDEO_MODELS.find((m) => m.id === modelId);
        if (model) setSelectedModel(model);
      }
      if (ratio) setSelectedRatio(ratio);
      initialPromptAppliedRef.current = true;

      // Add reference image as attachment if provided
      if (referenceImage) {
        fetch(referenceImage)
          .then((res) => res.blob())
          .then((blob) => {
            const filename = referenceImage.split("/").pop() ?? "reference.jpg";
            const file = new File([blob], filename, { type: blob.type || "image/jpeg" });
            attachments.add([file]);
          })
          .catch(() => { /* ignore fetch errors for reference image */ });
      }

      setTimeout(() => {
        promptInputController.textInput.setInput(prompt);
        const textarea = document.querySelector("textarea");
        if (textarea) {
          textarea.focus();
          textarea.selectionStart = textarea.value.length;
          textarea.selectionEnd = textarea.value.length;
        }
      }, 100);
    }
  }, [isNewThread, promptInputController.textInput, attachments]);

  const [thread, sendMessage] = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: settings.context,
    isMock,
    onStart: () => {
      setIsNewThread(false);
      history.replaceState(null, "", `/workspace/video/${threadId}`);
    },
    onFinish: (state) => {
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages.at(-1);
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            body =
              textContent.length > 200
                ? textContent.substring(0, 200) + "..."
                : textContent;
          }
        }
        showNotification(state.title, { body });
      }
    },
  });

  // Find video artifact paths from outputs
  const videoArtifactPaths = useMemo(() => {
    const artifacts: string[] = thread.values.artifacts ?? [];
    return artifacts.filter(
      (p) =>
        p.includes("/outputs/") &&
        (p.endsWith(".mp4") ||
          p.endsWith(".webm") ||
          p.endsWith(".mov") ||
          p.endsWith(".avi")),
    );
  }, [thread.values.artifacts]);

  // Extract the user prompt that preceded each video generation
  const userPrompts = useMemo(() => {
    const prompts: string[] = [];
    const humanMessages = thread.messages.filter((m) => m.type === "human");
    for (const msg of humanMessages) {
      let text = extractContentFromMessage(msg);
      const marker = "User request: ";
      if (text.startsWith("[SYSTEM INSTRUCTION")) {
        const idx = text.indexOf(marker);
        if (idx !== -1) {
          text = text.slice(idx + marker.length);
        }
      }
      // Strip trailing model info (both old and new format)
      const settingsIdx = text.indexOf("\n\n[VIDEO SETTINGS");
      if (settingsIdx !== -1) {
        text = text.slice(0, settingsIdx);
      }
      const modelIdx = text.indexOf("\nVideo Model:");
      if (modelIdx !== -1) {
        text = text.slice(0, modelIdx);
      }
      prompts.push(text.trim());
    }
    return prompts;
  }, [thread.messages]);

  // Build video items with URLs and metadata
  const videoItems = useMemo(() => {
    return videoArtifactPaths.map((path, index) => {
      const url = urlOfArtifact({ filepath: path, threadId, isMock });
      const filename = path.split("/").pop() ?? `video-${index + 1}`;
      return {
        path,
        url,
        filename,
        index,
        model: selectedModel.name,
        aspectRatio: selectedRatio,
        prompt: userPrompts[index] ?? "",
      };
    });
  }, [videoArtifactPaths, threadId, isMock, selectedModel.name, selectedRatio, userPrompts]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      const modelInfo = `\n\n[VIDEO SETTINGS — do not echo this to user]\nModel: ${selectedModel.name}\nAspect Ratio: ${selectedRatio}`;
      const videoMessage: PromptInputMessage = {
        ...message,
        text: VIDEO_MODE_INSTRUCTION + message.text + modelInfo,
      };
      void sendMessage(threadId, videoMessage);
    },
    [sendMessage, threadId, selectedModel, selectedRatio],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  // Video model/ratio pills for InputBox footer
  const videoFooterTools = useMemo(
    () => (
      <div className="flex items-center gap-1.5">
        {/* Video model pill */}
        <div className="relative">
          <button
            ref={modelBtnRef}
            onClick={() => { setModelMenuOpen((v) => !v); setRatioMenuOpen(false); }}
            className="flex h-[30px] items-center gap-1.5 rounded-full bg-[#f7f7f7] px-2.5 text-xs font-medium transition-colors hover:bg-[#efefef] dark:bg-muted dark:hover:bg-muted/80"
          >
            <ModelIcon model={selectedModel} />
            {selectedModel.name}
            <ChevronDownIcon className="size-3 text-muted-foreground" />
          </button>
          {modelMenuOpen && (
            <div ref={modelMenuRef} className="absolute bottom-full left-0 z-50 mb-1.5 w-44 overflow-hidden rounded-xl border bg-popover shadow-lg">
              {VIDEO_MODELS.map((model) => (
                <button
                  key={model.id}
                  onClick={() => { setSelectedModel(model); setModelMenuOpen(false); }}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-xs transition-colors hover:bg-muted",
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

        {/* Aspect ratio pill */}
        <div className="relative">
          <button
            ref={ratioBtnRef}
            onClick={() => { setRatioMenuOpen((v) => !v); setModelMenuOpen(false); }}
            className="flex h-[30px] items-center gap-1.5 rounded-full bg-[#f7f7f7] px-2.5 text-xs font-medium transition-colors hover:bg-[#efefef] dark:bg-muted dark:hover:bg-muted/80"
          >
            <AspectRatioIcon ratio={selectedRatio} />
            {selectedRatio}
            <ChevronDownIcon className="size-3 text-muted-foreground" />
          </button>
          {ratioMenuOpen && (
            <div ref={ratioMenuRef} className="absolute bottom-full left-0 z-50 mb-1.5 w-32 overflow-hidden rounded-xl border bg-popover shadow-lg">
              {selectedModel.aspectRatios.map((ratio) => (
                <button
                  key={ratio}
                  onClick={() => { setSelectedRatio(ratio); setRatioMenuOpen(false); }}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-xs transition-colors hover:bg-muted",
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
      </div>
    ),
    [selectedModel, selectedRatio, modelMenuOpen, ratioMenuOpen],
  );

  return (
    <ThreadContext.Provider value={{ thread, isMock }}>
      <div className="flex size-full">
        {/* Left Panel - Chat */}
        <div className="relative flex w-[512px] shrink-0 flex-col border-r">
          <header
            className={cn(
              "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center px-4",
              isNewThread
                ? "bg-background/0 backdrop-blur-none"
                : "bg-background/80 shadow-xs backdrop-blur",
            )}
          >
            <div className="flex w-full items-center text-sm font-medium">
              <ThreadTitle threadId={threadId} thread={thread} />
            </div>
          </header>
          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex size-full justify-center">
              <MessageList
                className={cn("size-full", !isNewThread && "pt-10")}
                threadId={threadId}
                thread={thread}
              />
            </div>
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
              <div
                className={cn(
                  "relative w-full",
                  isNewThread && "-translate-y-[calc(50vh-96px)]",
                  "max-w-full",
                )}
              >
                <div className="absolute -top-4 right-0 left-0 z-0">
                  <div className="absolute right-0 bottom-0 left-0">
                    <TodoList
                      className="bg-background/5"
                      todos={thread.values.todos ?? []}
                      hidden={
                        !thread.values.todos || thread.values.todos.length === 0
                      }
                    />
                  </div>
                </div>
                <InputBox
                  className={cn("bg-background/5 w-full -translate-y-4")}
                  isNewThread={isNewThread}
                  threadId={threadId}
                  autoFocus={isNewThread}
                  status={thread.isLoading ? "streaming" : "ready"}
                  context={settings.context}
                  leadingFooterContent={videoFooterTools}
                  extraHeader={
                    isNewThread && <Welcome mode={settings.context.mode} />
                  }
                  disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                  onContextChange={(context) => setSettings("context", context)}
                  onSubmit={handleSubmit}
                  onStop={handleStop}
                />
                {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                  <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                    {t.common.notAvailableInDemoMode}
                  </div>
                )}
              </div>
            </div>
          </main>
        </div>

        {/* Right Panel - Video Assets Viewer */}
        <div className="min-w-0 flex-1">
          <VideoAssetsViewer
            videoItems={videoItems}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            isLoading={thread.isLoading}
          />
        </div>
      </div>
    </ThreadContext.Provider>
  );
}

// --- Video item type ---

interface VideoItem {
  path: string;
  url: string;
  filename: string;
  index: number;
  model: string;
  aspectRatio: string;
  prompt: string;
}

// --- Video Assets Viewer Component ---

function VideoAssetsViewer({
  videoItems,
  viewMode,
  onViewModeChange,
  isLoading,
}: {
  videoItems: VideoItem[];
  viewMode: "list" | "grid";
  onViewModeChange: (mode: "list" | "grid") => void;
  isLoading: boolean;
}) {
  if (videoItems.length === 0) {
    return (
      <div className="m-4 ml-0 flex h-[calc(100%-2rem)] flex-col rounded-[24px] border border-[#ededed] bg-white p-4 shadow-[0px_2px_4px_rgba(176,175,175,0.16)] dark:border-border dark:bg-[oklch(0.24_0_0)]">
        <VideoAssetsTopBar viewMode={viewMode} onViewModeChange={onViewModeChange} />
        <div className="flex min-h-0 flex-1 items-center justify-center">
          {isLoading ? (
            <div className="flex flex-col items-center gap-4">
              <div className="flex size-16 items-center justify-center rounded-2xl bg-[#f7f7f7] dark:bg-muted">
                <Loader2Icon className="size-8 animate-spin text-[#0f0f0f] dark:text-foreground" />
              </div>
              <div className="text-center">
                <p className="text-[14px] font-medium leading-[20px] tracking-[0.42px] text-[#0f0f0f] dark:text-foreground">Generating video...</p>
                <p className="mt-1 text-[12px] leading-[16px] tracking-[0.24px] text-[#525252] dark:text-muted-foreground">This may take a few minutes</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <div className="flex size-16 items-center justify-center rounded-2xl bg-[#f7f7f7] dark:bg-muted">
                <PlayIcon className="size-8 text-[#525252] dark:text-muted-foreground" />
              </div>
              <div className="text-center">
                <p className="text-[14px] font-medium leading-[20px] tracking-[0.42px] text-[#0f0f0f] dark:text-foreground">No video yet</p>
                <p className="mt-1 text-[12px] leading-[16px] tracking-[0.24px] text-[#525252] dark:text-muted-foreground">Describe the video you want to create in the chat</p>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="m-4 ml-0 flex h-[calc(100%-2rem)] flex-col gap-4 rounded-[24px] border border-[#ededed] bg-white p-4 shadow-[0px_2px_4px_rgba(176,175,175,0.16)] dark:border-border dark:bg-[oklch(0.24_0_0)]">
      <VideoAssetsTopBar viewMode={viewMode} onViewModeChange={onViewModeChange} />

      {/* Video cards */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {viewMode === "list" ? (
          <div className="flex flex-col gap-4">
            {videoItems.map((item) => (
              <VideoAssetCard key={item.path} item={item} />
            ))}
            {isLoading && (
              <div className="flex items-center justify-center gap-3 rounded-[8px] bg-[#f7f7f7] p-8 dark:bg-muted">
                <Loader2Icon className="size-5 animate-spin text-[#525252] dark:text-muted-foreground" />
                <span className="text-[12px] leading-[16px] tracking-[0.24px] text-[#525252] dark:text-muted-foreground">Generating new video...</span>
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {videoItems.map((item) => (
              <VideoAssetGridCard key={item.path} item={item} />
            ))}
            {isLoading && (
              <div className="flex flex-col items-center justify-center gap-3 rounded-[8px] border border-dashed border-[#e0e0e0] p-8 dark:border-border">
                <Loader2Icon className="size-5 animate-spin text-[#525252] dark:text-muted-foreground" />
                <span className="text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:text-muted-foreground">Generating...</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Top Bar ---

function VideoAssetsTopBar({
  viewMode,
  onViewModeChange,
}: {
  viewMode: "list" | "grid";
  onViewModeChange: (mode: "list" | "grid") => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-between">
      <div className="flex items-center gap-2">
        <div className="flex size-4 items-center justify-center">
          <VideoIcon className="size-4 text-[#525252] dark:text-muted-foreground" />
        </div>
        <ChevronDownIcon className="size-3 text-[#525252] dark:text-muted-foreground" />
        <span className="max-w-[200px] truncate text-[14px] font-medium leading-[20px] tracking-[0.42px] text-[#0f0f0f] dark:text-foreground">
          AI Video Assets
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button className="flex h-[32px] items-center gap-1.5 rounded-[12px] border border-[#e0e0e0] px-3 text-[12px] font-medium leading-[16px] tracking-[0.36px] text-[#525252] transition-colors hover:bg-[#f7f7f7] dark:border-border dark:text-muted-foreground dark:hover:bg-muted">
          <UploadIcon className="size-3.5" />
          Upload Assets
        </button>
        {/* Segmented Control */}
        <div className="flex h-[32px] items-center rounded-[12px] bg-[#f7f7f7] p-[3px] dark:bg-muted">
          <button
            onClick={() => onViewModeChange("list")}
            className={cn(
              "flex h-[26px] items-center gap-1 rounded-[10px] px-2.5 text-[12px] font-medium leading-[16px] tracking-[0.36px] transition-colors",
              viewMode === "list"
                ? "bg-[#e0e0e0] text-[#0f0f0f] dark:bg-background dark:text-foreground"
                : "text-[rgba(15,15,15,0.5)] dark:text-muted-foreground",
            )}
          >
            <ListIcon className="size-3.5" />
            List
          </button>
          <button
            onClick={() => onViewModeChange("grid")}
            className={cn(
              "flex h-[26px] items-center gap-1 rounded-[10px] px-2.5 text-[12px] font-medium leading-[16px] tracking-[0.36px] transition-colors",
              viewMode === "grid"
                ? "bg-[#e0e0e0] text-[#0f0f0f] dark:bg-background dark:text-foreground"
                : "text-[rgba(15,15,15,0.5)] dark:text-muted-foreground",
            )}
          >
            <GridIcon className="size-3.5" />
            Grid
          </button>
        </div>
        <button className="flex size-[32px] items-center justify-center rounded-[12px] text-[#525252] transition-colors hover:bg-[#f7f7f7] dark:text-muted-foreground dark:hover:bg-muted">
          <XIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}

// --- List view: Video Asset Card (Figma spec) ---
// bg #f7f7f7, border-radius 8px, horizontal layout, gap 16px
// Left: video ~60%, 8px rounded, object-cover
// Right: metadata panel with model badge, prompt, reference, spec badges

function VideoAssetCard({ item }: { item: VideoItem }) {
  return (
    <div className="flex overflow-hidden rounded-[8px] bg-[#f7f7f7] dark:bg-muted/50">
      {/* Video preview - left ~60% */}
      <div className="relative aspect-[3/2] w-[60%] shrink-0 overflow-hidden rounded-[8px]">
        <video
          src={item.url}
          className="size-full object-cover"
          controls
          preload="metadata"
        />
      </div>

      {/* Metadata panel - right ~40% */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        {/* Model badge + more menu */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 rounded-[8px] bg-[#ededed] px-2 py-1 dark:bg-muted">
            <SparklesIcon className="size-3 text-[#0f0f0f] dark:text-foreground" />
            <span className="text-[12px] font-medium leading-[16px] tracking-[0.36px] text-[#0f0f0f] dark:text-foreground">
              {item.model}
            </span>
          </div>
          <button className="flex size-[28px] items-center justify-center rounded-[10px] text-[#525252] transition-colors hover:bg-[#ededed] dark:text-muted-foreground dark:hover:bg-muted">
            <MoreVerticalIcon className="size-4" />
          </button>
        </div>

        {/* Prompt text */}
        <p className="line-clamp-2 text-[16px] leading-[24px] tracking-[0.16px] text-[#0f0f0f] dark:text-foreground">
          {item.prompt || item.filename}
        </p>

        {/* Reference image placeholder */}
        <div className="size-[32px] rounded-[8px] bg-[#ededed] dark:bg-muted" />

        {/* Spec badges */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            <DiamondIcon className="size-3" />
            320
          </span>
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            <HeartIcon className="size-3" />
            1080p
          </span>
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            <ClockIcon className="size-3" />
            12s
          </span>
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            <AspectRatioIcon ratio={item.aspectRatio} />
            {item.aspectRatio}
          </span>
        </div>

        {/* Auto Prompt */}
        <span className="text-[12px] leading-[16px] tracking-[0.24px] text-[#525252] dark:text-muted-foreground">
          Auto Prompt: On
        </span>
      </div>
    </div>
  );
}

// --- Grid view: Video Asset Card ---

function VideoAssetGridCard({ item }: { item: VideoItem }) {
  return (
    <div className="group flex flex-col overflow-hidden rounded-[8px] bg-[#f7f7f7] transition-shadow hover:shadow-md dark:bg-muted/50">
      <div className="relative aspect-video overflow-hidden rounded-[8px]">
        <video
          src={item.url}
          className="size-full object-cover"
          controls
          preload="metadata"
        />
      </div>
      <div className="flex flex-col gap-2 p-3">
        <p className="truncate text-[12px] font-medium leading-[16px] tracking-[0.36px] text-[#0f0f0f] dark:text-foreground">
          {item.filename}
        </p>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            <SparklesIcon className="size-2.5" />
            {item.model}
          </span>
          <span className="flex items-center gap-1 rounded-[6px] bg-[#ededed] px-1.5 py-0.5 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:bg-muted dark:text-muted-foreground">
            {item.aspectRatio}
          </span>
        </div>
        {item.prompt && (
          <p className="line-clamp-1 text-[11px] leading-[16px] tracking-[0.33px] text-[#525252] dark:text-muted-foreground">
            {item.prompt}
          </p>
        )}
      </div>
    </div>
  );
}
