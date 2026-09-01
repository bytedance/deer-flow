import { getMessageRunId } from "./run-duration";
import { hasPresentFiles, type MessageGroup } from "./utils";

export interface ArtifactArchiveCandidate {
  runId: string;
}

export function getArtifactArchiveCandidatesByGroupIndex(
  groups: MessageGroup[],
): Array<ArtifactArchiveCandidate | undefined> {
  const candidates = Array<ArtifactArchiveCandidate | undefined>(
    groups.length,
  ).fill(undefined);
  const lastGroupIndexByRunId = new Map<string, number>();

  groups.forEach((group, groupIndex) => {
    if (group.type !== "assistant:present-files") return;

    for (const message of group.messages) {
      if (!hasPresentFiles(message)) continue;
      const runId = getMessageRunId(message);
      if (!runId) continue;
      lastGroupIndexByRunId.set(runId, groupIndex);
    }
  });

  for (const [runId, groupIndex] of lastGroupIndexByRunId) {
    candidates[groupIndex] = { runId };
  }

  return candidates;
}
