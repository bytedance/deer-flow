"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  DatabaseIcon,
  FolderIcon,
  LayersIcon,
  LoaderIcon,
  TableIcon,
} from "lucide-react";
import { useState } from "react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { useTeableConfig } from "@/core/teable/hooks";
import {
  useTeableBases,
  useTeableSpaces,
  useTeableTables,
} from "@/core/teable/hooks";
import { cn } from "@/lib/utils";

function TreeItem({
  icon,
  label,
  depth,
  isExpanded,
  isSelected,
  isLoading,
  onToggle,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  depth: number;
  isExpanded?: boolean;
  isSelected?: boolean;
  isLoading?: boolean;
  onToggle?: () => void;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-1.5 border-b px-2 py-2 text-left text-sm transition-colors",
        "hover:bg-accent",
        isSelected && "bg-accent font-medium",
      )}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      onClick={onClick ?? onToggle}
    >
      {onToggle ? (
        <button
          type="button"
          className="hover:bg-muted shrink-0 rounded p-0.5"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
        >
          {isLoading ? (
            <LoaderIcon className="h-3.5 w-3.5 animate-spin" />
          ) : isExpanded ? (
            <ChevronDownIcon className="h-3.5 w-3.5" />
          ) : (
            <ChevronRightIcon className="h-3.5 w-3.5" />
          )}
        </button>
      ) : (
        <span className="w-5" />
      )}
      <span className="text-muted-foreground shrink-0">{icon}</span>
      <span className="truncate">{label}</span>
    </button>
  );
}

function BaseNode({
  baseId,
  baseName,
  selectedTableId,
  defaultExpanded,
  onSelectTable,
}: {
  baseId: string;
  baseName: string;
  selectedTableId: string | null;
  defaultExpanded: boolean;
  onSelectTable: (tableId: string, tableName: string) => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { data: tables, isLoading } = useTeableTables(expanded ? baseId : null);

  return (
    <>
      <TreeItem
        icon={<DatabaseIcon className="h-4 w-4" />}
        label={baseName}
        depth={1}
        isExpanded={expanded}
        isLoading={isLoading}
        onToggle={() => setExpanded(!expanded)}
      />
      {expanded &&
        tables?.map((table) => (
          <TreeItem
            key={table.id}
            icon={<TableIcon className="h-4 w-4" />}
            label={table.name}
            depth={2}
            isSelected={selectedTableId === table.id}
            onClick={() => onSelectTable(table.id, table.name)}
          />
        ))}
    </>
  );
}

function SpaceNode({
  spaceId,
  spaceName,
  selectedTableId,
  defaultBaseId,
  onSelectTable,
}: {
  spaceId: string;
  spaceName: string;
  selectedTableId: string | null;
  defaultBaseId: string;
  onSelectTable: (tableId: string, tableName: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const { data: bases, isLoading } = useTeableBases(expanded ? spaceId : null);

  return (
    <>
      <TreeItem
        icon={<FolderIcon className="h-4 w-4" />}
        label={spaceName}
        depth={0}
        isExpanded={expanded}
        isLoading={isLoading}
        onToggle={() => setExpanded(!expanded)}
      />
      {expanded &&
        bases?.map((base) => (
          <BaseNode
            key={base.id}
            baseId={base.id}
            baseName={base.name}
            selectedTableId={selectedTableId}
            defaultExpanded={base.id === defaultBaseId}
            onSelectTable={onSelectTable}
          />
        ))}
    </>
  );
}

export function TableResourceList({
  className,
  selectedTableId,
  onSelectTable,
}: {
  className?: string;
  selectedTableId: string | null;
  onSelectTable: (tableId: string, tableName: string) => void;
}) {
  const { data: config } = useTeableConfig();
  const defaultBaseId = config?.base_id ?? "";
  const { data: spaces, isLoading, error } = useTeableSpaces();

  if (isLoading) {
    return (
      <div
        className={cn("flex size-full items-center justify-center", className)}
      >
        <LoaderIcon className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className={cn(
          "flex size-full items-center justify-center p-4",
          className,
        )}
      >
        <ConversationEmptyState
          icon={<LayersIcon />}
          title="Failed to load"
          description={error.message}
        />
      </div>
    );
  }

  if (!spaces?.length) {
    return (
      <div
        className={cn(
          "flex size-full items-center justify-center p-4",
          className,
        )}
      >
        <ConversationEmptyState
          icon={<LayersIcon />}
          title="No spaces"
          description="No Teable spaces found"
        />
      </div>
    );
  }

  return (
    <div className={cn("flex size-full flex-col overflow-hidden", className)}>
      <header className="border-b px-3 py-2">
        <h3 className="text-sm font-medium">Resources</h3>
      </header>
      <div className="min-h-0 grow overflow-y-auto">
        {spaces.map((space) => (
          <SpaceNode
            key={space.id}
            spaceId={space.id}
            spaceName={space.name}
            selectedTableId={selectedTableId}
            defaultBaseId={defaultBaseId}
            onSelectTable={onSelectTable}
          />
        ))}
      </div>
    </div>
  );
}
