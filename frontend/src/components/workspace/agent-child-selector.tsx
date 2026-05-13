"use client";

import { BotIcon } from "lucide-react";

import { type Agent } from "@/core/agents";
import { cn } from "@/lib/utils";

interface AgentChildSelectorProps {
  agents: Agent[];
  onSelect: (agent: Agent) => void;
}

export function AgentChildSelector({
  agents,
  onSelect,
}: AgentChildSelectorProps) {
  if (agents.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-3 px-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
      {agents.map((agent) => (
        <button
          key={agent.name}
          type="button"
          onClick={() => onSelect(agent)}
          className={cn(
            "flex flex-col items-start gap-2 rounded-lg border p-4",
            "hover:bg-accent hover:border-accent-foreground/20",
            "transition-colors text-left cursor-pointer",
          )}
        >
          <span className="text-2xl">
            {agent.icon ?? <BotIcon className="size-6" />}
          </span>
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">
              {agent.display_name ?? agent.name}
            </span>
            {agent.description && (
              <span className="text-xs text-muted-foreground line-clamp-2">
                {agent.description}
              </span>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}
