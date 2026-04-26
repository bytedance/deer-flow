"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";

import type { Canvas } from "@/core/canvas/types";

export interface CanvasContextType {
  // Canvas 数据
  canvas: Canvas | null;
  setCanvas: (canvas: Canvas | null) => void;

  // 选中的节点
  selectedNodeId: string | null;
  selectNode: (nodeId: string | null) => void;

  // 面板状态
  open: boolean;
  setOpen: (open: boolean) => void;

  // 编辑状态
  isEditing: boolean;
  setIsEditing: (editing: boolean) => void;

  // React Flow 节点选择
  selectedNodes: string[];
  setSelectedNodes: (nodes: string[]) => void;

  // 边选择
  selectedEdges: string[];
  setSelectedEdges: (edges: string[]) => void;
}

const CanvasContext = createContext<CanvasContextType | undefined>(undefined);

interface CanvasProviderProps {
  children: ReactNode;
}

export function CanvasProvider({ children }: CanvasProviderProps) {
  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const { setOpen: setSidebarOpen } = useSidebar();

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    if (nodeId) {
      setIsEditing(true);
    }
  }, []);

  const handleSetOpen = useCallback(
    (isOpen: boolean) => {
      setOpen(isOpen);
      if (isOpen) {
        setSidebarOpen(false);
      }
    },
    [setSidebarOpen],
  );

  const value: CanvasContextType = {
    canvas,
    setCanvas,
    selectedNodeId,
    selectNode,
    open,
    setOpen: handleSetOpen,
    isEditing,
    setIsEditing,
    selectedNodes,
    setSelectedNodes,
    selectedEdges,
    setSelectedEdges,
  };

  return (
    <CanvasContext.Provider value={value}>{children}</CanvasContext.Provider>
  );
}

export function useCanvasContext() {
  const context = useContext(CanvasContext);
  if (context === undefined) {
    throw new Error("useCanvasContext must be used within a CanvasProvider");
  }
  return context;
}
