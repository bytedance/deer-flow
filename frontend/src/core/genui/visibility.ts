import { getInteractionKey, type InteractionState, type UIBlock } from "./store";

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

export function isSubmittedBlock(
  block: UIBlock | undefined,
  interactions: Map<string, InteractionState>,
): boolean {
  if (!block) {
    return false;
  }
  const interactionKey = getInteractionKey(block);
  if (!interactionKey) {
    return false;
  }
  return interactions.get(interactionKey)?.status === "submitted";
}

export function filterSupersededInteractiveBlockIds(
  blockIds: string[],
  blocks: Map<string, UIBlock>,
): string[] {
  const latestBlockIdByCallback = new Map<string, string>();

  for (const block of blocks.values()) {
    if (!block.parent_id && block.interactive && block.callback_id) {
      latestBlockIdByCallback.set(block.callback_id, block.block_id);
    }
  }

  const seen = new Set<string>();

  return blockIds.filter((id) => {
    if (seen.has(id)) {
      return false;
    }
    seen.add(id);

    const block = blocks.get(id);
    if (!block?.interactive || !block.callback_id) {
      return true;
    }

    return latestBlockIdByCallback.get(block.callback_id) === id;
  });
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

    // Keep blocks with functional_interaction visible across historical turns.
    if (
      block?.interactive &&
      block?.functional_interaction &&
      wasPresentBeforeStream
    ) {
      historicalBlockIds.push(id);
      continue;
    }

    // Hide interactive blocks from previous turns (wasPresentBeforeStream),
    // and orphan interactive blocks on page refresh (no stream boundary + no anchor).
    if (
      block?.interactive &&
      (wasPresentBeforeStream || (!hasStreamBoundary && !hasMessageAnchor))
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
