import type { Message } from "@langchain/langgraph-sdk";
import {
  BookOpenTextIcon,
  ChevronUp,
  CoinsIcon,
  FolderOpenIcon,
  GlobeIcon,
  LightbulbIcon,
  ListTodoIcon,
  MessageCircleQuestionMarkIcon,
  NotebookPenIcon,
  SearchIcon,
  SquareTerminalIcon,
  WrenchIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

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
import { formatTokenCount } from "@/core/messages/usage";
import type { TokenDebugStep } from "@/core/messages/usage-model";
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
  tokenDebugSteps = [],
  showTokenDebugSummaries = false,
}: {
  className?: string;
  messages: Message[];
  isLoading?: boolean;
  tokenDebugSteps?: TokenDebugStep[];
  showTokenDebugSummaries?: boolean;
}) {
  const { t } = useI18n();
  const [showAbove, setShowAbove] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [showLastThinking, setShowLastThinking] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const steps = useMemo(() => convertToSteps(messages), [messages]);
  const debugStepByMessageId = useMemo(
    () =>
      new Map(
        tokenDebugSteps.map(
          (step) => [step.messageId || step.id, step] as const,
        ),
      ),
    [tokenDebugSteps],
  );
  const toolCallCountByMessageId = useMemo(() => {
    const counts = new Map<string, number>();

    for (const step of steps) {
      if (step.type !== "toolCall" || !step.messageId) {
        continue;
      }

      counts.set(step.messageId, (counts.get(step.messageId) ?? 0) + 1);
    }

    return counts;
  }, [steps]);
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
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const firstEligibleDebugSummaryStepIndexByMessageId = useMemo(() => {
    const firstIndices = new Map<string, number>();

    if (!showTokenDebugSummaries) {
      return firstIndices;
    }

    for (const [index, step] of steps.entries()) {
      const messageId = step.messageId;
      if (!messageId || firstIndices.has(messageId)) {
        continue;
      }

      const debugStep = debugStepByMessageId.get(messageId);
      if (!debugStep) {
        continue;
      }

      const toolCallCount = toolCallCountByMessageId.get(messageId) ?? 0;
      if (!debugStep.sharedAttribution && toolCallCount > 0) {
        continue;
      }
      if (
        !debugStep.sharedAttribution &&
        toolCallCount === 0 &&
        debugStep.label === t.common.thinking &&
        debugStep.secondaryLabels.length === 0
      ) {
        continue;
      }

      firstIndices.set(messageId, index);
    }

    return firstIndices;
  }, [
    debugStepByMessageId,
    showTokenDebugSummaries,
    steps,
    t.common.thinking,
    toolCallCountByMessageId,
  ]);

  const renderDebugSummary = (
    messageId: string | undefined,
    stepIndex: number,
  ) => {
    if (!showTokenDebugSummaries || !messageId) {
      return null;
    }

    const debugStep = debugStepByMessageId.get(messageId);
    if (!debugStep) {
      return null;
    }
    if (
      firstEligibleDebugSummaryStepIndexByMessageId.get(messageId) !== stepIndex
    ) {
      return null;
    }

    return (
      <ChainOfThoughtStep
        key={`token-debug-${messageId}`}
        icon={CoinsIcon}
        label={
          <DebugStepLabel
            label={debugStep.label}
            token={formatDebugToken(debugStep, t)}
          />
        }
        description={
          debugStep.sharedAttribution
            ? t.tokenUsage.sharedAttribution
            : undefined
        }
      >
        {debugStep.secondaryLabels.length > 0 && (
          <ChainOfThoughtSearchResults>
            {debugStep.secondaryLabels.map((label, index) => (
              <ChainOfThoughtSearchResult
                key={`${debugStep.id}-${index}-${label}`}
              >
                {label}
              </ChainOfThoughtSearchResult>
            ))}
          </ChainOfThoughtSearchResults>
        )}
      </ChainOfThoughtStep>
    );
  };

  const renderToolCall = (
    step: CoTToolCallStep,
    options?: { isLast?: boolean },
  ) => {
    const debugStep =
      showTokenDebugSummaries && step.messageId
        ? debugStepByMessageId.get(step.messageId)
        : undefined;

    return (
      <ToolCall
        key={step.id}
        {...step}
        isLast={options?.isLast}
        isLoading={isLoading}
        tokenDebugStep={
          debugStep && !debugStep.sharedAttribution ? debugStep : undefined
        }
      />
    );
  };

  const lastReasoningDebugStep =
    showTokenDebugSummaries && lastReasoningStep?.messageId
      ? debugStepByMessageId.get(lastReasoningStep.messageId)
      : undefined;

  return (
    <ChainOfThought
      className={cn("w-full gap-2 rounded-lg border p-0.5", className)}
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
                  showAbove ? "rotate-180" : "",
                )}
              />
            }
          ></ChainOfThoughtStep>
        </Button>
      )}
      {lastToolCallStep && (
        <ChainOfThoughtContent className="px-4 pb-2">
          {showAbove &&
            aboveLastToolCallSteps.flatMap((step) => {
              const stepIndex = steps.indexOf(step);
              if (step.type === "reasoning") {
                return [
                  renderDebugSummary(step.messageId, stepIndex),
                  <ChainOfThoughtStep
                    key={step.id}
                    label={
                      <MarkdownContent
                        content={step.reasoning ?? ""}
                        isLoading={isLoading}
                        rehypePlugins={rehypePlugins}
                      />
                    }
                  ></ChainOfThoughtStep>,
                ];
              }

              return [
                renderDebugSummary(step.messageId, stepIndex),
                renderToolCall(step),
              ];
            })}
          {renderDebugSummary(
            lastToolCallStep.messageId,
            steps.indexOf(lastToolCallStep),
          )}
          {lastToolCallStep && (
            <FlipDisplay uniqueKey={lastToolCallStep.id ?? ""}>
              {renderToolCall(lastToolCallStep, { isLast: true })}
            </FlipDisplay>
          )}
        </ChainOfThoughtContent>
      )}
      {lastReasoningStep && (
        <>
          {renderDebugSummary(
            lastReasoningStep.messageId,
            steps.indexOf(lastReasoningStep),
          )}
          <Button
            key={lastReasoningStep.id}
            className="w-full items-start justify-start text-left"
            variant="ghost"
            onClick={() => setShowLastThinking(!showLastThinking)}
          >
            <div className="flex w-full items-center justify-between">
              <ChainOfThoughtStep
                className="font-normal"
                label={
                  <DebugStepLabel
                    label={t.common.thinking}
                    token={shouldInlineThinkingToken({
                      debugStep: lastReasoningDebugStep,
                      toolCallCount: lastReasoningStep.messageId
                        ? (toolCallCountByMessageId.get(
                            lastReasoningStep.messageId,
                          ) ?? 0)
                        : 0,
                      enabled: showTokenDebugSummaries,
                      thinkingLabel: t.common.thinking,
                      t,
                    })}
                  />
                }
                icon={LightbulbIcon}
              ></ChainOfThoughtStep>
              <div>
                <ChevronUp
                  className={cn(
                    "text-muted-foreground size-4",
                    showLastThinking ? "" : "rotate-180",
                  )}
                />
              </div>
            </div>
          </Button>
          {showLastThinking && (
            <ChainOfThoughtContent className="px-4 pb-2">
              <ChainOfThoughtStep
                key={lastReasoningStep.id}
                label={
                  <MarkdownContent
                    content={lastReasoningStep.reasoning ?? ""}
                    isLoading={isLoading}
                    rehypePlugins={rehypePlugins}
                  />
                }
              ></ChainOfThoughtStep>
            </ChainOfThoughtContent>
          )}
        </>
      )}
    </ChainOfThought>
  );
}

