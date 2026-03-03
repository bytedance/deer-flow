import type { Message } from "@langchain/langgraph-sdk";
import {
  BookOpenTextIcon,
  CheckCircle2Icon,
  ClockIcon,
  ChevronUp,
  FolderOpenIcon,
  GlobeIcon,
  LightbulbIcon,
  ListTodoIcon,
  MessageCircleQuestionMarkIcon,
  NotebookPenIcon,
  SearchIcon,
  SparklesIcon,
  SquareTerminalIcon,
  WrenchIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractReasoningContentFromMessage,
  findToolCallResult,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { extractTitleFromMarkdown } from "@/core/utils/markdown";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { useArtifacts } from "../artifacts";
import { FlipDisplay } from "../flip-display";
import { Tooltip } from "../tooltip";

import { MarkdownContent } from "./markdown-content";

export function MessageGroup({
  className,
  messages,
  isLoading = false,
}: {
  className?: string;
  messages: Message[];
  isLoading?: boolean;
}) {
  const { t } = useI18n();
  const [showAbove, setShowAbove] = useState(
    env.VITE_STATIC_WEBSITE_ONLY === "true",
  );
  const [showLastThinking, setShowLastThinking] = useState(
    env.VITE_STATIC_WEBSITE_ONLY === "true",
  );
  const steps = useMemo(() => convertToSteps(messages), [messages]);
  const lastToolCallStep = useMemo(() => {
    const filteredSteps = steps.filter((step) => step.type === "toolCall");
    return filteredSteps[filteredSteps.length - 1];
  }, [steps]);
  const aboveLastToolCallSteps = useMemo(() => {
    if (lastToolCallStep) {
      const index = steps.indexOf(lastToolCallStep);
      return steps.slice(0, index);
    }
    return [];
  }, [lastToolCallStep, steps]);
  const lastReasoningStep = useMemo(() => {
    if (lastToolCallStep) {
      const index = steps.indexOf(lastToolCallStep);
      return steps.slice(index + 1).find((step) => step.type === "reasoning");
    } else {
      const filteredSteps = steps.filter((step) => step.type === "reasoning");
      return filteredSteps[filteredSteps.length - 1];
    }
  }, [lastToolCallStep, steps]);
  const isThinkingStreaming = isLoading && Boolean(lastReasoningStep);
  const showThinking = isThinkingStreaming ? true : showLastThinking;
  const thinkingScrollRef = useRef<HTMLDivElement | null>(null);
  const toolCallsScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!isThinkingStreaming) {
      return;
    }
    const container = thinkingScrollRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [isThinkingStreaming, lastReasoningStep?.reasoning]);
  useEffect(() => {
    if (!isLoading) {
      return;
    }
    const container = toolCallsScrollRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [isLoading, aboveLastToolCallSteps.length, lastToolCallStep?.id, showAbove]);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const showDoneStep = !isLoading && steps.length > 0;
  return (
    <ChainOfThought
      className={cn(
        "bg-background/50 w-full gap-2 rounded-lg border p-0.5",
        className,
      )}
      open={true}
    >
      {aboveLastToolCallSteps.length > 0 && (
        <Button
          key="above"
          className="w-full items-start justify-start text-left"
          variant="ghost"
          onClick={() => setShowAbove(!showAbove)}
        >
          <ChainOfThoughtStep
            className="my-0"
            label={
              <span className="opacity-60">
                {showAbove
                  ? t.toolCalls.lessSteps
                  : t.toolCalls.moreSteps(aboveLastToolCallSteps.length)}
              </span>
            }
            icon={
              <ChevronUp
                className={cn(
                  "size-4 opacity-60 transition-transform duration-200",
                  showAbove ? "" : "rotate-180",
                )}
              />
            }
          ></ChainOfThoughtStep>
        </Button>
      )}
      {lastToolCallStep && (
        <ChainOfThoughtContent className="px-4 pb-2">
          <div
            ref={toolCallsScrollRef}
            className="max-h-[36rem] overflow-y-auto pr-2"
          >
            {showAbove &&
              aboveLastToolCallSteps.map((step) =>
                step.type === "reasoning" ? (
                  <ChainOfThoughtStep
                    key={step.id}
                    icon={ClockIcon}
                    className="text-[rgb(175,174,163)]"
                    label={
                      <MarkdownContent
                        content={step.reasoning ?? ""}
                        isLoading={isLoading}
                        rehypePlugins={rehypePlugins}
                      />
                    }
                  ></ChainOfThoughtStep>
                ) : (
                  <ToolCall key={step.id} {...step} isLoading={isLoading} />
                ),
              )}
            {lastToolCallStep && (
              <FlipDisplay uniqueKey={lastToolCallStep.id ?? ""}>
                <ToolCall
                  key={lastToolCallStep.id}
                  {...lastToolCallStep}
                  isLast={true}
                  isLoading={isLoading}
                  hideContent={aboveLastToolCallSteps.length > 0 && !showAbove}
                />
              </FlipDisplay>
            )}
          </div>
        </ChainOfThoughtContent>
      )}
      {lastReasoningStep && (
        <>
          <Button
            key={lastReasoningStep.id}
            className="w-full items-start justify-start text-left"
            variant="ghost"
            onClick={() => {
              if (isThinkingStreaming) {
                return;
              }
              setShowLastThinking(!showLastThinking);
            }}
          >
            <div className="flex w-full items-center justify-between">
              <ChainOfThoughtStep
                className="my-0 font-normal"
                label={t.common.thinking}
                icon={LightbulbIcon}
              ></ChainOfThoughtStep>
              <div>
                <ChevronUp
                  className={cn(
                    "text-muted-foreground size-4",
                    showThinking ? "" : "rotate-180",
                  )}
                />
              </div>
            </div>
          </Button>
          {showThinking && (
            <ChainOfThoughtContent className="px-4 pb-2">
              <div
                ref={thinkingScrollRef}
                className="max-h-[36rem] overflow-y-auto pr-2"
              >
                <ChainOfThoughtStep
                  key={lastReasoningStep.id}
                  icon={ClockIcon}
                  className="text-[rgb(175,174,163)]"
                  label={
                    <MarkdownContent
                      content={lastReasoningStep.reasoning ?? ""}
                      isLoading={isLoading}
                      rehypePlugins={rehypePlugins}
                    />
                  }
                ></ChainOfThoughtStep>
              </div>
            </ChainOfThoughtContent>
          )}
        </>
      )}
      {showDoneStep && (
        <div className="px-4 pb-2">
          <ChainOfThoughtStep
            className="my-0"
            icon={
              <CheckCircle2Icon className="text-emerald-500 dark:text-emerald-400 size-4" />
            }
            label={t.toolCalls.done}
          />
        </div>
      )}
    </ChainOfThought>
  );
}

