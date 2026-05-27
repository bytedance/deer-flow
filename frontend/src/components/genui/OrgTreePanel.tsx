"use client";

import { useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";

import type { OrgTreeNode } from "./device-selector-types";

interface OrgTreePanelProps {
  treeData: OrgTreeNode[];
  onSelectOrgNode: (node: OrgTreeNode) => void;
  selectedOrgId?: string;
  disabled?: boolean;
}

function matchNode(node: OrgTreeNode, lower: string): boolean {
  if (node.label.toLowerCase().includes(lower)) return true;
  if (node.children) {
    return node.children.some((c) => matchNode(c, lower));
  }
  return false;
}

function filterTree(nodes: OrgTreeNode[], lower: string): OrgTreeNode[] {
  return nodes
    .filter((n) => matchNode(n, lower))
    .map((n) => ({
      ...n,
      children: n.children ? filterTree(n.children, lower) : undefined,
    }));
}

function OrgTreeNodeItem({
  node,
  depth,
  onSelect,
  selectedOrgId,
  disabled,
  searchText,
}: {
  node: OrgTreeNode;
  depth: number;
  onSelect: (node: OrgTreeNode) => void;
  selectedOrgId?: string;
  disabled?: boolean;
  searchText: string;
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
        <HighlightLabel text={node.label} highlight={searchText} />
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
            searchText={searchText}
          />
        ))}
    </div>
  );
}

function HighlightLabel({ text, highlight }: { text: string; highlight: string }) {
  if (!highlight) return <span className="truncate">{text}</span>;
  const lower = highlight.toLowerCase();
  const idx = text.toLowerCase().indexOf(lower);
  if (idx === -1) return <span className="truncate">{text}</span>;
  return (
    <span className="truncate">
      {text.slice(0, idx)}
      <span className="bg-yellow-200 dark:bg-yellow-800 rounded-sm">
        {text.slice(idx, idx + highlight.length)}
      </span>
      {text.slice(idx + highlight.length)}
    </span>
  );
}

export default function OrgTreePanel({ treeData, onSelectOrgNode, selectedOrgId, disabled }: OrgTreePanelProps) {
  const { t } = useI18n();
  const [searchText, setSearchText] = useState("");

  const rootOrgNodes = useMemo(() => {
    const roots = treeData.filter((n) => n.type >= 10);
    const lower = searchText.trim().toLowerCase();
    if (!lower) return roots;
    return filterTree(roots, lower);
  }, [treeData, searchText]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-2 py-1.5">
        <input
          type="text"
          className="w-full rounded border bg-background px-2 py-1 text-xs outline-none focus:border-primary/50"
          placeholder={t.genui.searchOrgPlaceholder}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {rootOrgNodes.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            {searchText ? t.genui.noMatches : t.genui.noOrgData}
          </div>
        ) : (
          rootOrgNodes
            .sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0))
            .map((node) => (
              <OrgTreeNodeItem
                key={node.id}
                node={node}
                depth={0}
                onSelect={onSelectOrgNode}
                selectedOrgId={selectedOrgId}
                disabled={disabled}
                searchText={searchText.trim()}
              />
            ))
        )}
      </div>
    </div>
  );
}
