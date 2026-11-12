import type { Message } from "@langchain/langgraph-sdk";

export function isErrorToolMessage(message: Message): boolean {
  if (message.type !== "tool") return false;
  if (message.status === "error") return true;
  const metadata = message.additional_kwargs?.deerflow_tool_meta;
  return (
    typeof metadata === "object" &&
    metadata !== null &&
    "status" in metadata &&
    metadata.status === "error"
  );
}
