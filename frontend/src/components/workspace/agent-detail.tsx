"use client";

import { BotIcon, CopyIcon, PencilIcon } from "lucide-react";

import { type Agent } from "@/core/agents/types";
import { cn } from "@/lib/utils";

interface AgentDetailProps {
  agent: Agent;
  className?: string;
  onFork?: () => void;
  onEdit?: () => void;
}

export function AgentDetail({
  agent,
  className,
  onFork,
  onEdit,
}: AgentDetailProps) {
  return (
    <div className={cn("flex flex-col gap-4 p-4", className)}>
      <div className="flex items-start gap-4">
        <div className="bg-primary/10 flex h-12 w-12 shrink-0 items-center justify-center rounded-full">
          <BotIcon className="text-primary h-6 w-6" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-lg font-semibold">
            {agent.display_name ?? agent.name}
          </h2>
          {agent.description && (
            <p className="text-muted-foreground text-sm">{agent.description}</p>
          )}
          <div className="text-muted-foreground flex items-center gap-2 text-xs">
            <span className="bg-muted rounded px-1.5 py-0.5">
              {agent.source}
            </span>
            {!agent.enabled && (
              <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">
                disabled
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1">
          {!agent.editable && onFork && (
            <button
              onClick={onFork}
              className="text-muted-foreground hover:text-foreground rounded p-1.5"
              title="Fork to my agents"
            >
              <CopyIcon className="h-4 w-4" />
            </button>
          )}
          {agent.editable && onEdit && (
            <button
              onClick={onEdit}
              className="text-muted-foreground hover:text-foreground rounded p-1.5"
              title="Edit agent"
            >
              <PencilIcon className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {agent.tags && agent.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {agent.tags.map((tag) => (
            <span
              key={tag}
              className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-xs"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-sm">
        {agent.model && (
          <div>
            <span className="text-muted-foreground text-xs">Model</span>
            <p className="font-mono text-xs">{agent.model}</p>
          </div>
        )}
        {agent.tool_groups && agent.tool_groups.length > 0 && (
          <div>
            <span className="text-muted-foreground text-xs">Tool Groups</span>
            <p className="text-xs">{agent.tool_groups.join(", ")}</p>
          </div>
        )}
        {agent.skills && agent.skills.length > 0 && (
          <div>
            <span className="text-muted-foreground text-xs">Skills</span>
            <p className="text-xs">{agent.skills.join(", ")}</p>
          </div>
        )}
        {agent.mcp_servers && agent.mcp_servers.length > 0 && (
          <div>
            <span className="text-muted-foreground text-xs">MCP Servers</span>
            <p className="text-xs">{agent.mcp_servers.join(", ")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
