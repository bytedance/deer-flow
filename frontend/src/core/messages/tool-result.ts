type ToolResultMessage = {
  type?: string;
  tool_call_id?: string;
  tool_calls?: Array<{ id?: string }>;
};

/** Pair results with assistant occurrences, preserving unique leading SDK results. */
export function indexToolResults<T extends ToolResultMessage>(
  messages: readonly T[],
) {
  const results = new Map<number, T[]>();
  let groupStart = 0;
  for (let end = 0; end <= messages.length; end += 1) {
    if (end < messages.length && messages[end]?.type !== "human") continue;

    const uniqueOwners = new Map<string, number>();
    const previousAssistant = new Map<number, number>();
    let assistantIndex = -1;
    for (let index = groupStart; index < end; index += 1) {
      const message = messages[index]!;
      if (message.type !== "ai") continue;
      previousAssistant.set(index, assistantIndex);
      assistantIndex = index;
      for (const call of message.tool_calls ?? []) {
        if (!call.id) continue;
        uniqueOwners.set(call.id, uniqueOwners.has(call.id) ? -1 : index);
      }
    }

    assistantIndex = -1;
    let assistantCalls = new Set<string | undefined>();
    for (let index = groupStart; index < end; index += 1) {
      const message = messages[index]!;
      if (message.type === "ai") {
        assistantIndex = index;
        assistantCalls = new Set(message.tool_calls?.map((call) => call.id));
      }
      if (message.type !== "tool" || !message.tool_call_id) continue;
      const uniqueOwner = uniqueOwners.get(message.tool_call_id);
      // Only the next assistant can own a leading result. Never bridge a human
      // or another assistant, and never guess forward when a call ID repeats.
      const owner =
        uniqueOwner !== undefined &&
        uniqueOwner > index &&
        previousAssistant.get(uniqueOwner)! < index
          ? uniqueOwner
          : assistantCalls.has(message.tool_call_id)
            ? assistantIndex
            : -1;
      if (owner < 0) continue;
      const owned = results.get(owner);
      if (owned) owned.push(message);
      else results.set(owner, [message]);
    }
    groupStart = end + 1;
  }
  return results;
}
