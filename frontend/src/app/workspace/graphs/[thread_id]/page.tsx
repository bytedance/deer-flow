"use client";

import type { JSONContent } from "@tiptap/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { useThreadChat } from "@/components/workspace/chats";
import { GraphWorkspace } from "@/components/workspace/graphs";
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

const GRAPHS_MODE_INSTRUCTION = `[SYSTEM INSTRUCTION — AI GRAPHS MODE]
You are operating in AI Graphs mode. You MUST follow these rules:
1. Use ONLY the "ai-graphs" skill. Run: python /mnt/skills/public/ai-graphs/scripts/generate.py
2. Output TipTap JSON files with ECharts to /mnt/user-data/outputs/. You may create ONE file (dashboard.json) or MULTIPLE files (e.g. overview.json, details.json) — each becomes a separate page.
3. NEVER generate HTML files, PNG images, or SVG files.
4. NEVER use chart-visualization skill or generate.js.
5. If no data file is uploaded, search the web for data, create a CSV at /mnt/user-data/uploads/, then use generate.py.
6. After writing JSON files, ALWAYS call present_files with ALL output JSON paths.
7. The dashboard renders in an interactive TipTap editor with ECharts charts on the right panel. Multiple JSON files become multiple pages.
[END SYSTEM INSTRUCTION]

User request: `;


export default function GraphsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();

  const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();
  const promptInputController = usePromptInputController();

  const { showNotification } = useNotification();

  // Dashboard TipTap JSON pages loaded from artifact files
  const [dashboardPages, setDashboardPages] = useState<
    { name: string; content: JSONContent; filepath: string }[]
  >([]);
  const loadingRef = useRef(false);

  // Pre-fill input with prompt from graphs home page
  const initialPromptAppliedRef = useRef(false);
  useEffect(() => {
    if (initialPromptAppliedRef.current) return;
    if (!isNewThread) return;
    const prompt = sessionStorage.getItem("graphs-initial-prompt");
    if (prompt) {
      sessionStorage.removeItem("graphs-initial-prompt");
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
      history.replaceState(null, "", `/workspace/graphs/${threadId}`);
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

  // Find all JSON artifact paths from outputs
  const dashboardArtifactPaths = useMemo(() => {
    const artifacts: string[] = thread.values.artifacts ?? [];
    return artifacts.filter(
      (p) => p.endsWith(".json") && p.includes("/outputs/"),
    );
  }, [thread.values.artifacts]);

  // Fetch all dashboard JSON files
  const fetchDashboards = useCallback(
    (paths: string[]) => {
      if (loadingRef.current || paths.length === 0) return;
      loadingRef.current = true;

      const fetches = paths.map((filepath) => {
        const url = urlOfArtifact({ filepath, threadId, isMock });
        const fileName =
          filepath.split("/").pop()?.replace(".json", "") ?? "Page";
        // Humanize: "usability-dashboard" → "Usability Dashboard"
        const name = fileName
          .split(/[-_]/)
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(" ");

        return fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`)
          .then((res) => {
            if (!res.ok) throw new Error(`Failed: ${res.status}`);
            return res.json();
          })
          .then((json: JSONContent) => ({ name, content: json, filepath }))
          .catch((err) => {
            console.error(`Failed to load ${filepath}:`, err);
            return null;
          });
      });

      void Promise.all(fetches)
        .then((results) => {
          const valid = results.filter(
            (r): r is { name: string; content: JSONContent; filepath: string } => r !== null,
          );
          if (valid.length > 0) {
            setDashboardPages(valid);
          }
        })
        .finally(() => {
          loadingRef.current = false;
        });
    },
    [threadId, isMock],
  );

  // Load dashboards when artifacts first appear
  useEffect(() => {
    if (dashboardArtifactPaths.length > 0) {
      fetchDashboards(dashboardArtifactPaths);
    }
  }, [dashboardArtifactPaths, fetchDashboards]);

  // Reload dashboards when the stream finishes
  const prevLoadingRef = useRef(false);
  useEffect(() => {
    const wasLoading = prevLoadingRef.current;
    prevLoadingRef.current = thread.isLoading;
    if (
      wasLoading &&
      !thread.isLoading &&
      dashboardArtifactPaths.length > 0
    ) {
      fetchDashboards(dashboardArtifactPaths);
    }
  }, [thread.isLoading, dashboardArtifactPaths, fetchDashboards]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      const graphsMessage: PromptInputMessage = {
        ...message,
        text: GRAPHS_MODE_INSTRUCTION + message.text,
      };
      void sendMessage(threadId, graphsMessage);
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

        {/* Right Panel - Graph Workspace */}
        <div className="min-w-0 flex-1">
          <GraphWorkspace
            className="size-full"
            dashboardPages={dashboardPages}
            threadId={threadId}
          />
        </div>
      </div>
    </ThreadContext.Provider>
  );
}
