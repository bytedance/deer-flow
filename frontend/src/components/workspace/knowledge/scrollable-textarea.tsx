"use client";

/**
 * 带 RAG overlay 滚动条的输入框（2026-10-06 评测弹窗对齐）：裸 textarea 用的是原生上下
 * 箭头滑块，与全页 ScrollArea overlay 配方（题库表/抽屉同款）不一致。输入框随内容长高
 * （共享 Textarea 自带 field-sizing-content，min-h 由包装层给到与旧裸框一致的 64px），
 * 涨到 max-h-40 后由 ScrollArea 接管——滚动时浮现细轨缩略图、停 2s 淡出。外圈
 * border/focus ring 骑在包装层上（chat-panel composer 配方），内层 textarea 无边框、
 * 聚焦圈画在整框；resize 手柄随自适应高度一并去掉。
 */
import * as React from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

function ScrollableTextarea({
  className,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <div className="border-input focus-within:border-ring focus-within:ring-ring/50 min-h-16 rounded-md border transition-[color,box-shadow] focus-within:ring-[3px]">
      <ScrollArea className="max-h-40" scrollHideDelay={2000} type="scroll">
        <Textarea
          className={cn(
            "min-h-0 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0",
            className,
          )}
          {...props}
        />
      </ScrollArea>
    </div>
  );
}

export { ScrollableTextarea };
