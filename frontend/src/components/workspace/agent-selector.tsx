"use client";

import { BotIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";


import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useGroupedAgents } from "@/core/agents";
import { type Agent } from "@/core/agents/types";
import { cn } from "@/lib/utils";

interface AgentSelectorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (agent: Agent) => void;
  selectedAgent?: string | null;
}

export function AgentSelector({
  open,
  onOpenChange,
  onSelect,
  selectedAgent,
}: AgentSelectorProps) {
  const { groups, isLoading } = useGroupedAgents();
  const [search, setSearch] = useState("");

  const filteredGroups = useMemo(() => {
    if (!search) return groups;
    const lower = search.toLowerCase();
    return groups
      .map((group) => ({
        ...group,
        agents: group.agents.filter(
          (a) =>
            a.name.toLowerCase().includes(lower) ||
            (a.display_name?.toLowerCase().includes(lower) ?? false) ||
            a.description.toLowerCase().includes(lower) ||
            (a.tags?.some((t) => t.toLowerCase().includes(lower)) ?? false),
        ),
      }))
      .filter((g) => g.agents.length > 0);
  }, [groups, search]);

  const handleSelect = useCallback(
    (agent: Agent) => {
      onSelect(agent);
      onOpenChange(false);
    },
    [onSelect, onOpenChange],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg p-0">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle className="text-base font-medium">
            Select Agent
          </DialogTitle>
        </DialogHeader>
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search agents..."
            value={search}
            onValueChange={setSearch}
          />
          <CommandList className="max-h-80">
            {isLoading && (
              <div className="text-muted-foreground py-6 text-center text-sm">
                Loading agents...
              </div>
            )}
            <CommandEmpty>No agents found.</CommandEmpty>
            {filteredGroups.map((group) => (
              <CommandGroup key={group.source} heading={group.label}>
                {group.agents.map((agent) => (
                  <CommandItem
                    key={agent.name}
                    value={agent.name}
                    onSelect={() => handleSelect(agent)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2",
                      selectedAgent === agent.name && "bg-accent",
                    )}
                    disabled={!agent.enabled}
                  >
                    <div className="bg-primary/10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
                      <BotIcon className="text-primary h-4 w-4" />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm font-medium">
                        {agent.display_name ?? agent.name}
                      </span>
                      {agent.description && (
                        <span className="text-muted-foreground truncate text-xs">
                          {agent.description}
                        </span>
                      )}
                    </div>
                    {agent.tags && agent.tags.length > 0 && (
                      <div className="flex shrink-0 gap-1">
                        {agent.tags.slice(0, 2).map((tag) => (
                          <span
                            key={tag}
                            className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[10px]"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
