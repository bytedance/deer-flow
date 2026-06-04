"use client";

import { BotIcon } from "@/components/ui/icons";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
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

  // Allow ESC to dismiss — standard popover behavior.
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open || agents.length === 0) return null;

  function handleSelect(agent: Agent) {
    onClose();
    if (onSelect) {
      onSelect(agent);
    } else {
      router.push(`/workspace/agents/${agent.name}/chats/new`);
    }
  }

  // Adaptive grid: 1 child = 1 col, 2-3 children = N cols, 4+ = 2 rows of up to 3.
  // Avoids the empty 4th column that read as "missing card" when only 3 agents exist.
  const columnsClass =
    agents.length <= 1
      ? "grid-cols-1"
      : agents.length === 2
        ? "grid-cols-2"
        : "grid-cols-3";

  // Width follows the column count so individual cards stay readable (~200px wide).
  const widthClass =
    agents.length <= 1
      ? "max-w-sm"
      : agents.length === 2
        ? "max-w-md"
        : "max-w-2xl";

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="bg-background/60 absolute inset-0 backdrop-blur-sm" />
      <div
        className={cn(
          "border-border/60 bg-card text-card-foreground relative z-10 w-full rounded-xl border p-6 shadow-2xl",
          "animate-in fade-in slide-in-from-bottom-2 duration-200",
          widthClass,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="mb-5">
            <h3 className="text-foreground text-base font-semibold tracking-tight">
              {title}
            </h3>
            {description && (
              <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
                {description}
              </p>
            )}
          </div>
        )}
        <div className={cn("grid gap-3", columnsClass)}>
          {agents.map((agent) => (
            <button
              key={agent.name}
              type="button"
              onClick={() => handleSelect(agent)}
              className={cn(
                "border-border/60 bg-background hover:bg-accent hover:border-primary/40",
                "focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none",
                "flex cursor-pointer flex-col items-start gap-3 rounded-lg border p-4 text-left transition-colors",
              )}
            >
              <span className="text-2xl leading-none">
                {agent.icon ?? <BotIcon className="size-6" />}
              </span>
              <div className="flex flex-col gap-1">
                <span className="text-foreground text-sm font-semibold">
                  {agent.display_name ?? agent.name}
                </span>
                {agent.description && (
                  <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
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
