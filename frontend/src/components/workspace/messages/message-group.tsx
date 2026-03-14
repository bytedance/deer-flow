import type { Message } from "@langchain/langgraph-sdk";
import {
  BarChart3Icon,
  BookOpenTextIcon,
  CheckCircle2Icon,
  ChevronRight,
  ClockIcon,
  ChevronUp,
  DatabaseIcon,
  FolderOpenIcon,
  GlobeIcon,
  ImageIcon,
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
  getToolDisplayCategory,
  getToolIconHint,
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

function buildFaviconCandidates(url: string): string[] {
  try {
    const parsed = new URL(url);
    const hostname = parsed.hostname;
    const origin = parsed.origin;
    const candidates = [
      `${origin}/favicon.ico`,
      `https://icons.duckduckgo.com/ip3/${hostname}.ico`,
      `https://www.google.com/s2/favicons?domain=${hostname}&sz=32`,
    ];
    return [...new Set(candidates)];
  } catch {
    return [];
  }
}

function SearchResultFavicon({ url }: { url: string }) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const candidates = useMemo(() => buildFaviconCandidates(url), [url]);

  useEffect(() => {
    setSourceIndex(0);
  }, [url]);

  if (sourceIndex >= candidates.length) {
    return <GlobeIcon className="text-muted-foreground size-4 shrink-0" />;
  }

  const src = candidates[sourceIndex];
  if (!src) {
    return <GlobeIcon className="text-muted-foreground size-4 shrink-0" />;
  }

  return (
    <img
      alt=""
      aria-hidden="true"
      className="size-4 shrink-0 rounded-[2px]"
      loading="lazy"
      onError={() => {
        setSourceIndex((prev) => prev + 1);
      }}
      src={src}
    />
  );
}

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
  const lastReasoningStepIndex = useMemo(() => {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i]?.type === "reasoning") {
        return i;
      }
    }
    return -1;
  }, [steps]);
  const lastReasoningStep = useMemo(() => {
    if (lastReasoningStepIndex < 0) {
      return null;
    }
    const step = steps[lastReasoningStepIndex];
    if (!step || step.type !== "reasoning") {
      return null;
    }
    return step;
  }, [lastReasoningStepIndex, steps]);
  const primarySteps = useMemo(() => {
    if (lastReasoningStepIndex < 0) {
      return steps;
    }
    return steps.filter((_, index) => index !== lastReasoningStepIndex);
  }, [lastReasoningStepIndex, steps]);
  const lastToolCallStep = useMemo(() => {
    const filteredSteps = primarySteps.filter((step) => step.type === "toolCall");
    return filteredSteps[filteredSteps.length - 1];
  }, [primarySteps]);
  const aboveLastToolCallSteps = useMemo(() => {
    if (lastToolCallStep) {
      const index = primarySteps.indexOf(lastToolCallStep);
      return primarySteps.slice(0, index);
    }
    return [];
  }, [lastToolCallStep, primarySteps]);
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
  const showDoneStep = !isLoading && primarySteps.length > 0;
  const hasPrimaryContainerContent = (
    aboveLastToolCallSteps.length > 0 ||
    Boolean(lastToolCallStep) ||
    showDoneStep
  );
  return (
    <div className={cn("w-full space-y-2", className)}>
      {hasPrimaryContainerContent && (
        <ChainOfThought
          className="bg-background/50 w-full gap-2 rounded-lg border p-0.5"
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
                showConnector={false}
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
                        label={step.title ?? t.common.thinking}
                      >
                        <MarkdownContent
                          content={step.body ?? ""}
                          isLoading={isLoading}
                          rehypePlugins={rehypePlugins}
                        />
                      </ChainOfThoughtStep>
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
          {showDoneStep && (
            <div className="px-4 pb-2">
              <ChainOfThoughtStep
                className="my-0"
                icon={
                  <CheckCircle2Icon className="text-emerald-500 dark:text-emerald-400 size-4" />
                }
                label={t.toolCalls.done}
                showConnector={false}
              />
            </div>
          )}
        </ChainOfThought>
      )}
      {lastReasoningStep && (
        <div className="bg-background/50 w-full rounded-lg border p-0.5">
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
              <div className="text-muted-foreground flex items-center gap-2 text-sm">
                <LightbulbIcon className="size-4" />
                <span>{t.common.thinking}</span>
              </div>
              <ChevronUp
                className={cn(
                  "text-muted-foreground size-4 transition-transform duration-200",
                  showThinking ? "" : "rotate-180",
                )}
              />
            </div>
          </Button>
          {showThinking && (
            <div
              ref={thinkingScrollRef}
              className="mt-3 max-h-[36rem] overflow-y-auto px-4 pb-3 pr-6"
            >
              <div className="text-[rgb(108,107,98)] dark:text-[rgb(175,174,163)] flex gap-2 text-sm">
                <div className="relative mt-0.5">
                  <ClockIcon className="size-4" />
                  <div className="bg-border absolute top-5 -bottom-4 left-1/2 w-[2px] min-h-2 -translate-x-1/2" />
                </div>
                <div className="min-w-0 flex-1 overflow-hidden">
                  <MarkdownContent
                    content={lastReasoningStep.body ?? lastReasoningStep.reasoning ?? ""}
                    isLoading={isLoading}
                    rehypePlugins={rehypePlugins}
                    className="text-[rgb(108,107,98)] text-sm dark:text-[rgb(175,174,163)]"
                  />
                </div>
              </div>
            </div>
          )}
          {!isLoading && (
            <div className="px-4 pb-2">
              <ChainOfThoughtStep
                className="my-0"
                icon={
                  <CheckCircle2Icon className="text-emerald-500 dark:text-emerald-400 size-4" />
                }
                label={t.toolCalls.done}
                showConnector={false}
              />
            </div>
          )}
        </div>
      )}
    </div>
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

export const ToolCall = memo(function ToolCall({
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
  const displayCategory = getToolDisplayCategory(name);

  if (displayCategory === "web_search") {
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
    // Normalize search results: built-in web_search returns a flat array,
    // while MCP tools (e.g. firecrawl_search) may wrap results in {web: [...]}.
    const searchResults: { url: string; title: string }[] | undefined =
      Array.isArray(result)
        ? result
        : result && typeof result === "object" && Array.isArray((result as Record<string, unknown>).web)
          ? (result as Record<string, unknown>).web as { url: string; title: string }[]
          : undefined;
    return (
      <ChainOfThoughtStep
        key={id}
        label={label}
        icon={SearchIcon}
      >
        {!hideContent && searchResults && (
          <div className="bg-background/80 mt-2 overflow-hidden rounded-lg border">
            <ul className="divide-y divide-border/70">
              {searchResults.map((item) => (
                <li key={item.url}>
                  <a
                    className="group flex items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-muted/60"
                    href={item.url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <SearchResultFavicon url={item.url} />
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
      <ChainOfThoughtStep
        key={id}
        label={label}
        icon={SearchIcon}
      >
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
  } else if (displayCategory === "web_fetch") {
    const url = (args as { url: string })?.url;
    let title = url;
    if (typeof result === "string") {
      const potentialTitle = extractTitleFromMarkdown(result);
      if (potentialTitle && potentialTitle.toLowerCase() !== "untitled") {
        title = potentialTitle;
      }
    } else if (result && typeof result === "object") {
      // MCP tools (e.g. firecrawl_scrape) return metadata with title fields
      const meta = (result as Record<string, unknown>).metadata as Record<string, unknown> | undefined;
      const metaTitle = meta?.ogTitle ?? meta?.["og:title"] ?? meta?.title;
      if (typeof metaTitle === "string" && metaTitle) {
        title = metaTitle;
      }
    }
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.viewWebPage}
        icon={url ? <SearchResultFavicon url={url} /> : GlobeIcon}
      >
        {!hideContent && (
          <ChainOfThoughtSearchResult>
            {url && (
              <a
                className="group flex items-center gap-2"
                href={url}
                target="_blank"
                rel="noreferrer"
              >
                <SearchResultFavicon url={url} />
                <span className="truncate">{title}</span>
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
      <ChainOfThoughtStep
        key={id}
        label={description}
        icon={FolderOpenIcon}
      >
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
      <ChainOfThoughtStep
        key={id}
        label={description}
        icon={BookOpenTextIcon}
      >
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
        label={description}
        icon={NotebookPenIcon}
      >
        {!hideContent && path && (
          <ChainOfThoughtSearchResult
            className="cursor-pointer"
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
  } else if (name === "execute_python") {
    const code: string | undefined = (args as { code: string })?.code;
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.runPython}
        icon={SquareTerminalIcon}
      >
        {!hideContent && code && (
          <CodeBlock
            className="mx-0 cursor-pointer border-none px-0"
            showLineNumbers={false}
            language="python"
            code={code}
          />
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "present_files") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.presentFiles}
        icon={FolderOpenIcon}
      ></ChainOfThoughtStep>
    );
  } else if (name === "view_image") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={t.toolCalls.viewImage}
        icon={ImageIcon}
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
    // Smart fallback: use describeMcpTool for label, pick icon by tool type
    const description: string | undefined = (args as { description: string })
      ?.description;
    const label = description ?? describeMcpTool(name, args, t.toolCalls.useTool(name));
    const iconHint = getToolIconHint(name);
    const icon =
      iconHint === "database" ? DatabaseIcon
        : iconHint === "globe" ? GlobeIcon
          : iconHint === "chart" ? BarChart3Icon
            : WrenchIcon;
    return (
      <ChainOfThoughtStep
        key={id}
        label={label}
        icon={icon}
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

export const McpDataToolCall = memo(function McpDataToolCall({
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
    <ChainOfThoughtStep
      key={id}
      label={label}
      icon={DatabaseIcon}
    >
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

export interface GenericCoTStep<T extends string = string> {
  id?: string;
  messageId?: string;
  type: T;
}

export interface CoTReasoningStep extends GenericCoTStep<"reasoning"> {
  reasoning: string | null;
  title: string | null;
  body: string | null;
}

export interface CoTToolCallStep extends GenericCoTStep<"toolCall"> {
  name: string;
  args: Record<string, unknown>;
  result?: string | Record<string, unknown>;
}

export type CoTStep = CoTReasoningStep | CoTToolCallStep;

export function convertToSteps(
  messages: Message[],
  resultCache: Map<string, unknown>,
): CoTStep[] {
  const steps: CoTStep[] = [];
  for (const message of messages) {
    if (message.type === "ai") {
      const reasoning = extractReasoningContentFromMessage(message);
      if (reasoning) {
        let title: string | null = null;
        let body: string = reasoning;
        const firstLine = reasoning.split("\n")[0]?.trim() ?? "";
        if (firstLine.startsWith("# ")) {
          title = firstLine.slice(2).trim();
          body = reasoning.slice(reasoning.indexOf("\n") + 1).replace(/^\n+/, "");
        } else {
          const breakIdx = reasoning.indexOf("\n\n");
          if (breakIdx > 0) {
            const firstPara = reasoning.slice(0, breakIdx).trim();
            if (firstPara.length > 0 && firstPara.length < 100) {
              title = firstPara;
              body = reasoning.slice(breakIdx).replace(/^\n+/, "");
            }
          }
        }
        // Strip markdown bold/italic markers from the title
        if (title) {
          title = title.replace(/\*+/g, "").trim();
        }
        const step: CoTReasoningStep = {
          id: message.id,
          messageId: message.id,
          type: "reasoning",
          reasoning,
          title,
          body,
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
