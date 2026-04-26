"use client";

import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type OnSelectionChangeParams,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { nanoid } from "nanoid";
import { useCallback, useEffect, useRef, useState } from "react";

import type { CanvasNode, CanvasEdge, NodeType } from "@/core/canvas/types";

import { CanvasToolbar } from "./canvas-toolbar";
import { ComponentPanel } from "./component-panel";
import { useCanvasContext } from "./context";
import { ExecutionStatus } from "./execution-status";
import { NodeEditor } from "./node-editor";
import { DataOutputNode } from "./nodes/data-output-node";
import { DataSourceNode } from "./nodes/data-source-node";
import { PythonScriptNode } from "./nodes/python-script-node";
import { SQLExecutorNode } from "./nodes/sql-executor-node";


const nodeTypes = {
  data_source: DataSourceNode,
  sql_executor: SQLExecutorNode,
  python_script: PythonScriptNode,
  data_output: DataOutputNode,
};

// 节点默认数据
const defaultNodeData: Record<NodeType, Record<string, unknown>> = {
  data_source: { table_name: "", db_connection_id: "" },
  sql_executor: { query_name: "", sql_query: "" },
  python_script: { script_name: "", code: "" },
  data_output: { output_name: "", output_type: "csv" },
};

export function CanvasPanel() {
  const {
    canvas,
    setSelectedNodes,
    setSelectedEdges,
    selectedNodeId,
    selectNode,
    executionStatus,
    canvasMode,
    setCanvas,
    nodeResults,
  } = useCanvasContext();

  // 保存状态
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // 确保 edges 有唯一 id
  const ensureEdgeIds = useCallback((edges: CanvasEdge[]): CanvasEdge[] => {
    return edges.map((edge) => ({
      ...edge,
      id: edge.id ?? `edge-${nanoid()}`,
    }));
  }, []);

  // 确保 nodes 有唯一 id
  const ensureNodeIds = useCallback((nodes: CanvasNode[]): CanvasNode[] => {
    return nodes.map((node) => ({
      ...node,
      id: node.id ?? `node-${nanoid()}`,
    }));
  }, []);

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);

  const onSelectionChange = useCallback(
    ({ nodes: selectedNodes, edges: selectedEdges }: OnSelectionChangeParams<CanvasNode, CanvasEdge>) => {
      setSelectedNodes(selectedNodes.map((n) => n.id));
      setSelectedEdges(selectedEdges.map((e) => e.id));
      // 单选节点时设置 selectedNodeId 以显示 Node Editor
      if (selectedNodes.length === 1) {
        selectNode(selectedNodes[0]!.id);
      } else {
        selectNode(null);
      }
    },
    [setSelectedNodes, setSelectedEdges, selectNode],
  );

  // React Flow 引用
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // 拖拽开始处理
  const handleDragStart = useCallback((_nodeType: NodeType) => {
    // 设置拖拽数据到 dataTransfer（由 ComponentPanel 处理）
  }, []);

  // 添加节点到画布
  const addNode = useCallback(
    (nodeType: NodeType, position?: { x: number; y: number }) => {
      const newNode: CanvasNode = {
        id: `node-${nanoid()}`,
        type: nodeType,
        position: position ?? { x: 200 + Math.random() * 200, y: 200 + Math.random() * 200 },
        data: { ...defaultNodeData[nodeType] },
      };

      setNodes((nds) => [...nds, newNode]);

      // 如果 canvas 不存在，创建一个新的 canvas 对象
      if (!canvas) {
        setCanvas({
          id: `canvas-${nanoid()}`,
          thread_id: "",
          name: "New Canvas",
          description: "",
          agent_execution_mode: "interactive",
          nodes: [newNode],
          edges: [],
          status: "idle",
          execution_log: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      } else {
        setCanvas({
          ...canvas,
          nodes: [...canvas.nodes, newNode],
        });
      }
    },
    [canvas, setNodes, setCanvas],
  );

  // 处理拖放
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      // 从 window 对象获取拖拽的节点类型
      const nodeType = (window as unknown as { __canvasDragNodeType?: NodeType }).__canvasDragNodeType;
      if (!nodeType) return;

      // 计算放置位置
      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!reactFlowBounds) return;

      const position = {
        x: event.clientX - reactFlowBounds.left,
        y: event.clientY - reactFlowBounds.top,
      };

      addNode(nodeType, position);

      // 清除拖拽数据
      delete (window as unknown as { __canvasDragNodeType?: NodeType }).__canvasDragNodeType;
    },
    [addNode],
  );

  // 处理节点变化（根据模式限制）
  const handleNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      // 在运行模式下，只允许选择变化，不允许其他修改
      if (canvasMode === "run") {
        const selectionChanges = changes.filter((change) => change.type === "select");
        if (selectionChanges.length > 0) {
          setNodes((nds) => applyNodeChanges(selectionChanges, nds));
        }
      } else {
        onNodesChange(changes);
      }
    },
    [canvasMode, onNodesChange, setNodes],
  );

  // 处理边变化（根据模式限制）
  const handleEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) => {
      // 在运行模式下禁止边的变化
      if (canvasMode === "run") {
        return;
      }
      onEdgesChange(changes);
    },
    [canvasMode, onEdgesChange],
  );

  // 处理连接（根据模式限制）
  const handleConnect = useCallback(
    (connection: Connection) => {
      // 在运行模式下禁止新建连接
      if (canvasMode === "run") {
        return;
      }
      setEdges((eds) => addEdge(connection, eds));
    },
    [canvasMode, setEdges],
  );

  // 保存到后端（静默执行，不触发状态更新）
  const saveCanvas = useCallback(async (silent = true) => {
    if (!canvas || canvas.thread_id === "") {
      console.warn("Canvas not ready for saving: no thread_id");
      return;
    }
    setIsSaving(true);
    try {
      // 直接调用 API 而不是通过 hook，避免 query cache 更新导致重新渲染
      const { updateCanvas } = await import("@/core/canvas/api");
      await updateCanvas(canvas.thread_id, {
        nodes: nodes,
        edges: edges,
      });
      setLastSaved(new Date());
      // 不更新 context，因为 React Flow 状态已经是最新
    } catch (error) {
      console.error("Failed to save canvas:", error);
      // 静默模式下不显示错误，非静默模式可以处理
      if (!silent) {
        throw error;
      }
    } finally {
      setIsSaving(false);
    }
  }, [canvas, nodes, edges]);

  // 自动保存 - 当 nodes 或 edges 变化时 debounce 保存（静默）
  useEffect(() => {
    if (!canvas || canvas.thread_id === "" || canvasMode !== "edit") {
      return;
    }
    // 只在有实际节点或边时才自动保存
    if (nodes.length === 0 && edges.length === 0) {
      return;
    }
    const timer = setTimeout(() => {
      void saveCanvas(true); // 静默保存
    }, 1000); // 1秒 debounce
    return () => clearTimeout(timer);
  }, [nodes, edges, canvas, canvasMode, saveCanvas]);

  // 使用上一次保存的数据引用，避免不必要的同步
  const prevCanvasRef = useRef<typeof canvas>(null);

  // Sync canvas data with React Flow state - 只在外部数据变化时同步
  useEffect(() => {
    if (canvas && canvas !== prevCanvasRef.current) {
      prevCanvasRef.current = canvas;
      // 检查是否需要更新，避免用户编辑时被外部数据覆盖
      const currentNodesCount = nodes.length;
      const canvasNodesCount = canvas.nodes.length;
      // 只有当节点数量不一致时才同步（意味着外部创建了新节点）
      if (canvasNodesCount > currentNodesCount || (currentNodesCount === 0 && canvasNodesCount > 0)) {
        setNodes(ensureNodeIds(canvas.nodes));
        setEdges(ensureEdgeIds(canvas.edges));
      }
    }
  }, [canvas, nodes.length, setNodes, setEdges, ensureNodeIds, ensureEdgeIds]);

  return (
    <div className="h-full w-full flex">
      {/* 左侧主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Canvas DAG区域 */}
        <div
          className="flex-1 relative min-h-0"
          ref={reactFlowWrapper}
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={handleConnect}
            onSelectionChange={onSelectionChange}
            nodeTypes={nodeTypes}
            fitView
            attributionPosition="bottom-left"
            // 运行模式下禁用交互
            nodesDraggable={canvasMode === "edit"}
            nodesConnectable={canvasMode === "edit"}
            elementsSelectable={true}
          >
            <Controls />
            <MiniMap />
            <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
          </ReactFlow>
          {/* 工具栏 */}
          <div className="absolute top-2 left-2 z-10">
            <CanvasToolbar
              onSave={saveCanvas}
              isSaving={isSaving}
              lastSaved={lastSaved}
            />
          </div>
          {/* 执行状态 */}
          <div className="absolute bottom-2 left-2 z-10">
            <ExecutionStatus
              status={executionStatus}
              nodeResults={nodeResults}
              onNodeSelect={selectNode}
            />
          </div>
        </div>

        {/* 底部组件面板 - 水平布局 */}
        <div className="h-16 border-t bg-muted/30 shrink-0">
          <ComponentPanel
            onDragStart={handleDragStart}
            onNodeAdd={addNode}
            className="h-full"
            horizontal={true}
          />
        </div>
      </div>

      {/* 右侧 Node Editor */}
      {selectedNodeId && (
        <div className="w-64 border-l bg-background p-4 shrink-0 overflow-auto">
          <NodeEditor />
        </div>
      )}
    </div>
  );
}