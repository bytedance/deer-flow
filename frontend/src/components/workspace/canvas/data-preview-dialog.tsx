"use client";

import { useCallback, useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { NodePreviewResponse } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

interface DataPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  data: NodePreviewResponse | null;
  isLoading?: boolean;
  error?: Error | null;
  title?: string;
  description?: string;
  className?: string;
}

/**
 * 将数据转换为 CSV 格式
 */
function convertToCSV(
  rows: Record<string, unknown>[],
  columns: { name: string; type: string }[]
): string {
  if (rows.length === 0 || columns.length === 0) {
    return "";
  }

  // 表头
  const header = columns.map((col) => col.name).join(",");

  // 数据行
  const dataRows = rows.map((row) => {
    return columns
      .map((col) => {
        const value = row[col.name];
        // 处理特殊字符：逗号、引号、换行符
        if (
          value === null ||
          value === undefined ||
          value === "" ||
          String(value).includes(",") ||
          String(value).includes('"') ||
          String(value).includes("\n")
        ) {
          return `"${String(value ?? "").replace(/"/g, '""')}"`;
        }
        return String(value ?? "");
      })
      .join(",");
  });

  return [header, ...dataRows].join("\n");
}

/**
 * 下载 CSV 文件
 */
function downloadCSV(csv: string, filename: string) {
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function DataPreviewDialog({
  open,
  onOpenChange,
  data,
  isLoading = false,
  error = null,
  title = "数据预览",
  description,
  className,
}: DataPreviewDialogProps) {
  // 生成 CSV 数据
  const csvData = useMemo(() => {
    if (!data || !data.rows || !data.columns) return null;
    return convertToCSV(data.rows, data.columns);
  }, [data]);

  // 处理导出
  const handleExport = useCallback(() => {
    if (csvData) {
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      downloadCSV(csvData, `data-preview-${timestamp}.csv`);
    }
  }, [csvData]);

  // 格式化单元格值
  const formatCellValue = useCallback((value: unknown): string => {
    if (value === null || value === undefined) {
      return "NULL";
    }
    if (typeof value === "object") {
      return JSON.stringify(value);
    }
    return String(value);
  }, []);

  // 获取单元格样式
  const getCellStyle = useCallback((value: unknown): string => {
    if (value === null || value === undefined) {
      return "text-muted-foreground italic";
    }
    if (typeof value === "number") {
      return "text-right tabular-nums";
    }
    if (typeof value === "boolean") {
      return "text-primary";
    }
    return "";
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("max-w-4xl max-h-[80vh]", className)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <div className="flex flex-col gap-4 flex-1 min-h-0">
          {/* 状态显示 */}
          {isLoading && (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
              <span className="ml-2 text-muted-foreground">加载中...</span>
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center py-8 text-destructive">
              <span className="text-lg font-medium">加载失败</span>
              <span className="text-sm">{error.message}</span>
            </div>
          )}

          {/* 数据表格 */}
          {!isLoading && !error && data && (
            <>
              {/* 信息栏 */}
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  共 {data.rows_count ?? data.rows.length} 行，{data.columns.length} 列
                </span>
                {data.rows_count !== undefined && data.rows.length < data.rows_count && (
                  <span className="text-xs">(显示前 {data.rows.length} 行)</span>
                )}
              </div>

              {/* 表格 */}
              <ScrollArea className="flex-1 border rounded-md">
                {data.rows.length > 0 ? (
                  <Table>
                    <TableHeader className="sticky top-0 bg-background">
                      <TableRow>
                        {data.columns.map((col) => (
                          <TableHead key={col.name} className="font-medium">
                            <div className="flex flex-col">
                              <span>{col.name}</span>
                              <span className="text-xs text-muted-foreground font-normal">
                                {col.type}
                              </span>
                            </div>
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.rows.map((row, rowIndex) => (
                        <TableRow key={rowIndex}>
                          {data.columns.map((col) => (
                            <TableCell
                              key={col.name}
                              className={getCellStyle(row[col.name])}
                            >
                              {formatCellValue(row[col.name])}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="flex items-center justify-center py-8 text-muted-foreground">
                    暂无数据
                  </div>
                )}
              </ScrollArea>
            </>
          )}

          {/* 空状态 */}
          {!isLoading && !error && !data && (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              选择节点以预览数据
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          {csvData && (
            <Button onClick={handleExport} disabled={!csvData}>
              导出 CSV
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
