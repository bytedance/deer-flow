"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { VsfxTreeNode } from "./VsfxTreeNode";

export type VsfxTreeNodeData = {
  children: VsfxTreeNodeData[];
  handle: string | number;
  name: string;
};

type VsfxTreeViewProps = {
  hiddenHandles: Set<string | number>;
  nodes: VsfxTreeNodeData[];
  onSelectHandles: (handles: Array<string | number>) => void;
  onToggleVisibility: (handles: Array<string | number>, hidden: boolean) => void;
  onZoomToSelection: () => void;
  selectedHandles: Array<string | number>;
};

export function VsfxTreeView(_props: VsfxTreeViewProps) {
  const { hiddenHandles, nodes, onSelectHandles, onToggleVisibility, onZoomToSelection, selectedHandles } = _props;
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [scrollTargetKey, setScrollTargetKey] = useState<string | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLDivElement>());
  const pathIndex = useMemo(() => buildPathIndex(nodes), [nodes]);

  useEffect(() => {
    setExpandedKeys(new Set());
    setScrollTargetKey(null);
    nodeRefs.current.clear();
  }, [nodes]);

  useEffect(() => {
    const primaryHandle = selectedHandles[0];

    if (primaryHandle == null) {
      return;
    }

    const pathKeys = pathIndex.get(String(primaryHandle));

    if (!pathKeys || pathKeys.length === 0) {
      return;
    }

    setExpandedKeys((currentKeys) => {
      const nextKeys = new Set(currentKeys);

      for (const key of pathKeys.slice(0, -1)) {
        nextKeys.add(key);
      }

      return nextKeys;
    });
    const targetKey = pathKeys.at(-1);

    if (!targetKey) {
      return;
    }

    setScrollTargetKey(targetKey);
  }, [pathIndex, selectedHandles]);

  useEffect(() => {
    if (!scrollTargetKey) {
      return;
    }

    const targetElement = nodeRefs.current.get(scrollTargetKey);

    if (!targetElement) {
      return;
    }

    requestAnimationFrame(() => {
      if (typeof targetElement.scrollIntoView !== "function") {
        return;
      }

      targetElement.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    });
  }, [expandedKeys, scrollTargetKey]);

  return (
    <div className="min-h-0 flex-1 overflow-auto px-2 py-2" data-testid="vsfx-tree-view">
      <div className="space-y-1">
        {nodes.map((node, index) => (
          <VsfxTreeNode
            depth={0}
            expandedKeys={expandedKeys}
            hiddenHandles={hiddenHandles}
            key={`${String(node.handle)}-${index}`}
            node={node}
            nodeKey={String(index)}
            onSelectHandles={onSelectHandles}
            onToggleExpanded={(nodeKey) => {
              setExpandedKeys((currentKeys) => {
                const nextKeys = new Set(currentKeys);

                if (nextKeys.has(nodeKey)) {
                  nextKeys.delete(nodeKey);
                }
                else {
                  nextKeys.add(nodeKey);
                }

                return nextKeys;
              });
            }}
            onToggleVisibility={onToggleVisibility}
            onZoomToSelection={onZoomToSelection}
            registerNodeRef={(nodeKey, element) => {
              if (element) {
                nodeRefs.current.set(nodeKey, element);
                return;
              }

              nodeRefs.current.delete(nodeKey);
            }}
            selectedHandles={new Set(selectedHandles.map((handle) => String(handle)))}
          />
        ))}
      </div>
    </div>
  );
}

function buildPathIndex(
  nodes: VsfxTreeNodeData[],
  parentPath: number[] = [],
  pathIndex = new Map<string, string[]>(),
  parentKeys: string[] = [],
) {
  nodes.forEach((node, index) => {
    const currentPath = [...parentPath, index];
    const nodeKey = currentPath.join(".");
    const pathKeys = [...parentKeys, nodeKey];

    if (!pathIndex.has(String(node.handle))) {
      pathIndex.set(String(node.handle), pathKeys);
    }

    if (node.children.length > 0) {
      buildPathIndex(node.children, currentPath, pathIndex, pathKeys);
    }
  });

  return pathIndex;
}

export function collectLeafHandles(node: VsfxTreeNodeData): Array<string | number> {
  if (node.children.length === 0) {
    return isUiGroupHandle(node.handle) ? [] : [node.handle];
  }

  return node.children.flatMap((childNode) => collectLeafHandles(childNode));
}

export function collectSelectableHandles(node: VsfxTreeNodeData): Array<string | number> {
  const descendantHandles = node.children.flatMap((childNode) => collectSelectableHandles(childNode));

  if (isUiGroupHandle(node.handle)) {
    return descendantHandles;
  }

  return [node.handle, ...descendantHandles];
}

export function isUiGroupHandle(handle: string | number) {
  return String(handle) === "0";
}

export function isTreeNodeSelected(
  node: VsfxTreeNodeData,
  selectedHandles: Set<string>,
) {
  return collectSelectableHandles(node).some((handle) => selectedHandles.has(String(handle)));
}

export function isTreeNodeHidden(
  node: VsfxTreeNodeData,
  hiddenHandles: Set<string | number>,
) {
  const visibilityHandles = isUiGroupHandle(node.handle)
    ? collectLeafHandles(node)
    : collectSelectableHandles(node);

  return visibilityHandles.length > 0
    && visibilityHandles.every((handle) => hiddenHandles.has(handle));
}

export function getTreeNodeVisibilityHandles(node: VsfxTreeNodeData) {
  const handles = isUiGroupHandle(node.handle)
    ? collectLeafHandles(node)
    : collectSelectableHandles(node);

  return Array.from(new Set(handles.filter((handle) => !isUiGroupHandle(handle))));
}
