"use client";

import { ChevronRightIcon, EyeIcon, EyeOffIcon } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  getTreeNodeVisibilityHandles,
  isTreeNodeHidden,
  isTreeNodeSelected,
  type VsfxTreeNodeData,
} from "./VsfxTreeView";

type VsfxTreeNodeProps = {
  depth: number;
  expandedKeys: Set<string>;
  hiddenHandles: Set<string | number>;
  node: VsfxTreeNodeData;
  nodeKey: string;
  onSelectHandles: (handles: Array<string | number>) => void;
  onToggleExpanded: (nodeKey: string) => void;
  onToggleVisibility: (handles: Array<string | number>, hidden: boolean) => void;
  onZoomToSelection: () => void;
  registerNodeRef: (nodeKey: string, element: HTMLDivElement | null) => void;
  selectedHandles: Set<string>;
};

export function VsfxTreeNode({
  depth,
  expandedKeys,
  hiddenHandles,
  node,
  nodeKey,
  onSelectHandles,
  onToggleExpanded,
  onToggleVisibility,
  onZoomToSelection,
  registerNodeRef,
  selectedHandles,
}: VsfxTreeNodeProps) {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const expanded = expandedKeys.has(nodeKey);
  const selected = isTreeNodeSelected(node, selectedHandles);
  const visibilityHandles = useMemo(() => getTreeNodeVisibilityHandles(node), [node]);
  const hidden = isTreeNodeHidden(node, hiddenHandles);

  useEffect(() => {
    registerNodeRef(nodeKey, nodeRef.current);
    return () => {
      registerNodeRef(nodeKey, null);
    };
  }, [nodeKey, registerNodeRef]);

  return (
    <div className="space-y-1">
      <div
        className="flex items-center gap-1"
        ref={(element) => {
          nodeRef.current = element;
          registerNodeRef(nodeKey, element);
        }}
        style={{ paddingLeft: `calc(${depth} * 0.75rem)` }}
      >
        {node.children.length > 0 ? (
          <Button
            aria-expanded={expanded}
            aria-label={`Toggle ${node.name}`}
            className="size-7 text-muted-foreground"
            onClick={() => onToggleExpanded(nodeKey)}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            <ChevronRightIcon className={cn("size-4 transition-transform", expanded && "rotate-90")} />
          </Button>
        ) : (
          <span className="block size-7 shrink-0" />
        )}
        {visibilityHandles.length > 0 ? (
          <Button
            aria-label={`${hidden ? "Show" : "Hide"} ${node.name}`}
            className="size-7 text-muted-foreground"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onToggleVisibility(visibilityHandles, !hidden);
            }}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            {hidden ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
          </Button>
        ) : null}
        <button
          className={cn(
            "hover:bg-accent hover:text-accent-foreground flex min-w-0 flex-1 rounded-md border border-transparent px-2 py-1.5 text-left text-sm transition-colors",
            selected && "bg-accent text-accent-foreground border-border",
          )}
          data-testid={createVsfxTreeRowTestId(node.handle)}
          onClick={() => onSelectHandles(getTreeNodeVisibilityHandles(node))}
          onDoubleClick={() => onZoomToSelection()}
          type="button"
        >
          <span className="truncate">{node.name}</span>
        </button>
      </div>
      {expanded ? (
        <div className="space-y-1">
          {node.children.map((childNode, childIndex) => (
            <VsfxTreeNode
              depth={depth + 1}
              expandedKeys={expandedKeys}
              hiddenHandles={hiddenHandles}
              key={`${String(childNode.handle)}-${childIndex}`}
              node={childNode}
              nodeKey={`${nodeKey}.${childIndex}`}
              onSelectHandles={onSelectHandles}
              onToggleExpanded={onToggleExpanded}
              onToggleVisibility={onToggleVisibility}
              onZoomToSelection={onZoomToSelection}
              registerNodeRef={registerNodeRef}
              selectedHandles={selectedHandles}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function createVsfxTreeRowTestId(handle: string | number) {
  return `vsfx-tree-row-${toStableSelectorPart(String(handle))}`;
}

function toStableSelectorPart(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
