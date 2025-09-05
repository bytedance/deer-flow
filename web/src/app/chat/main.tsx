// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo } from "react";

import { useStore } from "~/core/store";
import { cn } from "~/lib/utils";

import { AgentStatus } from "./components/agent-status";
import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";

export default function Main() {
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = useMemo(
    () => openResearchId !== null,
    [openResearchId],
  );
  return (
    <>
      <AgentStatus />
      <div
        className={cn(
          "flex h-full w-full justify-center-safe px-4 pt-12 pb-4",
          doubleColumnMode && "gap-8",
        )}
      >
        <MessagesBlock
          className={cn(
            "shrink-0 transition-all duration-300 ease-out",
            !doubleColumnMode &&
              `w-[768px] translate-x-[min(max(calc((100vw-538px)*0.75),575px)/2,960px/2)]`,
            doubleColumnMode && `w-[538px]`,
          )}
        />
        <ResearchBlock
          className={cn(
            "w-[min(max(calc((100vw-538px)*0.75),575px),960px)] pb-4 transition-all duration-300 ease-out",
            !doubleColumnMode && "scale-0",
            doubleColumnMode && "",
          )}
          researchId={openResearchId}
        />
      </div>
    </>
  );
}
