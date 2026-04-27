"use client";

import { GitBranch, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { useCreateThreadBranch, useThreadRecord } from "@/core/threads/hooks";
import {
  agentNameOfThreadMetadata,
  isBranchThreadMetadata,
  pathOfThread,
} from "@/core/threads/utils";

import { Tooltip } from "./tooltip";

type ThreadBranchActionsProps = {
  threadId: string;
  isNewThread: boolean;
  isStreaming: boolean;
  isMock?: boolean;
  title?: string | null;
  agentName?: string;
};

export function ThreadBranchActions({
  threadId,
  isNewThread,
  isStreaming,
  isMock,
  title,
  agentName,
}: ThreadBranchActionsProps) {
  const { t } = useI18n();
  const router = useRouter();
  const { data: threadRecord } = useThreadRecord(
    !isNewThread && !isMock ? threadId : null,
  );
  const createBranchMutation = useCreateThreadBranch();

  const metadata = threadRecord?.metadata;
  const routeAgentName = agentName ?? agentNameOfThreadMetadata(metadata);
  const isBranch = isBranchThreadMetadata(metadata);
  const parentThreadId =
    typeof metadata?.return_thread_id === "string"
      ? metadata.return_thread_id
      : typeof metadata?.parent_thread_id === "string"
        ? metadata.parent_thread_id
        : undefined;
  const branchDisabled = isNewThread || (isMock ?? false) || isStreaming;

  const handleCreateBranch = async () => {
    try {
      const branchName = title?.trim()
        ? `${title.trim()} / ${t.branching.branch}`
        : t.branching.sideBranchDefaultName;

      const branch = await createBranchMutation.mutateAsync({
        threadId,
        body: {
          branch_name: branchName,
          copy_uploads: true,
          metadata: routeAgentName ? { agent_name: routeAgentName } : {},
        },
      });

      toast.success(t.branching.branchCreated);
      void router.push(
        pathOfThread(
          branch.thread_id,
          agentNameOfThreadMetadata(branch.metadata),
        ),
      );
    } catch (error) {
      toast.error(
        error instanceof Error && error.message.trim()
          ? error.message
          : t.branching.branchCreateFailed,
      );
    }
  };

  return (
    <div className="flex items-center gap-2">
      {isBranch ? (
        <div className="text-muted-foreground inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs">
          <GitBranch className="h-3.5 w-3.5" />
          <span>{t.branching.branch}</span>
        </div>
      ) : null}

      {isBranch && parentThreadId ? (
        <Tooltip content={t.branching.backToParentDescription}>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              void router.push(pathOfThread(parentThreadId, routeAgentName))
            }
          >
            <Undo2 className="h-4 w-4" />
            <span className="hidden sm:inline">{t.branching.backToParent}</span>
          </Button>
        </Tooltip>
      ) : null}

      <Tooltip
        content={
          isStreaming
            ? t.branching.branchDisabledWhileStreaming
            : t.branching.newBranchDescription
        }
      >
        <Button
          size="sm"
          variant="ghost"
          disabled={branchDisabled || createBranchMutation.isPending}
          onClick={() => void handleCreateBranch()}
        >
          <GitBranch className="h-4 w-4" />
          <span className="hidden sm:inline">{t.branching.newBranch}</span>
        </Button>
      </Tooltip>
    </div>
  );
}
