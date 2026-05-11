"use client";

import { Suspense, useEffect, useRef } from "react";

import { getBlockComponent } from "@/core/genui/registry";
import { sanitizeProps } from "@/core/genui/sanitizer";
import { type UIBlock, useBlockStore } from "@/core/genui/store";
import { validateProps } from "@/core/genui/validator";

import { BlockErrorBoundary } from "./BlockErrorBoundary";

interface GenUIRendererProps {
  block: UIBlock;
  onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
}

function BlockFallback() {
  return (
    <div className="animate-pulse rounded-lg border bg-muted/50 p-4">
      <div className="h-4 w-1/3 rounded bg-muted" />
      <div className="mt-2 h-20 rounded bg-muted" />
    </div>
  );
}

function UnsupportedBlock({ component }: { component: string }) {
  return (
    <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950">
      <p className="text-sm text-yellow-800 dark:text-yellow-200">
        Unsupported component: {component}
      </p>
    </div>
  );
}

export function GenUIRenderer({ block, onInteraction }: GenUIRendererProps) {
  const interactionState = useBlockStore(
    (state) => block.callback_id ? state.interactions.get(block.callback_id) : undefined,
  );

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (
      !block.interactive ||
      !block.callback_id ||
      !block.callback_timeout_ms ||
      interactionState?.status === "submitted" ||
      interactionState?.status === "expired"
    ) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      if (block.callback_id) {
        useBlockStore.getState().setInteractionExpired(block.callback_id);
      }
    }, block.callback_timeout_ms);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [block.interactive, block.callback_id, block.callback_timeout_ms, interactionState?.status]);

  const Component = getBlockComponent(block.component, block.schema_version);

  if (!Component) {
    return <UnsupportedBlock component={block.component} />;
  }

  const sanitizedProps = sanitizeProps(block.component, block.props);

  const validation = validateProps(block.component, sanitizedProps);
  if (!validation.success) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
        <p className="text-sm font-medium text-red-800 dark:text-red-200">
          Invalid props for {block.component}
        </p>
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">
          {validation.error}
        </p>
      </div>
    );
  }

  const blockWithSanitizedProps = {
    ...block,
    props: sanitizedProps,
    interactionState,
    onInteraction,
  };

  return (
    <BlockErrorBoundary componentName={block.component}>
      <Suspense fallback={<BlockFallback />}>
        <Component block={blockWithSanitizedProps} />
      </Suspense>
    </BlockErrorBoundary>
  );
}
