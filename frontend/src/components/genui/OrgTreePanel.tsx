"use client";

import { useState } from "react";

import type { OrgTreeNode } from "./device-selector-types";

interface OrgTreePanelProps {
  treeData: OrgTreeNode[];
  onSelectOrgNode: (node: OrgTreeNode) => void;
  selectedOrgId?: string;
  disabled?: boolean;
}

function OrgTreeNodeItem({
  node,
  depth,
  onSelect,
  selectedOrgId,
  disabled,
}: {
  node: OrgTreeNode;
  depth: number;
  onSelect: (node: OrgTreeNode) => void;
  selectedOrgId?: string;
  disabled?: boolean;
}) {
  const hasOrgChildren = node.children?.some((c) => c.type >= 10) ?? false;
  const [expanded, setExpanded] = useState(true);

  return (
    <div>
      <button
        type="button"
        className={`flex w-full items-center gap-1 rounded px-2 py-1 text-left text-xs transition-colors hover:bg-muted/50 disabled:opacity-50 ${
          selectedOrgId === node.id ? "bg-primary/10 font-medium text-primary" : ""
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => onSelect(node)}
        disabled={disabled}
      >
        {hasOrgChildren && (
          <span
            className="inline-flex w-4 shrink-0 items-center justify-center text-muted-foreground"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
          >
            {expanded ? "▼" : "▶"}
          </span>
        )}
        {!hasOrgChildren && <span className="w-4 shrink-0" />}
        <span className="truncate">{node.label}</span>
      </button>
      {expanded && node.children
        ?.filter((c) => c.type >= 10)
        .sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0))
        .map((child) => (
          <OrgTreeNodeItem
            key={child.id}
            node={child}
            depth={depth + 1}
            onSelect={onSelect}
            selectedOrgId={selectedOrgId}
            disabled={disabled}
          />
        ))}
    </div>
  );
}

export default function OrgTreePanel({ treeData, onSelectOrgNode, selectedOrgId, disabled }: OrgTreePanelProps) {
  const rootOrgNodes = treeData.filter((n) => n.type >= 10);

  if (rootOrgNodes.length === 0) {
    return <div className="p-4 text-center text-xs text-muted-foreground">无组织数据</div>;
  }

  return (
    <div className="h-full overflow-y-auto">
      {rootOrgNodes
        .sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0))
        .map((node) => (
          <OrgTreeNodeItem
            key={node.id}
            node={node}
            depth={0}
            onSelect={onSelectOrgNode}
            selectedOrgId={selectedOrgId}
            disabled={disabled}
          />
        ))}
    </div>
  );
}
