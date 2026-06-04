"use client";

import { Suspense, useEffect, useMemo, useRef } from "react";

import { getBlockComponent } from "@/core/genui/registry";
import { sanitizeProps } from "@/core/genui/sanitizer";
import {
  getInteractionKey,
  type UIBlock,
  useBlockStore,
} from "@/core/genui/store";
import { validateProps } from "@/core/genui/validator";

import { BlockErrorBoundary } from "./BlockErrorBoundary";

interface GenUIRendererProps {
  block: UIBlock;
  threadId?: string;
  disableExpiration?: boolean;
  onInteraction?: (
    callbackId: string,
    payload: Record<string, unknown>,
    blockId?: string,
  ) => void;
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

export function GenUIRenderer({ block, threadId, disableExpiration, onInteraction }: GenUIRendererProps) {
  const interactionKey = getInteractionKey(block);
  const interactionState = useBlockStore(
    (state) => interactionKey ? state.interactions.get(interactionKey) : undefined,
  );

  const effectiveInteractionState = useMemo(() => {
    if (interactionState) return interactionState;
    if (block.interactive && block.interaction_status === "submitted") {
      return { status: "submitted" as const };
    }
    return undefined;
  }, [block.interactive, block.interaction_status, interactionState]);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (
      disableExpiration ||
      !block.interactive ||
      !interactionKey ||
      !block.callback_timeout_ms ||
      interactionState?.status === "submitted" ||
      interactionState?.status === "expired"
    ) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      if (interactionKey) {
        useBlockStore.getState().setInteractionExpired(interactionKey);
      }
    }, block.callback_timeout_ms);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [disableExpiration, block.interactive, block.callback_timeout_ms, interactionKey, interactionState?.status]);

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
    interactionState: effectiveInteractionState,
    onInteraction,
  };

  return (
    <BlockErrorBoundary componentName={block.component}>
      <Suspense fallback={<BlockFallback />}>
        <Component block={blockWithSanitizedProps} threadId={threadId} />
      </Suspense>
    </BlockErrorBoundary>
  );
}
