"use client";

import { BotIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { createPortal } from "react-dom";

import { type Agent } from "@/core/agents";
import { cn } from "@/lib/utils";

interface AgentChildSelectorProps {
  open: boolean;
  agents: Agent[];
  title?: string;
  description?: string;
  onSelect?: (agent: Agent) => void;
  onClose: () => void;
}

export function AgentChildSelector({
  open,
  agents,
  title,
  description,
  onSelect,
  onClose,
}: AgentChildSelectorProps) {
  const router = useRouter();

  if (!open || agents.length === 0) return null;

  function handleSelect(agent: Agent) {
    onClose();
    if (onSelect) {
      onSelect(agent);
    } else {
      router.push(`/workspace/agents/${agent.name}/chats/new`);
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/20" />
      <div
        className={cn(
          "relative z-10 w-full max-w-2xl mb-8 mx-4",
          "animate-in slide-in-from-bottom-4 fade-in duration-300",
          "rounded-xl border bg-background p-6 shadow-xl",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="mb-4">
            <h3 className="text-base font-semibold">{title}</h3>
            {description && (
              <p className="text-muted-foreground mt-1 text-sm">
                {description}
              </p>
            )}
          </div>
        )}
        <div className="grid grid-cols-4 gap-3">
          {agents.map((agent) => (
            <button
              key={agent.name}
              type="button"
              onClick={() => handleSelect(agent)}
              className={cn(
                "flex flex-col items-center gap-2 rounded-lg border p-4",
                "hover:bg-accent hover:border-accent-foreground/20",
                "transition-colors cursor-pointer text-center",
              )}
            >
              <span className="text-3xl">
                {agent.icon ?? <BotIcon className="size-7" />}
              </span>
              <div className="flex flex-col items-center gap-0.5">
                <span className="text-sm font-medium">
                  {agent.display_name ?? agent.name}
                </span>
                {agent.description && (
                  <span className="text-muted-foreground line-clamp-1 text-xs">
                    {agent.description}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
