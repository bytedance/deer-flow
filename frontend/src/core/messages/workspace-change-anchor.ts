import { getMessageRunId } from "./run-duration";
import type { MessageGroup } from "./utils";

/**
 * Locate the single UI position that owns each run's workspace-change summary.
 * The card is resolved from `(threadId, runId)` alone, so every AI message of a
 * run renders an identical copy — and a run ends in more than one terminal
 * assistant bubble whenever the model emits intermediate answer text that never
 * gains a tool call. Anchor the card on the run's last assistant bubble instead
 * of repeating it under each one (#4555).
 *
 * Returns group indices rather than message ids because terminal assistant
 * groups hold exactly one message and that message's id may be absent.
 */
export function getWorkspaceChangeAnchorGroupIndices(
  groups: MessageGroup[],
): Set<number> {
  const anchorByRunId = new Map<string, number>();

  groups.forEach((group, groupIndex) => {
    if (group.type !== "assistant") {
      return;
    }
    for (const message of group.messages) {
      if (message.type !== "ai") {
        continue;
      }
      const runId = getMessageRunId(message);
      if (runId) {
        anchorByRunId.set(runId, groupIndex);
      }
    }
  });

  return new Set(anchorByRunId.values());
}
