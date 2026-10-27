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
 *
 * Candidates are restricted to `assistant` groups, unlike
 * `getRunDurationDisplaysByGroupIndex`, which accepts a run's last group of any
 * type. The asymmetry is load-bearing rather than an oversight: run duration is
 * rendered by `MessageList` around every group, while this card is rendered by
 * `MessageListItem`, which `MessageList` invokes only for `human`/`assistant`
 * groups. Anchoring a run that ends in an `assistant:processing` group would
 * pick a position that never renders and silently drop the card, so do not
 * unify the two helpers.
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
