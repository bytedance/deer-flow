"use client";

import { useMemo } from "react";

import { GenUIRenderer } from "@/components/genui/GenUIRenderer";
import { type UIBlock } from "@/core/genui/store";

interface PreviewAreaProps {
  componentName: string;
  props: Record<string, unknown> | null;
}

export function PreviewArea({ componentName, props }: PreviewAreaProps) {
  const block: UIBlock | null = useMemo(() => {
    if (!componentName || !props) return null;
    return {
      schema_version: "1.0",
      type: "ui_block",
      action: "create",
      block_id: `debug-${componentName}`,
      component: componentName,
      props,
      interactive: false,
    };
  }, [componentName, props]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-2">
        <h3 className="text-sm font-semibold">预览</h3>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {!componentName && (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            请从左侧选择一个组件
          </div>
        )}
        {componentName && !props && (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            请在 JSON 编辑器中输入有效的 props
          </div>
        )}
        {block && (
          <GenUIRenderer
            block={block}
            disableExpiration
          />
        )}
      </div>
    </div>
  );
}
