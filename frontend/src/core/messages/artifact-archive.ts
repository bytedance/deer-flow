import { getMessageRunId } from "./run-duration";
import {
  extractPresentFilesFromMessage,
  hasPresentFiles,
  type MessageGroup,
} from "./utils";

export interface ArtifactArchiveDisplay {
  runId: string;
  fileCount: number;
}

export function getArtifactArchiveDisplaysByGroupIndex(
  groups: MessageGroup[],
): Array<ArtifactArchiveDisplay | undefined> {
  const displays = Array<ArtifactArchiveDisplay | undefined>(
    groups.length,
  ).fill(undefined);
  const deliveries = new Map<
    string,
    { files: Set<string>; lastGroupIndex: number }
  >();

  groups.forEach((group, groupIndex) => {
    if (group.type !== "assistant:present-files") return;

    for (const message of group.messages) {
      if (!hasPresentFiles(message)) continue;
      const runId = getMessageRunId(message);
      if (!runId) continue;

      const delivery = deliveries.get(runId) ?? {
        files: new Set<string>(),
        lastGroupIndex: groupIndex,
      };
      extractPresentFilesFromMessage(message).forEach((file) =>
        delivery.files.add(file),
      );
      delivery.lastGroupIndex = groupIndex;
      deliveries.set(runId, delivery);
    }
  });

  for (const [runId, delivery] of deliveries) {
    if (delivery.files.size > 1) {
      displays[delivery.lastGroupIndex] = {
        runId,
        fileCount: delivery.files.size,
      };
    }
  }

  return displays;
}
