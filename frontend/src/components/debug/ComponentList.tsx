"use client";

import { BugIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface ComponentListProps {
  components: string[];
  selected: string;
  onSelect: (component: string) => void;
}

export function ComponentList({ components, selected, onSelect }: ComponentListProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-3">
        <h2 className="text-sm font-semibold">A2UI 组件</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {components.length} 个已注册组件
        </p>
      </div>
      <div className="flex-1 overflow-auto p-2">
        {components.map((name) => (
          <button
            key={name}
            onClick={() => onSelect(name)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
              selected === name
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <BugIcon className="size-4 shrink-0" />
            <span className="truncate font-mono text-xs">{name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
