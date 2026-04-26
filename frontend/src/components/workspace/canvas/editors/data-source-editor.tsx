"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useDbConnections,
  useTableSchema,
  useTables,
} from "@/core/canvas/hooks";
import type { CanvasNode, DataSourceNodeData } from "@/core/canvas/types";

interface DataSourceEditorProps {
  node: CanvasNode;
  onUpdate: (data: Partial<DataSourceNodeData>) => void;
  onPreview?: () => void;
}

export function DataSourceEditor({
  node,
  onUpdate,
  onPreview,
}: DataSourceEditorProps) {
  const nodeData = node.data as DataSourceNodeData;

  // 本地状态
  const [localTableName, setLocalTableName] = useState(
    nodeData.table_name ?? ""
  );

  // 从hooks获取数据
  const { connections, isLoading: loadingConnections } = useDbConnections();
  const { tables, isLoading: loadingTables } = useTables(
    nodeData.db_connection_id ?? null
  );
  const { columns, isLoading: loadingSchema } = useTableSchema(
    nodeData.db_connection_id ?? null,
    nodeData.table_name ?? null
  );

  // 同步表名
  useEffect(() => {
    setLocalTableName(nodeData.table_name ?? "");
  }, [nodeData.table_name]);

  // 连接选择
  const handleConnectionChange = useCallback(
    (connectionId: string) => {
      // 清空表名
      onUpdate({
        db_connection_id: connectionId,
        table_name: undefined,
      });
      setLocalTableName("");
    },
    [onUpdate]
  );

  // 表选择
  const handleTableChange = useCallback(
    (tableName: string) => {
      setLocalTableName(tableName);
      onUpdate({ table_name: tableName });
    },
    [onUpdate]
  );

  // 表名输入
  const handleTableNameBlur = useCallback(() => {
    if (localTableName !== nodeData.table_name) {
      onUpdate({ table_name: localTableName || undefined });
    }
  }, [localTableName, nodeData.table_name, onUpdate]);

  return (
    <div className="flex flex-col gap-4">
      {/* 数据库连接选择 */}
      <div className="space-y-2">
        <Label htmlFor="db-connection">数据库连接</Label>
        <Select
          value={nodeData.db_connection_id ?? ""}
          onValueChange={handleConnectionChange}
          disabled={loadingConnections}
        >
          <SelectTrigger id="db-connection" className="w-full">
            <SelectValue placeholder="选择数据库连接" />
          </SelectTrigger>
          <SelectContent>
            {connections.map((conn) => (
              <SelectItem key={conn.id} value={conn.id}>
                <span className="flex items-center gap-2">
                  <span>{conn.name}</span>
                  <span className="text-xs text-muted-foreground">
                    ({conn.type})
                  </span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {connections.length === 0 && !loadingConnections && (
          <p className="text-xs text-muted-foreground">
            暂无可用的数据库连接
          </p>
        )}
      </div>

      {/* 表选择 */}
      <div className="space-y-2">
        <Label htmlFor="table-select">数据表</Label>
        {nodeData.db_connection_id ? (
          <Select
            value={nodeData.table_name ?? ""}
            onValueChange={handleTableChange}
            disabled={loadingTables}
          >
            <SelectTrigger id="table-select" className="w-full">
              <SelectValue placeholder="选择数据表" />
            </SelectTrigger>
            <SelectContent>
              {tables.map((table) => (
                <SelectItem key={table} value={table}>
                  {table}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            id="table-select"
            value={localTableName}
            onChange={(e) => setLocalTableName(e.target.value)}
            onBlur={handleTableNameBlur}
            placeholder="输入表名（需选择连接后可选）"
          />
        )}
      </div>

      {/* 表结构预览 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>表结构</Label>
          {loadingSchema && (
            <span className="text-xs text-muted-foreground">加载中...</span>
          )}
        </div>
        <ScrollArea className="h-32 border rounded-md">
          {columns.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>列名</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead className="w-16">可空</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {columns.map((col) => (
                  <TableRow key={col.name}>
                    <TableCell>{col.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {col.type}
                    </TableCell>
                    <TableCell className="text-center">
                      {col.nullable ? "是" : "否"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
              {nodeData.db_connection_id && nodeData.table_name
                ? "暂无列信息"
                : "选择数据库和表以查看结构"}
            </div>
          )}
        </ScrollArea>
      </div>

      {/* 数据预览按钮 */}
      <Button
        variant="outline"
        onClick={onPreview}
        disabled={!nodeData.db_connection_id || !nodeData.table_name}
      >
        预览数据
      </Button>
    </div>
  );
}
