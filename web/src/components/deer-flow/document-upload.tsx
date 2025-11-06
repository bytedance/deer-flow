// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Upload, X, FileText, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, useRef, useCallback } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { uploadDocument, type DocumentInfo } from "~/core/api/documents";
import { cn } from "~/lib/utils";

interface DocumentUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploadSuccess?: (document: DocumentInfo) => void;
}

interface UploadProgress {
  fileName: string;
  progress: number;
  status: "uploading" | "success" | "error";
  error?: string;
}

export function DocumentUpload({
  open,
  onOpenChange,
  onUploadSuccess,
}: DocumentUploadProps) {
  const t = useTranslations("documentUpload");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  // 打开对话框时重置状态
  const handleOpenChange = useCallback(
    (newOpen: boolean) => {
      onOpenChange(newOpen);
      if (!newOpen) {
        // 重置状态
        setSelectedFiles([]);
        setUploadProgress([]);
        setIsUploading(false);
      }
    },
    [onOpenChange],
  );

  // 处理文件选择
  const handleFileSelect = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files || []);
      if (files.length === 0) return;

      // 验证文件类型和大小
      const validFiles: File[] = [];
      const maxSize = 100 * 1024 * 1024; // 100MB

      files.forEach((file) => {
        // 允许常见的文档格式
        const allowedTypes = [
          "application/pdf",
          "application/msword",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "application/vnd.ms-excel",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "text/plain",
          "text/markdown",
          "text/csv",
        ];

        if (!allowedTypes.includes(file.type)) {
          toast.error(
            t("invalidFileType", { fileName: file.name, type: file.type }),
          );
          return;
        }

        if (file.size > maxSize) {
          toast.error(
            t("fileTooLarge", {
              fileName: file.name,
              maxSize: "100MB",
            }),
          );
          return;
        }

        validFiles.push(file);
      });

      if (validFiles.length > 0) {
        setSelectedFiles((prev) => [...prev, ...validFiles]);
        // 初始化上传进度
        setUploadProgress((prev) => [
          ...prev,
          ...validFiles.map((file) => ({
            fileName: file.name,
            progress: 0,
            status: "uploading" as const,
          })),
        ]);
      }

      // 重置input以便可以再次选择相同文件
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [t],
  );

  // 移除文件
  const handleRemoveFile = useCallback((index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
    setUploadProgress((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // 处理上传
  const handleUpload = useCallback(async () => {
    if (selectedFiles.length === 0) {
      toast.error(t("noFilesSelected"));
      return;
    }

    setIsUploading(true);

    try {
      // 逐个上传文件
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        if (!file) continue;
        
        const progressIndex = i;

        try {
          // 更新进度
          setUploadProgress((prev) => {
            const newProgress = [...prev];
            if (newProgress[progressIndex]) {
              newProgress[progressIndex] = {
                fileName: newProgress[progressIndex].fileName,
                progress: 10,
                status: "uploading",
              };
            }
            return newProgress;
          });

          const result = await uploadDocument({
            file,
            onProgress: (progress) => {
              setUploadProgress((prev) => {
                const newProgress = [...prev];
                if (newProgress[progressIndex]) {
                  newProgress[progressIndex] = {
                    ...newProgress[progressIndex],
                    progress,
                  };
                }
                return newProgress;
              });
            },
          });

          // 更新进度为成功
          setUploadProgress((prev) => {
            const newProgress = [...prev];
            if (newProgress[progressIndex]) {
              newProgress[progressIndex] = {
                fileName: newProgress[progressIndex].fileName,
                progress: 100,
                status: "success",
              };
            }
            return newProgress;
          });

          // 通知上传成功
          if (onUploadSuccess && result.document) {
            onUploadSuccess(result.document);
          }
        } catch (error) {
          console.error(`Failed to upload ${file.name}:`, error);
          const errorMessage =
            error instanceof Error ? error.message : t("uploadError");

          setUploadProgress((prev) => {
            const newProgress = [...prev];
            if (newProgress[progressIndex]) {
              newProgress[progressIndex] = {
                fileName: newProgress[progressIndex].fileName,
                progress: 0,
                status: "error",
                error: errorMessage,
              };
            }
            return newProgress;
          });

          toast.error(t("uploadFileError", { fileName: file.name }));
        }
      }

      // 检查上传结果
      setUploadProgress((prev) => {
        const allSuccess = prev
          .slice(0, selectedFiles.length)
          .every((p) => p.status === "success");
        const hasError = prev
          .slice(0, selectedFiles.length)
          .some((p) => p.status === "error");

        if (allSuccess && !hasError) {
          toast.success(t("uploadSuccess"));
          // 延迟关闭对话框，让用户看到成功消息
          setTimeout(() => {
            handleOpenChange(false);
          }, 1500);
        }
        return prev;
      });
    } catch (error) {
      console.error("Upload failed:", error);
      toast.error(t("uploadError"));
    } finally {
      setIsUploading(false);
    }
  }, [selectedFiles, uploadProgress, onUploadSuccess, handleOpenChange, t]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* 文件选择 */}
          <div className="space-y-2">
            <Label>{t("selectFiles")}</Label>
            <div
              className={cn(
                "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
                "hover:border-primary/50 hover:bg-accent/50",
              )}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground mb-1">
                {t("clickToUpload")}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("supportedFormats")}
              </p>
              <Input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.csv"
                onChange={handleFileSelect}
                className="hidden"
              />
            </div>
          </div>

          {/* 已选择的文件列表 */}
          {selectedFiles.length > 0 && (
            <div className="space-y-2">
              <Label>{t("selectedFiles")}</Label>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {selectedFiles.map((file, index) => (
                  <div
                    key={`${file.name}-${index}`}
                    className="flex items-center justify-between p-2 border rounded-lg"
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm truncate">{file.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        ({(file.size / 1024 / 1024).toFixed(2)} MB)
                      </span>
                    </div>
                    {!isUploading && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0"
                        onClick={() => handleRemoveFile(index)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 上传进度 */}
          {uploadProgress.length > 0 && (
            <div className="space-y-2">
              <Label>{t("uploadProgress")}</Label>
              <div className="space-y-2">
                {uploadProgress.map((progress, index) => (
                  <div key={index} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="truncate">{progress.fileName}</span>
                      <span className="text-muted-foreground">
                        {progress.progress}%
                      </span>
                    </div>
                    <div className="w-full bg-secondary rounded-full h-2">
                      <div
                        className={cn(
                          "h-2 rounded-full transition-all",
                          progress.status === "success" && "bg-green-500",
                          progress.status === "error" && "bg-red-500",
                          progress.status === "uploading" && "bg-primary",
                        )}
                        style={{ width: `${progress.progress}%` }}
                      />
                    </div>
                    {progress.status === "uploading" && (
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        <span>{t("uploading")}</span>
                      </div>
                    )}
                    {progress.status === "success" && (
                      <div className="text-xs text-green-600">
                        {t("uploadSuccess")}
                      </div>
                    )}
                    {progress.status === "error" && progress.error && (
                      <div className="text-xs text-red-600">
                        {progress.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={isUploading}
          >
            {t("cancel")}
          </Button>
          <Button
            onClick={handleUpload}
            disabled={isUploading || selectedFiles.length === 0}
          >
            {isUploading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("uploading")}
              </>
            ) : (
              t("upload")
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
