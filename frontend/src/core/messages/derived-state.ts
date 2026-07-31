import type { Message } from "@langchain/langgraph-sdk";

import { getMessageRunId } from "./run-duration";
import {
  getMessageGroups,
  isHiddenFromUIMessage,
  type MessageGroup,
} from "./utils";

function messageStableKey(message: Message) {
  if (
    message.type === "tool" &&
    typeof message.tool_call_id === "string" &&
    message.tool_call_id.length > 0
  ) {
    return `tool:${message.tool_call_id}`;
  }
  if (typeof message.id === "string" && message.id.length > 0) {
    return `message:${message.id}`;
  }
  return null;
}

function sameMessageIdentity(previous: Message, next: Message) {
  if (previous === next) return true;
  if (previous.type !== next.type) return false;
  const previousKey = messageStableKey(previous);
  return previousKey !== null && previousKey === messageStableKey(next);
}

function canReuseMessageGroup(
  previous: MessageGroup | undefined,
  next: MessageGroup,
): previous is MessageGroup {
  if (
    !previous ||
    previous.id !== next.id ||
    previous.type !== next.type ||
    previous.messages.length !== next.messages.length
  ) {
    return false;
  }
  return previous.messages.every((message, index) => {
    const nextMessage = next.messages[index];
    return (
      nextMessage !== undefined &&
      sameMessageIdentity(message, nextMessage) &&
      getMessageRunId(message) === getMessageRunId(nextMessage) &&
      Object.is(
        message.additional_kwargs?.turn_duration,
        nextMessage.additional_kwargs?.turn_duration,
      )
    );
  });
}

function stabilizeGroups(
  nextGroups: MessageGroup[],
  previousGroups: readonly MessageGroup[],
  activeGroupIndex: number,
) {
  return nextGroups.map((group, index) =>
    index !== activeGroupIndex &&
    canReuseMessageGroup(previousGroups[index], group)
      ? previousGroups[index]
      : group,
  );
}

export function deriveStableMessageGroups(
  messages: Message[],
  isLoading: boolean,
  previousGroups: readonly MessageGroup[],
  previousIsLoading: boolean,
): MessageGroup[] {
  if (isLoading && previousGroups.length > 0) {
    let turnStartIndex = -1;
    for (let index = messages.length - 1; index >= 0; index--) {
      const candidate = messages[index];
      if (candidate?.type === "human" && !isHiddenFromUIMessage(candidate)) {
        turnStartIndex = index;
        break;
      }
    }

    const turnStartMessage = messages[turnStartIndex];
    let previousTurnStartGroupIndex = -1;
    if (turnStartMessage) {
      for (let index = previousGroups.length - 1; index >= 0; index -= 1) {
        const group = previousGroups[index];
        if (
          group?.type === "human" &&
          group.messages.some((message) =>
            sameMessageIdentity(message, turnStartMessage),
          )
        ) {
          previousTurnStartGroupIndex = index;
          break;
        }
      }
    }

    if (turnStartIndex >= 0 && previousTurnStartGroupIndex >= 0) {
      const prefix = previousGroups.slice(0, previousTurnStartGroupIndex);
      const previousTail = previousGroups.slice(previousTurnStartGroupIndex);
      const nextTail = getMessageGroups(messages.slice(turnStartIndex), {
        isCurrentTurnLoading: true,
      });
      const stableTail = stabilizeGroups(
        nextTail,
        previousTail,
        nextTail.length - 1,
      );
      return [...prefix, ...stableTail];
    }
  }

  const nextGroups = getMessageGroups(messages, {
    isCurrentTurnLoading: isLoading,
  });
  const activeGroupIndex =
    isLoading || previousIsLoading ? nextGroups.length - 1 : -1;
  return stabilizeGroups(nextGroups, previousGroups, activeGroupIndex);
}

export type AssistantTurnUsageState = {
  groups: readonly MessageGroup[];
  byGroupIndex: Array<Message[] | null>;
};

export function deriveAssistantTurnUsageState(
  groups: readonly MessageGroup[],
  previous?: AssistantTurnUsageState,
): AssistantTurnUsageState {
  let firstChangedIndex = 0;
  if (previous) {
    const commonLength = Math.min(groups.length, previous.groups.length);
    while (
      firstChangedIndex < commonLength &&
      groups[firstChangedIndex] === previous.groups[firstChangedIndex]
    ) {
      firstChangedIndex += 1;
    }
    if (
      firstChangedIndex === groups.length &&
      groups.length === previous.groups.length
    ) {
      return previous;
    }
  }

  let recomputeStart = firstChangedIndex;
  while (
    recomputeStart > 0 &&
    groups[recomputeStart]?.type !== "human" &&
    groups[recomputeStart - 1]?.type !== "human"
  ) {
    recomputeStart -= 1;
  }

  const byGroupIndex: Array<Message[] | null> = Array.from(
    { length: groups.length },
    (_, index) =>
      index < recomputeStart ? (previous?.byGroupIndex[index] ?? null) : null,
  );
  let turnStartIndex: number | null = null;
  for (let index = recomputeStart; index < groups.length; index += 1) {
    const group = groups[index];
    if (!group) continue;
    if (group.type === "human") {
      turnStartIndex = null;
      continue;
    }
    turnStartIndex ??= index;
    const nextGroup = groups[index + 1];
    if (nextGroup && nextGroup.type !== "human") continue;
    byGroupIndex[index] = groups
      .slice(turnStartIndex, index + 1)
      .flatMap((currentGroup) => currentGroup.messages)
      .filter((message) => message.type === "ai");
    turnStartIndex = null;
  }

  return { groups, byGroupIndex };
}