function formatDebugToken(
  debugStep: TokenDebugStep,
  t: ReturnType<typeof useI18n>["t"],
) {
  return debugStep.usage
    ? `${formatTokenCount(debugStep.usage.totalTokens)} ${t.tokenUsage.label}`
    : t.tokenUsage.unavailableShort;
}

function shouldInlineThinkingToken({
  debugStep,
  toolCallCount,
  enabled,
  thinkingLabel,
  t,
}: {
  debugStep?: TokenDebugStep;
  toolCallCount: number;
  enabled: boolean;
  thinkingLabel: string;
  t: ReturnType<typeof useI18n>["t"];
}) {
  if (
    !enabled ||
    !debugStep ||
    debugStep.sharedAttribution ||
    toolCallCount > 0 ||
    debugStep.label !== thinkingLabel
  ) {
    return null;
  }

  return formatDebugToken(debugStep, t);
}

function DebugStepLabel({
  label,
  token,
}: {
  label: React.ReactNode;
  token?: string | null;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0 flex-1">{label}</div>
      {token ? (
        <div className="text-muted-foreground shrink-0 font-mono text-[11px]">
          {token}
        </div>
      ) : null}
    </div>
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
  tokenDebugStep,
}: {
  id?: string;
  messageId?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string | Record<string, unknown>;
  isLast?: boolean;
  isLoading?: boolean;
  tokenDebugStep?: TokenDebugStep;
}) {
  const { t } = useI18n();
  const { setOpen, autoOpen, autoSelect, selectedArtifact, select } =
    useArtifacts();
  const tokenLabel = tokenDebugStep
    ? formatDebugToken(tokenDebugStep, t)
    : null;
  const resolveLabel = (fallback: React.ReactNode) =>
    tokenDebugStep ? (
      <DebugStepLabel label={tokenDebugStep.label} token={tokenLabel} />
    ) : (
      fallback
    );

  if (name === "web_search") {
    let label: React.ReactNode = t.toolCalls.searchForRelatedInfo;
    if (typeof args.query === "string") {
      label = t.toolCalls.searchOnWebFor(args.query);
    }
    return (
      <ChainOfThoughtStep
        key={id}
        label={resolveLabel(label)}
        icon={SearchIcon}
      >
        {Array.isArray(result) && (
          <ChainOfThoughtSearchResults>
            {result.map((item) => (
              <ChainOfThoughtSearchResult key={item.url}>
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.title}
                </a>
              </ChainOfThoughtSearchResult>
            ))}
          </ChainOfThoughtSearchResults>
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
        label={resolveLabel(label)}
        icon={SearchIcon}
      >
        {Array.isArray(results) && (
          <ChainOfThoughtSearchResults>
            {Array.isArray(results) &&
              results.map((item) => (
                <Tooltip key={item.image_url} content={item.title}>
                  <a
                    className="size-24 overflow-hidden rounded-lg object-cover"
                    href={item.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
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
        label={resolveLabel(t.toolCalls.viewWebPage)}
        icon={GlobeIcon}
      >
        <ChainOfThoughtSearchResult>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="cursor-pointer"
            >
              {title}
            </a>
          )}
        </ChainOfThoughtSearchResult>
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
        label={resolveLabel(description)}
        icon={FolderOpenIcon}
      >
        {path && (
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
        label={resolveLabel(description)}
        icon={BookOpenTextIcon}
      >
        {path && (
          <ChainOfThoughtSearchResult className="cursor-pointer">
            {path}
          </ChainOfThoughtSearchResult>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "write_file" || name === "str_replace") {
    let description: string | undefined = (args as { description: string })
      ?.description;
    if (!description) {
      description = t.toolCalls.writeFile;
    }
    const path: string | undefined = (args as { path: string })?.path;
    if (isLoading && isLast && autoOpen && autoSelect && path && !result) {
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
        label={resolveLabel(description)}
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
        {path && (
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
      return (
        <ChainOfThoughtStep
          key={id}
          label={resolveLabel(t.toolCalls.executeCommand)}
          icon={SquareTerminalIcon}
        />
      );
    }
    const command: string | undefined = (args as { command: string })?.command;
    return (
      <ChainOfThoughtStep
        key={id}
        label={resolveLabel(description)}
        icon={SquareTerminalIcon}
      >
        {command && (
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
        label={resolveLabel(t.toolCalls.needYourHelp)}
        icon={MessageCircleQuestionMarkIcon}
      ></ChainOfThoughtStep>
    );
  } else if (name === "write_todos") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={resolveLabel(t.toolCalls.writeTodos)}
        icon={ListTodoIcon}
      ></ChainOfThoughtStep>
    );
  } else {
    const description: string | undefined = (args as { description: string })
      ?.description;
    return (
      <ChainOfThoughtStep
        key={id}
        label={resolveLabel(description ?? t.toolCalls.useTool(name))}
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
          reasoning,
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
