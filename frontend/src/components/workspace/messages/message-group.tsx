import type { Message } from "@langchain/langgraph-sdk";
import {
  BookOpenTextIcon,
  CheckCircle2Icon,
  ChevronRight,
  ClockIcon,
  ChevronUp,
  DatabaseIcon,
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
import {
  memo,
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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
  describeMcpTool,
  extractMcpMeta,
  isMcpDataResult,
} from "@/core/mcp/tools";
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

export const MessageGroup = memo(function MessageGroup({
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
  const resultCacheRef = useRef(new Map<string, unknown>());
  const steps = useMemo(
    () => convertToSteps(messages, resultCacheRef.current),
    [messages],
  );
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
          onClick={() => startTransition(() => setShowAbove(!showAbove))}
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
                    className="text-[rgb(108,107,98)] dark:text-[rgb(175,174,163)]"
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
              startTransition(() => setShowLastThinking(!showLastThinking));
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
                  className="text-[rgb(108,107,98)] dark:text-[rgb(175,174,163)]"
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
}, (prev, next) => {
  if (prev.isLoading !== next.isLoading) return false;
  if (prev.className !== next.className) return false;
  if (prev.messages.length !== next.messages.length) return false;
  // Reference-compare the last message (only the streaming group changes)
  const prevLast = prev.messages[prev.messages.length - 1];
  const nextLast = next.messages[next.messages.length - 1];
  return prevLast === nextLast;
});

const ToolCall = memo(function ToolCall({
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
          startTransition(() => {
            select(
              new URL(
                `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
              ).toString(),
            );
            setOpen(true);
          });
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
  } else if (isMcpDataResult(result)) {
    return (
      <McpDataToolCall
        id={id}
        messageId={messageId}
        name={name}
        args={args}
        result={result}
        hideContent={hideContent}
      />
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
}, (prev, next) => {
  // Tool call results are immutable once set — only re-render when
  // result arrives (undefined → defined) or display state changes.
  return prev.id === next.id
    && prev.isLast === next.isLast
    && prev.isLoading === next.isLoading
    && prev.hideContent === next.hideContent
    && (prev.result == null) === (next.result == null);
});

const MAX_PREVIEW_COLUMNS = 6;

const McpDataToolCall = memo(function McpDataToolCall({
  id,
  messageId,
  name,
  args,
  result,
  hideContent = false,
}: {
  id?: string;
  messageId?: string;
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  hideContent?: boolean;
}) {
  const { t } = useI18n();
  const { setOpen, select } = useArtifacts();

  const label = useMemo(
    () => describeMcpTool(name, args, t.toolCalls.useTool(name)),
    [name, args, t],
  );
  const meta = useMemo(() => extractMcpMeta(name, result), [name, result]);
  const data = result.data as Record<string, unknown>[];

  const { columns, previewRows, remaining } = useMemo(() => {
    const firstRow = data[0];
    const allCols = firstRow ? Object.keys(firstRow) : [];
    const cols = allCols.length > MAX_PREVIEW_COLUMNS
      ? allCols.slice(0, MAX_PREVIEW_COLUMNS)
      : allCols;
    return {
      columns: cols,
      previewRows: data.slice(0, 3),
      remaining: data.length - 3,
    };
  }, [data]);

  const handleExpand = useCallback(() => {
    if (!id) return;
    const url = new URL(
      `mcp-data:${name}?tool_call_id=${id}${messageId ? `&message_id=${messageId}` : ""}`,
    ).toString();
    startTransition(() => {
      select(url);
      setOpen(true);
    });
  }, [id, name, messageId, select, setOpen]);

  return (
    <ChainOfThoughtStep key={id} label={label} icon={DatabaseIcon}>
      <ChainOfThoughtSearchResults>
        <ChainOfThoughtSearchResult>
          {t.toolCalls.mcpDataResults(meta.count, meta.total)}
        </ChainOfThoughtSearchResult>
        {meta.page != null && meta.totalPages != null && meta.totalPages > 1 && (
          <ChainOfThoughtSearchResult>
            {t.toolCalls.mcpDataPage(meta.page, meta.totalPages)}
          </ChainOfThoughtSearchResult>
        )}
        {meta.warning && (
          <ChainOfThoughtSearchResult className="bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
            {meta.warning}
          </ChainOfThoughtSearchResult>
        )}
        {meta.error && (
          <ChainOfThoughtSearchResult className="bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400">
            {meta.error}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtSearchResults>
      {!hideContent && previewRows.length > 0 && (
        <div className="bg-background/80 mt-2 overflow-hidden rounded-lg border">
          <table className="w-full table-auto text-xs">
            <thead>
              <tr className="bg-muted/50 text-muted-foreground">
                {columns.map((col) => (
                  <th
                    key={col}
                    className="max-w-[12rem] truncate px-3 py-1.5 text-left font-medium"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {previewRows.map((row, i) => (
                <tr key={i}>
                  {columns.map((col) => {
                    const val = row[col];
                    const display =
                      val == null
                        ? ""
                        : typeof val === "string"
                          ? val
                          : JSON.stringify(val);
                    return (
                      <td
                        key={col}
                        className="max-w-[12rem] truncate px-3 py-1.5"
                      >
                        {display.length > 24
                          ? display.slice(0, 24) + "..."
                          : display}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <button
            className="text-muted-foreground hover:text-foreground hover:bg-muted/60 flex w-full items-center justify-center gap-1 border-t px-3 py-1.5 text-xs transition-colors"
            onClick={handleExpand}
            type="button"
          >
            {remaining > 0
              ? `View all ${data.length} rows`
              : `Expand table`}
            <ChevronRight className="size-3" />
          </button>
        </div>
      )}
    </ChainOfThoughtStep>
  );
}, (prev, next) => {
  // MCP tool call results are immutable once received.
  return prev.id === next.id
    && prev.name === next.name
    && prev.hideContent === next.hideContent;
});

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
  result?: string | Record<string, unknown>;
}

type CoTStep = CoTReasoningStep | CoTToolCallStep;

function convertToSteps(
  messages: Message[],
  resultCache: Map<string, unknown>,
): CoTStep[] {
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
          // Use cached parsed result when available to skip
          // O(n) findToolCallResult scan + JSON.parse
          const cached = resultCache.get(toolCallId);
          if (cached !== undefined) {
            step.result = cached as string | Record<string, unknown>;
          } else {
            const toolCallResult = findToolCallResult(toolCallId, messages);
            if (toolCallResult) {
              try {
                const json = JSON.parse(toolCallResult);
                step.result = json;
                resultCache.set(toolCallId, json);
              } catch {
                step.result = toolCallResult;
                resultCache.set(toolCallId, toolCallResult);
              }
            }
          }
        }
        steps.push(step);
      }
    }
  }
  return steps;
}
