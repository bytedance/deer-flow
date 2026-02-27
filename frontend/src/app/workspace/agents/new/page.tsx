"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  ArrowLeftIcon,
  BotIcon,
  CheckCircleIcon,
  Loader2Icon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { checkAgentName } from "@/core/agents/api";
import { getAPIClient } from "@/core/api";
import { useI18n } from "@/core/i18n/hooks";
import { extractTextFromMessage } from "@/core/messages/utils";
import type { AgentThreadState } from "@/core/threads";
import { uuid } from "@/core/utils/uuid";
import { cn } from "@/lib/utils";

// Messages that carry tool_calls but may or may not have text
interface AIMessageRaw {
  type: string;
  tool_calls?: { name: string; id: string }[];
}

type Step = "name" | "chat";

const NAME_RE = /^[A-Za-z0-9-]+$/;

function BotAvatar() {
  return (
    <div className="bg-primary/10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full">
      <BotIcon className="text-primary h-4 w-4" />
    </div>
  );
}

export default function NewAgentPage() {
  const { t, locale } = useI18n();
  const router = useRouter();

  // ── Step 1: name form ──────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>("name");
  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [agentName, setAgentName] = useState("");

  // ── Step 2: chat ───────────────────────────────────────────────────────────
  const bottomRef = useRef<HTMLDivElement>(null);

  // Stable thread ID — all turns belong to the same thread
  const threadId = useMemo(() => uuid(), []);

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    fetchStateHistory: true,
    reconnectOnMount: false,
  });

  // True when the AI has emitted a create_custom_agent tool call but the
  // result hasn't arrived yet (or just arrived — until createdAgentName is set).
  const isCreating = useMemo(() => {
    return (thread.messages ?? []).some((msg) => {
      const raw = msg as AIMessageRaw;
      return (
        raw.type === "ai" &&
        Array.isArray(raw.tool_calls) &&
        raw.tool_calls.some((tc) => tc.name === "create_custom_agent")
      );
    });
  }, [thread.messages]);

  // Human + AI-text messages only; first human message (the auto-submitted
  // agent-name bootstrap) is hidden since the mocked opening covers it.
  const displayMessages = useMemo(() => {
    const all = (thread.messages ?? []).filter(
      (msg): msg is Message =>
        msg.type === "human" ||
        (msg.type === "ai" && extractTextFromMessage(msg).length > 0),
    );
    return all[0]?.type === "human" ? all.slice(1) : all;
  }, [thread.messages]);

  // Pulsing dots: streaming but AI hasn't replied yet (or user just sent).
  // Suppressed once we switch to the "creating" spinner.
  const showTypingIndicator =
    !isCreating &&
    thread.isLoading &&
    (displayMessages.length === 0 ||
      displayMessages[displayMessages.length - 1]?.type === "human");

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMessages, thread.isLoading, isCreating]);

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }
    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch {
      setNameError(t.agents.nameStepCheckError);
      return;
    } finally {
      setIsCheckingName(false);
    }
    setAgentName(trimmed);
    setStep("chat");
    await thread.submit(
      {
        messages: [
          {
            type: "human",
            content: `The agent name is ${trimmed}. Let's bootstrap it's **SOUL** with the \`bootstrap\` SKILL.`,
          },
        ],
      },
      {
        threadId,
        streamMode: ["values", "messages-tuple", "custom"],
        config: {
          recursion_limit: 1000,
        },
        context: {
          thread_id: threadId,
          locale,
          agent_name: trimmed,
          is_bootstrap: true,
          thinking_enabled: true,
          is_plan_mode: false,
          subagent_enabled: false,
        },
      },
    );
  }, [
    nameInput,
    thread,
    threadId,
    locale,
    t.agents.nameStepInvalidError,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepCheckError,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const handleChatSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || thread.isLoading) return;
      await thread.submit(
        {
          messages: [{ type: "human", content: trimmed }],
        },
        {
          threadId,
          streamSubgraphs: true,
          streamResumable: true,
          streamMode: ["values", "messages-tuple", "custom"],
          config: {
            recursion_limit: 1000,
          },
          context: {
            thread_id: threadId,
            locale,
            agent_name: agentName,
            is_bootstrap: true,
            thinking_enabled: true,
            is_plan_mode: false,
            subagent_enabled: false,
          },
        },
      );
    },
    [thread, threadId, locale, agentName],
  );

  // ── Shared header ──────────────────────────────────────────────────────────

  const header = (
    <header className="flex shrink-0 items-center gap-3 border-b px-4 py-3">
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => router.push("/workspace/agents")}
      >
        <ArrowLeftIcon className="h-4 w-4" />
      </Button>
      <h1 className="text-sm font-semibold">{t.agents.createPageTitle}</h1>
    </header>
  );

  // ── Step 1: name form ──────────────────────────────────────────────────────

  if (step === "name") {
    return (
      <div className="flex size-full flex-col">
        {header}
        <main className="flex flex-1 flex-col items-center justify-center px-4">
          <div className="w-full max-w-sm space-y-8">
            <div className="space-y-3 text-center">
              <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
                <BotIcon className="text-primary h-7 w-7" />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-semibold">
                  {t.agents.nameStepTitle}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {t.agents.nameStepHint}
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <Input
                autoFocus
                placeholder={t.agents.nameStepPlaceholder}
                value={nameInput}
                onChange={(e) => {
                  setNameInput(e.target.value);
                  setNameError("");
                }}
                onKeyDown={handleNameKeyDown}
                className={cn(nameError && "border-destructive")}
              />
              {nameError && (
                <p className="text-destructive text-sm">{nameError}</p>
              )}
              <Button
                className="w-full"
                onClick={() => void handleConfirmName()}
                disabled={!nameInput.trim() || isCheckingName}
              >
                {t.agents.nameStepContinue}
              </Button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ── Step 2: chat ───────────────────────────────────────────────────────────

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ArtifactsProvider>
        <div className="flex size-full flex-col">
          {header}

          <main className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6">
              <MessageList
                className={cn("size-full", "pt-10")}
                threadId={threadId}
                thread={thread}
              />

              {/* Typing indicator */}
              {showTypingIndicator && (
                <div className="flex items-start gap-3">
                  <BotAvatar />
                  <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3">
                    <div className="flex gap-1">
                      <span className="bg-muted-foreground/50 h-2 w-2 animate-bounce rounded-full [animation-delay:0ms]" />
                      <span className="bg-muted-foreground/50 h-2 w-2 animate-bounce rounded-full [animation-delay:150ms]" />
                      <span className="bg-muted-foreground/50 h-2 w-2 animate-bounce rounded-full [animation-delay:300ms]" />
                    </div>
                  </div>
                </div>
              )}

              {/* ── Bottom action area ── */}

              {isCreating && !thread.isLoading ? (
                // ✅ Inline success card
                <div className="flex flex-col items-center gap-4 rounded-2xl border py-10 text-center">
                  <CheckCircleIcon className="text-primary h-10 w-10" />
                  <div className="space-y-1">
                    <p className="font-semibold">{t.agents.agentCreated}</p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      onClick={() =>
                        router.push(`/workspace/agents/${agentName}/chats/new`)
                      }
                    >
                      {t.agents.startChatting}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => router.push("/workspace/agents")}
                    >
                      {t.agents.backToGallery}
                    </Button>
                  </div>
                </div>
              ) : isCreating ? (
                // ⏳ Tool in flight — spinner
                <div className="text-muted-foreground flex items-center gap-2 py-2">
                  <Loader2Icon className="h-4 w-4 animate-spin" />
                  <span className="text-sm">{t.agents.creating}</span>
                </div>
              ) : (
                // 📝 Normal input
                <PromptInput
                  onSubmit={({ text }) => void handleChatSubmit(text)}
                >
                  <PromptInputTextarea
                    autoFocus
                    placeholder={t.agents.createPageSubtitle}
                    disabled={thread.isLoading}
                  />
                  <PromptInputFooter className="justify-end">
                    <PromptInputSubmit disabled={thread.isLoading} />
                  </PromptInputFooter>
                </PromptInput>
              )}

              <div ref={bottomRef} />
            </div>
          </main>
        </div>
      </ArtifactsProvider>
    </ThreadContext.Provider>
  );
}
