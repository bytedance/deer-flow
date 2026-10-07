"use client";

import * as React from "react";
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";

import { cn } from "@/lib/utils";

function ScrollArea({
  className,
  children,
  horizontal = false,
  viewportRef,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root> & {
  /** 额外渲染横向悬浮滚动条（与纵向同款细轨道+淡入淡出）；Radix 在该方向
      无溢出时自动不显形，故纵向-only 调用方传了也无副作用。 */
  horizontal?: boolean;
  /** 把 Viewport（真实滚动层）的 ref 外露：供外部库自带滚动逻辑挂载
      （如 use-stick-to-bottom 的 scrollRef 需指向滚动元素）。 */
  viewportRef?: React.Ref<HTMLDivElement>;
}) {
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn("relative", className)}
      {...props}
    >
      {/* [&>div]:!block —— Radix 在 Viewport 内包一层 display:table 的 div 做测量，它会按
          内容 max-content 撑宽、让 truncate 行失效并横向溢出；强制 block 修掉（shadcn
          官方同款）。只命中 Radix 那层 div，不影响各调用方自己的内容。
          max-h-[inherit] —— Viewport 才是真滚动容器，而它的 size-full(height:100%) 只在
          祖先链高度 definite 时可解析；auto 高度 + max-h 封顶的 overlay（如编辑条目弹窗）
          链上高度 indefinite，height:100% 按 CSS 规范回退 auto → Viewport 被内容撑到全高、
          内部无溢出 → 滚轮失效且滚动条永不出现（2026-09-04 实测根因）。继承调用方加在
          Root 上的 max-h 封顶后 Viewport 有界、恢复滚动；Root 无封顶时 inherit 为 none，
          定高链路（聊天栏等）行为完全不变。用任意值写法：v4 无裸 max-h-inherit 工具类。 */}
      <ScrollAreaPrimitive.Viewport
        ref={viewportRef}
        data-slot="scroll-area-viewport"
        className="focus-visible:ring-ring/50 size-full max-h-[inherit] rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:outline-1 [&>div]:!block"
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollBar />
      {horizontal && <ScrollBar orientation="horizontal" />}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  );
}

function ScrollBar({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    // 悬浮细滚动条（2026-09-04）：overlay 不占布局宽度、无上下箭头；配合 Root 的
    // type="scroll" + scrollHideDelay 只在滚动时浮现、停下几秒后 data-state 淡出。
    // 轨道调细 w-1.5（thumb≈4px）贴“不明显”诉求。
    // 隐藏态（含淡出动画期间）pointer-events-none，防透明轨道抢内容右缘的点击。
    // 注：曾以为淡出卸载会把 Viewport 的 overflowY 打回 hidden 而加 forceMount——
    // 实测 @radix-ui/react-scroll-area@1.2.10 中置 scrollbarYEnabled 的 effect 挂在
    // 常驻的外层 Scrollbar 上，与 Presence 卸载无关，forceMount 已回退。
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      className={cn(
        "flex touch-none p-px transition-colors select-none",
        "data-[state=visible]:animate-in data-[state=hidden]:animate-out data-[state=visible]:fade-in-0 data-[state=hidden]:fade-out-0",
        "data-[state=hidden]:pointer-events-none",
        orientation === "vertical" &&
          "h-full w-1.5 border-l border-l-transparent",
        orientation === "horizontal" &&
          "h-1.5 flex-col border-t border-t-transparent",
        className,
      )}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb
        data-slot="scroll-area-thumb"
        className="bg-border relative flex-1 rounded-full"
      />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  );
}

export { ScrollArea, ScrollBar };
