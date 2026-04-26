"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import type {
  Canvas,
  CanvasMode,
  ExecutionStatusResponse,
  NodeResult,
  DbConnection,
} from "@/core/canvas/types";

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

  // Canvas 模式（编辑/运行）
  canvasMode: CanvasMode;
  setCanvasMode: (mode: CanvasMode) => void;

  // 执行状态
  executionStatus: ExecutionStatusResponse | null;
  setExecutionStatus: (status: ExecutionStatusResponse | null) => void;

  // 节点执行结果
  nodeResults: Record<string, NodeResult>;
  setNodeResults: (results: Record<string, NodeResult>) => void;
  updateNodeResult: (nodeId: string, result: NodeResult) => void;

  // 数据库连接
  dbConnections: DbConnection[];
  setDbConnections: (connections: DbConnection[]) => void;

  // 代码编辑器弹窗
  codeEditorOpen: boolean;
  setCodeEditorOpen: (open: boolean) => void;
  codeEditorNode: string | null;
  setCodeEditorNode: (nodeId: string | null) => void;

  // 数据预览弹窗
  dataPreviewOpen: boolean;
  setDataPreviewOpen: (open: boolean) => void;
  dataPreviewNode: string | null;
  setDataPreviewNode: (nodeId: string | null) => void;
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

  // 新增状态
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("edit");
  const [executionStatus, setExecutionStatus] =
    useState<ExecutionStatusResponse | null>(null);
  const [nodeResults, setNodeResults] = useState<Record<string, NodeResult>>(
    {},
  );
  const [dbConnections, setDbConnections] = useState<DbConnection[]>([]);

  // 弹窗状态
  const [codeEditorOpen, setCodeEditorOpen] = useState(false);
  const [codeEditorNode, setCodeEditorNode] = useState<string | null>(null);
  const [dataPreviewOpen, setDataPreviewOpen] = useState(false);
  const [dataPreviewNode, setDataPreviewNode] = useState<string | null>(null);

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

  // 更新单个节点结果的辅助函数
  const updateNodeResult = useCallback(
    (nodeId: string, result: NodeResult) => {
      setNodeResults((prev) => ({
        ...prev,
        [nodeId]: result,
      }));
    },
    [],
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
    // 新增的状态
    canvasMode,
    setCanvasMode,
    executionStatus,
    setExecutionStatus,
    nodeResults,
    setNodeResults,
    updateNodeResult,
    dbConnections,
    setDbConnections,
    // 弹窗状态
    codeEditorOpen,
    setCodeEditorOpen,
    codeEditorNode,
    setCodeEditorNode,
    dataPreviewOpen,
    setDataPreviewOpen,
    dataPreviewNode,
    setDataPreviewNode,
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