function ToolCall({
  id,
  messageId,
  name,
  args,
  result,
  isLast = false,
  isLoading = false,
  hideContent = false,
}: {
  id?: string;
  messageId?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string | Record<string, unknown>;
  isLast?: boolean;
  isLoading?: boolean;
  hideContent?: boolean;
}) {
  const { t } = useI18n();
  const { setOpen, autoOpen, autoSelect, selectedArtifact, select } =
    useArtifacts();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);

  if (name === "web_search") {
    let label: React.ReactNode = t.toolCalls.searchForRelatedInfo;
    if (typeof args.query === "string") {
      label = t.toolCalls.searchOnWebFor(args.query);
    }
    const getHostname = (url: string) => {
      try {
        return new URL(url).hostname.replace(/^www\./, "");
      } catch {
        return url;
      }
    };
    return (
      <ChainOfThoughtStep key={id} label={label} icon={SearchIcon}>
        {!hideContent && Array.isArray(result) && (
          <div className="bg-background/80 mt-2 overflow-hidden rounded-lg border">
            <ul className="divide-y divide-border/70">
              {result.map((item) => (
                <li key={item.url}>
                  <a
                    className="group flex items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-muted/60"
                    href={item.url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <GlobeIcon className="text-muted-foreground size-4 shrink-0" />
                    <span className="text-foreground min-w-0 flex-1 truncate">
                      {item.title}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">
                      {getHostname(item.url)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "image_search") {
    let label: React.ReactNode = t.toolCalls.searchForRelatedImages;
    if (typeof args.query === "string") {
      label = t.toolCalls.searchForRelatedImagesFor(args.query);
    }
    const results = (
      result as {
        results: {
          source_url: string;
          thumbnail_url: string;
          image_url: string;
          title: string;
        }[];
      }
    )?.results;
    return (
      <ChainOfThoughtStep key={id} label={label} icon={SearchIcon}>
        {!hideContent && Array.isArray(results) && (
          <ChainOfThoughtSearchResults>
            {Array.isArray(results) &&
              results.map((item) => (
                <Tooltip key={item.image_url} content={item.title}>
                  <a
                    className="size-24 overflow-hidden rounded-lg object-cover"
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <div className="bg-accent size-24">
                      <img
                        className="size-full object-cover"
                        src={item.thumbnail_url}
                        alt={item.title}
                        width={100}
                        height={100}
                      />
                    </div>
                  </a>
                </Tooltip>
              ))}
          </ChainOfThoughtSearchResults>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "web_fetch") {
    const url = (args as { url: string })?.url;
    let title = url;
    if (typeof result === "string") {
      const potentialTitle = extractTitleFromMarkdown(result);
      if (potentialTitle && potentialTitle.toLowerCase() !== "untitled") {
        title = potentialTitle;
      }
    }
    return (
      <ChainOfThoughtStep
        key={id}
        className="cursor-pointer"
        label={t.toolCalls.viewWebPage}
        icon={GlobeIcon}
        onClick={() => {
          window.open(url, "_blank");
        }}
      >
        {!hideContent && (
          <ChainOfThoughtSearchResult>
            {url && (
              <a href={url} target="_blank" rel="noreferrer">
                {title}
              </a>
            )}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "ls") {
    let description: string | undefined = (args as { description: string })
      ?.description;
    if (!description) {
      description = t.toolCalls.listFolder;
    }
    const path: string | undefined = (args as { path: string })?.path;
    return (
      <ChainOfThoughtStep key={id} label={description} icon={FolderOpenIcon}>
        {!hideContent && path && (
          <ChainOfThoughtSearchResult className="cursor-pointer">
            {path}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "read_file") {
    let description: string | undefined = (args as { description: string })
      ?.description;
    if (!description) {
      description = t.toolCalls.readFile;
    }
    const { path } = args as { path: string; content: string };
    return (
      <ChainOfThoughtStep key={id} label={description} icon={BookOpenTextIcon}>
        {!hideContent && path && (
          <ChainOfThoughtSearchResult className="cursor-pointer">
            {path}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "reflection" || name === "think") {
    const content =
      typeof result === "string"
        ? result
        : result
          ? JSON.stringify(result, null, 2)
          : "";
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.common.reflecting}
        icon={SparklesIcon}
      >
        {!hideContent && content ? (
          <MarkdownContent
            content={content}
            isLoading={isLoading}
            rehypePlugins={rehypePlugins}
          />
        ) : null}
      </ChainOfThoughtStep>
    );
  } else if (name === "write_file" || name === "str_replace") {
    let description: string | undefined = (args as { description: string })
      ?.description;
    if (!description) {
      description = t.toolCalls.writeFile;
    }
    const path: string | undefined = (args as { path: string })?.path;
    if (isLoading && isLast && autoOpen && autoSelect && path) {
      setTimeout(() => {
        const url = new URL(
          `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
        ).toString();
        if (selectedArtifact === url) {
          return;
        }
        select(url, true);
        setOpen(true);
      }, 100);
    }

    return (
      <ChainOfThoughtStep
        key={id}
        className="cursor-pointer"
        label={description}
        icon={NotebookPenIcon}
        onClick={() => {
          select(
            new URL(
              `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
            ).toString(),
          );
          setOpen(true);
        }}
      >
        {!hideContent && path && (
          <ChainOfThoughtSearchResult className="cursor-pointer">
            {path}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "bash") {
    const description: string | undefined = (args as { description: string })
      ?.description;
    if (!description) {
      return t.toolCalls.executeCommand;
    }
    const command: string | undefined = (args as { command: string })?.command;
    return (
      <ChainOfThoughtStep
        key={id}
        label={description}
        icon={SquareTerminalIcon}
      >
        {!hideContent && command && (
          <CodeBlock
            className="mx-0 cursor-pointer border-none px-0"
            showLineNumbers={false}
            language="bash"
            code={command}
          />
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "ask_clarification") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.needYourHelp}
        icon={MessageCircleQuestionMarkIcon}
      ></ChainOfThoughtStep>
    );
  } else if (name === "write_todos") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.writeTodos}
        icon={ListTodoIcon}
      ></ChainOfThoughtStep>
    );
  } else {
    const description: string | undefined = (args as { description: string })
      ?.description;
    return (
      <ChainOfThoughtStep
        key={id}
        label={description ?? t.toolCalls.useTool(name)}
        icon={WrenchIcon}
      ></ChainOfThoughtStep>
    );
  }
}

interface GenericCoTStep<T extends string = string> {
  id?: string;
  messageId?: string;
  type: T;
}

interface CoTReasoningStep extends GenericCoTStep<"reasoning"> {
  reasoning: string | null;
}

interface CoTToolCallStep extends GenericCoTStep<"toolCall"> {
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

type CoTStep = CoTReasoningStep | CoTToolCallStep;

function convertToSteps(messages: Message[]): CoTStep[] {
  const steps: CoTStep[] = [];
  for (const message of messages) {
    if (message.type === "ai") {
      const reasoning = extractReasoningContentFromMessage(message);
      if (reasoning) {
        const step: CoTReasoningStep = {
          id: message.id,
          messageId: message.id,
          type: "reasoning",
          reasoning: extractReasoningContentFromMessage(message),
        };
        steps.push(step);
      }
      for (const tool_call of message.tool_calls ?? []) {
        if (tool_call.name === "task") {
          continue;
        }
        const step: CoTToolCallStep = {
          id: tool_call.id,
          messageId: message.id,
          type: "toolCall",
          name: tool_call.name,
          args: tool_call.args,
        };
        const toolCallId = tool_call.id;
        if (toolCallId) {
          const toolCallResult = findToolCallResult(toolCallId, messages);
          if (toolCallResult) {
            try {
              const json = JSON.parse(toolCallResult);
              step.result = json;
            } catch {
              step.result = toolCallResult;
            }
          }
        }
        steps.push(step);
      }
    }
  }
  return steps;
}
