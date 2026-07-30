export function hasActiveWriteForArtifact(
  messages: readonly unknown[],
  filepath: string,
) {
  for (const message of [...messages].reverse()) {
    if (typeof message !== "object" || message === null) {
      continue;
    }
    if (Reflect.get(message, "type") !== "ai") {
      continue;
    }
    const toolCalls = Reflect.get(message, "tool_calls");
    if (!Array.isArray(toolCalls)) {
      continue;
    }
    for (const toolCall of toolCalls) {
      if (typeof toolCall !== "object" || toolCall === null) {
        continue;
      }
      const name = Reflect.get(toolCall, "name");
      const args = Reflect.get(toolCall, "args");
      if (
        (name !== "write_file" && name !== "str_replace") ||
        typeof args !== "object" ||
        args === null ||
        Reflect.get(args, "path") !== filepath
      ) {
        continue;
      }
      const toolCallId = Reflect.get(toolCall, "id");
      if (
        typeof toolCallId === "string" &&
        !messages.some(
          (candidate) =>
            typeof candidate === "object" &&
            candidate !== null &&
            Reflect.get(candidate, "type") === "tool" &&
            Reflect.get(candidate, "tool_call_id") === toolCallId,
        )
      ) {
        return true;
      }
    }
  }
  return false;
}
