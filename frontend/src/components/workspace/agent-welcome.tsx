"use client";

import { BotIcon } from "lucide-react";

import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import { type Agent } from "@/core/agents";
import { cn } from "@/lib/utils";

export function AgentWelcome({
  className,
  agent,
  agentName,
  onStarterClick,
}: {
  className?: string;
  agent: Agent | null | undefined;
  agentName: string;
  onStarterClick?: (prompt: string) => void;
}) {
  const displayName = agent?.display_name ?? agent?.name ?? agentName;
  const description = agent?.description;
  const icon = agent?.icon;

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="bg-primary/10 flex h-12 w-12 items-center justify-center rounded-full">
        {icon ? (
          <span className="text-2xl">{icon}</span>
        ) : (
          <BotIcon className="text-primary h-6 w-6" />
        )}
      </div>
      <div className="text-2xl font-bold">{displayName}</div>
      {description && (
        <p className="text-muted-foreground max-w-sm text-sm">{description}</p>
      )}
      {agent?.starters && agent.starters.length > 0 && (
        <Suggestions className="mt-2 justify-center">
          {agent.starters.map((s) => (
            <Suggestion
              key={s.label}
              suggestion={s.label}
              onClick={() => onStarterClick?.(s.prompt)}
            />
          ))}
        </Suggestions>
      )}
    </div>
  );
}
