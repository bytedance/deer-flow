"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
    usePromptInputController,
    type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { useThreadChat } from "@/components/workspace/chats";
import { DocumentWorkspace } from "@/components/workspace/documents";
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



export default function DocumentsThreadPage() {
    const { t } = useI18n();
    const [settings, setSettings] = useLocalSettings();
    const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();
    const promptInputController = usePromptInputController();
    const { showNotification } = useNotification();

    const [docContent, setDocContent] = useState<string | null>(null);
    const [docFormat, setDocFormat] = useState<"html" | "markdown">("html");
    const [docTitle, setDocTitle] = useState<string>("");
    const [downloadUrl, setDownloadUrl] = useState<string>("");
    const loadingRef = useRef(false);

    // Pre-fill input with prompt from home page
    const initialPromptAppliedRef = useRef(false);
    useEffect(() => {
        if (initialPromptAppliedRef.current) return;
        if (!isNewThread) return;
        const prompt = sessionStorage.getItem("documents-initial-prompt");
        if (prompt) {
            sessionStorage.removeItem("documents-initial-prompt");
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
            history.replaceState(null, "", `/workspace/documents/${threadId}`);
        },
        onFinish: (state) => {
            if (document.hidden || !document.hasFocus()) {
                let body = "Document generated";
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

    // Find document artifacts (.html or .md)
    const docArtifactPath = useMemo(() => {
        const artifacts: string[] = thread.values.artifacts ?? [];
        return artifacts.find(
            (p) =>
                (p.endsWith(".html") || p.endsWith(".md")) &&
                p.includes("/outputs/"),
        );
    }, [thread.values.artifacts]);

    // Fetch document content
    const fetchDocument = useCallback(
        (filepath: string) => {
            if (loadingRef.current) return;
            loadingRef.current = true;

            const url = urlOfArtifact({ filepath, threadId, isMock });
            const fileName = filepath.split("/").pop() ?? "document";
            const format = filepath.endsWith(".md") ? "markdown" : "html";
            const name = fileName.replace(/\.(html|md)$/, "").split(/[-_]/).map(
                (w) => w.charAt(0).toUpperCase() + w.slice(1),
            ).join(" ");

            fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`)
                .then((res) => {
                    if (!res.ok) throw new Error(`Failed: ${res.status}`);
                    return res.text();
                })
                .then((text) => {
                    setDocContent(text);
                    setDocFormat(format as "html" | "markdown");
                    setDocTitle(name);
                    setDownloadUrl(
                        urlOfArtifact({ filepath, threadId, download: true, isMock }),
                    );
                })
                .catch((err) => {
                    console.error("Failed to load document:", err);
                })
                .finally(() => {
                    loadingRef.current = false;
                });
        },
        [threadId, isMock],
    );

    // Load document when artifact appears
    useEffect(() => {
        if (docArtifactPath) {
            fetchDocument(docArtifactPath);
        }
    }, [docArtifactPath, fetchDocument]);

    // Reload when stream finishes
    const prevLoadingRef = useRef(false);
    useEffect(() => {
        const wasLoading = prevLoadingRef.current;
        prevLoadingRef.current = thread.isLoading;
        if (wasLoading && !thread.isLoading && docArtifactPath) {
            fetchDocument(docArtifactPath);
        }
    }, [thread.isLoading, docArtifactPath, fetchDocument]);

    const handleSubmit = useCallback(
        (message: PromptInputMessage) => {
            void sendMessage(threadId, message);
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
                            </div>
                        </div>
                    </main>
                </div>

                {/* Right Panel - Document Workspace */}
                <div className="min-w-0 flex-1">
                    <DocumentWorkspace
                        className="size-full"
                        content={docContent}
                        format={docFormat}
                        title={docTitle}
                        downloadUrl={downloadUrl}
                    />
                </div>
            </div>
        </ThreadContext.Provider>
    );
}
