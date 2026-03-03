import { ChevronUpIcon, LayersIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAgentContext } from "@/core/agent/hooks";
import { cn } from "@/lib/utils";

import {
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
} from "../ai-elements/queue";

type ContextPanelProps = {
  className?: string;
  modelName?: string;
  subagentEnabled?: boolean;
};

export function ContextPanel({
  className,
  modelName,
  subagentEnabled,
}: ContextPanelProps) {
  const [collapsed, setCollapsed] = useState(true);
  const { context, isLoading, error } = useAgentContext({
    modelName,
    subagentEnabled,
  });
  const tools = useMemo(() => context?.tools ?? [], [context?.tools]);
  const skills = useMemo(() => context?.skills ?? [], [context?.skills]);
  const statusLabel = useMemo(() => {
    if (isLoading) {
      return "Loading…";
    }
    if (error) {
      return "Unavailable";
    }
    return `${tools.length} tools · ${skills.length} skills`;
  }, [error, isLoading, skills.length, tools.length]);

  return (
    <div
      className={cn(
        "bg-sidebar flex w-full flex-col gap-2 rounded-lg border p-0.5",
        className,
      )}
    >
      <header className="flex min-h-8 items-center justify-between px-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <LayersIcon className="size-4" />
          <span>Context</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span>{statusLabel}</span>
          <Button
            className="text-muted-foreground size-6"
            size="icon-sm"
            type="button"
            variant="ghost"
            onClick={() => setCollapsed(!collapsed)}
          >
            <ChevronUpIcon
              className={cn(
                "size-4 transition-transform duration-300 ease-out",
                collapsed ? "" : "rotate-180",
              )}
            />
          </Button>
        </div>
      </header>
      <main
        className={cn(
          "px-2 transition-all duration-300 ease-out",
          collapsed ? "h-0 pb-2" : "h-40 pb-3",
        )}
      >
        <ScrollArea className="h-full pr-2">
          {isLoading ? (
            <div className="px-1 pb-2 text-xs text-muted-foreground">
              Loading context…
            </div>
          ) : error ? (
            <div className="px-1 pb-2 text-xs text-destructive">
              Failed to load context
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">
                  Tools
                </div>
                {tools.length === 0 ? (
                  <div className="px-1 text-xs text-muted-foreground">
                    No tools loaded
                  </div>
                ) : (
                  <ul className="space-y-1">
                    {tools.map((tool) => (
                      <QueueItem key={tool.name}>
                        <div className="flex items-start gap-2">
                          <QueueItemIndicator className="shrink-0" />
                          <QueueItemContent className="line-clamp-none whitespace-normal">
                            {tool.name}
                          </QueueItemContent>
                        </div>
                      </QueueItem>
                    ))}
                  </ul>
                )}
              </div>
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">
                  Skills
                </div>
                {skills.length === 0 ? (
                  <div className="px-1 text-xs text-muted-foreground">
                    No skills enabled
                  </div>
                ) : (
                  <ul className="space-y-1">
                    {skills.map((skill) => (
                      <QueueItem key={skill.name}>
                        <div className="flex items-start gap-2">
                          <QueueItemIndicator className="shrink-0" />
                          <QueueItemContent className="line-clamp-none whitespace-normal">
                            {skill.name}
                          </QueueItemContent>
                        </div>
                      </QueueItem>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </ScrollArea>
      </main>
    </div>
  );
}
