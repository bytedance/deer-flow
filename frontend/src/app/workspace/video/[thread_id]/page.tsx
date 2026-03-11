"use client";

import {
  DownloadIcon,
  Loader2Icon,
  PlayIcon,
  VideoIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  usePromptInputController,
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
[END SYSTEM INSTRUCTION]

User request: `;

export default function VideoPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();

  const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();
  const promptInputController = usePromptInputController();

  const { showNotification } = useNotification();

  // Video artifacts
  const [videoUrl, setVideoUrl] = useState<string | null>(null);

  // Pre-fill input with prompt from video home page
  const initialPromptAppliedRef = useRef(false);
  useEffect(() => {
    if (initialPromptAppliedRef.current) return;
    if (!isNewThread) return;
    const prompt = sessionStorage.getItem("video-initial-prompt");
    if (prompt) {
      sessionStorage.removeItem("video-initial-prompt");
      // Also clean up model/ratio from session (consumed but not used in instruction yet)
      sessionStorage.removeItem("video-model");
      sessionStorage.removeItem("video-aspect-ratio");
      initialPromptAppliedRef.current = true;
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
  }, [isNewThread, promptInputController.textInput]);

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

  // Set the latest video URL when artifacts appear
  useEffect(() => {
    if (videoArtifactPaths.length > 0) {
      const latestPath = videoArtifactPaths[videoArtifactPaths.length - 1]!;
      const url = urlOfArtifact({
        filepath: latestPath,
        threadId,
        isMock,
      });
      setVideoUrl(url);
    }
  }, [videoArtifactPaths, threadId, isMock]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      const videoMessage: PromptInputMessage = {
        ...message,
        text: VIDEO_MODE_INSTRUCTION + message.text,
      };
      void sendMessage(threadId, videoMessage);
    },
    [sendMessage, threadId],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

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

        {/* Right Panel - Video Viewer */}
        <div className="min-w-0 flex-1">
          <VideoViewer
            videoUrl={videoUrl}
            isLoading={thread.isLoading}
          />
        </div>
      </div>
    </ThreadContext.Provider>
  );
}

// --- Video Viewer Component ---

function VideoViewer({
  videoUrl,
  isLoading,
}: {
  videoUrl: string | null;
  isLoading: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleDownload = useCallback(() => {
    if (!videoUrl) return;
    const link = document.createElement("a");
    link.href = videoUrl;
    link.download = "video.mp4";
    link.click();
  }, [videoUrl]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border m-4 ml-0 bg-white dark:bg-[oklch(0.24_0_0)]">
      {/* Top bar */}
      <div className="flex h-[48px] shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <VideoIcon className="size-4 text-blue-500" />
          <span className="text-sm font-medium">Video Preview</span>
        </div>
        {videoUrl && (
          <button
            onClick={handleDownload}
            className="flex h-8 items-center gap-1.5 rounded-xl bg-blue-500/10 px-2.5 text-xs font-medium text-blue-600 hover:bg-blue-500/20 dark:text-blue-400"
          >
            <DownloadIcon className="size-4" />
            Download
          </button>
        )}
      </div>

      {/* Video content */}
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        {videoUrl ? (
          <div className="relative w-full max-w-3xl">
            <video
              ref={videoRef}
              src={videoUrl}
              className="w-full rounded-xl shadow-lg"
              controls
            />
          </div>
        ) : isLoading ? (
          <div className="flex flex-col items-center gap-4 text-muted-foreground">
            <div className="flex size-16 items-center justify-center rounded-2xl bg-blue-500/10">
              <Loader2Icon className="size-8 animate-spin text-blue-500" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">
                Generating video...
              </p>
              <p className="mt-1 text-xs">
                This may take a few minutes
              </p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-4 text-muted-foreground">
            <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
              <PlayIcon className="size-8" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">
                No video yet
              </p>
              <p className="mt-1 text-xs">
                Describe the video you want to create in the chat
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
