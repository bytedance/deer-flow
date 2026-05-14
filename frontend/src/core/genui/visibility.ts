import type { InteractionState, UIBlock } from "./store";

type StandaloneBlockBucketsOptions = {
  claimedBlockIds: string[];
  storeBlockIds: string[];
  historicalMessageBlockIds: string[];
  liveMessageBlockIds: string[];
  preStreamBlockIds: string[];
  blocks: Map<string, UIBlock>;
  interactions: Map<string, InteractionState>;
};

type StandaloneBlockBuckets = {
  historicalBlockIds: string[];
  tailBlockIds: string[];
};

function isSubmittedBlock(
  block: UIBlock | undefined,
  interactions: Map<string, InteractionState>,
): boolean {
  if (!block?.callback_id) {
    return false;
  }
  return interactions.get(block.callback_id)?.status === "submitted";
}

export function partitionStandaloneBlockIds({
  claimedBlockIds,
  storeBlockIds,
  historicalMessageBlockIds,
  liveMessageBlockIds,
  preStreamBlockIds,
  blocks,
  interactions,
}: StandaloneBlockBucketsOptions): StandaloneBlockBuckets {
  const claimed = new Set(claimedBlockIds);
  const historical = new Set(historicalMessageBlockIds);
  const live = new Set(liveMessageBlockIds);
  const preStream = new Set(preStreamBlockIds);
  const hasStreamBoundary = preStream.size > 0;
  const ids = new Set([
    ...storeBlockIds,
    ...historicalMessageBlockIds,
    ...liveMessageBlockIds,
  ]);

  const historicalBlockIds: string[] = [];
  const tailBlockIds: string[] = [];

  for (const id of ids) {
    if (claimed.has(id)) {
      continue;
    }

    const block = blocks.get(id);
    if (isSubmittedBlock(block, interactions)) {
      continue;
    }

    const hasHistoricalAnchor = historical.has(id);
    const hasLiveAnchor = live.has(id);
    const hasMessageAnchor = hasHistoricalAnchor || hasLiveAnchor;
    const wasPresentBeforeStream = preStream.has(id);

    // Recovered-only interactive blocks are usually stale historical forms.
    // Keep them hidden unless they belong to the active stream.
    if (
      block?.interactive &&
      !hasMessageAnchor &&
      (wasPresentBeforeStream || !hasStreamBoundary)
    ) {
      continue;
    }

    if (hasHistoricalAnchor || (!hasMessageAnchor && wasPresentBeforeStream)) {
      historicalBlockIds.push(id);
      continue;
    }

    tailBlockIds.push(id);
  }

  return {
    historicalBlockIds,
    tailBlockIds,
  };
}

export function buildStreamingBlockExclusions(
  ...blockIdGroups: string[][]
): string[] {
  return Array.from(new Set(blockIdGroups.flat()));
}
