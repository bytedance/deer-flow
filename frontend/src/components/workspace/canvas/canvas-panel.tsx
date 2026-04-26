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
  applyEdgeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { nanoid } from "nanoid";
import { useCallback, useEffect, useRef } from "react";

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
    setNodeResults,
  } = useCanvasContext();

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

  // Sync canvas data with React Flow state
  useEffect(() => {
    if (canvas) {
      setNodes(ensureNodeIds(canvas.nodes));
      setEdges(ensureEdgeIds(canvas.edges));
    }
  }, [canvas, setNodes, setEdges, ensureNodeIds, ensureEdgeIds]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge(connection, eds));
    },
    [setEdges],
  );

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
  const handleDragStart = useCallback((nodeType: NodeType) => {
    // 设置拖拽数据到 dataTransfer
    // 这个回调由 ComponentPanel 触发
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
      setCanvas({
        ...canvas!,
        nodes: [...canvas!.nodes, newNode],
      });
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

  return (
    <div className="h-full w-full flex">
      {/* 左侧组件面板 */}
      <div className="w-56 border-r bg-muted/30">
        <ComponentPanel
          onDragStart={handleDragStart}
          onNodeAdd={addNode}
          className="h-full"
        />
      </div>

      {/* Canvas DAG区域 */}
      <div
        className="flex-1 relative"
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
          <CanvasToolbar />
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
      {/* Node Editor侧边栏 */}
      {selectedNodeId && (
        <div className="w-64 border-l bg-background p-4">
          <NodeEditor />
        </div>
      )}
    </div>
  );
}