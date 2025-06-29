// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Download, FileText, FileImage, FileDown } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "~/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { Tooltip } from "~/components/deer-flow/tooltip";
import {
  downloadAsMarkdown,
  downloadAsPDF,
  downloadAsImage,
  downloadAsWord,
  createTempElementForScreenshot,
  cleanupTempElement,
} from "~/lib/download-utils";

export interface DownloadDropdownProps {
  content: string;
  className?: string;
  disabled?: boolean;
}

export function DownloadDropdown({
  content,
  className,
  disabled = false
}: DownloadDropdownProps) {
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownloadMarkdown = useCallback(() => {
    downloadAsMarkdown(content);
  }, [content]);

  const handleDownloadPDF = useCallback(async () => {
    if (isDownloading) return;
    setIsDownloading(true);
    try {
      await downloadAsPDF(content);
    } catch (error) {
      console.error('PDF download failed:', error);
    } finally {
      setIsDownloading(false);
    }
  }, [content, isDownloading]);

  const handleDownloadImage = useCallback(async () => {
    if (isDownloading) return;
    setIsDownloading(true);
    try {
      // 创建临时元素用于截图
      const tempId = createTempElementForScreenshot(content);
      // 等待DOM更新
      await new Promise(resolve => setTimeout(resolve, 100));
      await downloadAsImage(tempId);
      cleanupTempElement(tempId);
    } catch (error) {
      console.error('Image download failed:', error);
    } finally {
      setIsDownloading(false);
    }
  }, [content, isDownloading]);

  const handleDownloadWord = useCallback(async () => {
    if (isDownloading) return;
    setIsDownloading(true);
    try {
      await downloadAsWord(content);
    } catch (error) {
      console.error('Word download failed:', error);
    } finally {
      setIsDownloading(false);
    }
  }, [content, isDownloading]);

  return (
    <DropdownMenu>
      <Tooltip title="Download Report">
        <DropdownMenuTrigger asChild>
          <Button
            className={className}
            size="icon"
            variant="ghost"
            disabled={disabled || isDownloading}
          >
            <Download className={isDownloading ? "animate-bounce" : ""} />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem
          onClick={handleDownloadMarkdown}
          disabled={isDownloading}
          className="whitespace-nowrap"
        >
          <FileDown className="mr-2 h-4 w-4" />
          <span>Download as Markdown</span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={handleDownloadPDF}
          disabled={isDownloading}
          className="whitespace-nowrap"
        >
          <FileText className="mr-2 h-4 w-4" />
          <span>Download as PDF</span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={handleDownloadImage}
          disabled={isDownloading}
          className="whitespace-nowrap"
        >
          <FileImage className="mr-2 h-4 w-4" />
          <span>Download as Image</span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={handleDownloadWord}
          disabled={isDownloading}
          className="whitespace-nowrap"
        >
          <FileText className="mr-2 h-4 w-4" />
          <span>Download as Word</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
} 