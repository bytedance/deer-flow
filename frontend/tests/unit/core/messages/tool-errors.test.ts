import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  type ErrorCategory,
  findToolCallErrorInfo,
  isRetryableError,
} from "@/core/messages/tool-errors";

function makeToolMessage(
  toolCallId: string,
  overrides: Partial<Message> & { status?: string } = {},
): Message {
  const { status, ...rest } = overrides;
  return {
    type: "tool",
    tool_call_id: toolCallId,
    content: "Error: Tool 'web_search' failed with ConnectionError: network down",
    name: "web_search",
    additional_kwargs: {},
    ...rest,
    ...(status !== undefined ? { status } : {}),
  } as Message;
}

describe("findToolCallErrorInfo", () => {
  it("returns null when no tool message matches", () => {
    const messages: Message[] = [
      { type: "human", content: "hello" } as Message,
    ];
    expect(findToolCallErrorInfo("tc-1", messages)).toBeNull();
  });

  it("returns null when tool message status is not error", () => {
    const messages: Message[] = [
      makeToolMessage("tc-1", { status: "success" }),
    ];
    expect(findToolCallErrorInfo("tc-1", messages)).toBeNull();
  });

  it("returns error info with category from additional_kwargs", () => {
    const messages: Message[] = [
      makeToolMessage("tc-1", {
        status: "error",
        name: "web_search",
        content: "Error: Tool 'web_search' failed",
        additional_kwargs: {
          error_category: "network_issue",
          suggested_action: "请检查网络连接",
        },
      }),
    ];
    const info = findToolCallErrorInfo("tc-1", messages);
    expect(info).not.toBeNull();
    expect(info!.category).toBe("network_issue");
    expect(info!.suggestedAction).toBe("请检查网络连接");
    expect(info!.toolName).toBe("web_search");
    expect(info!.rawMessage).toContain("failed");
  });

  it("defaults to service_unavailable when category is missing", () => {
    const messages: Message[] = [
      makeToolMessage("tc-2", {
        status: "error",
        content: "Something went wrong",
      }),
    ];
    const info = findToolCallErrorInfo("tc-2", messages);
    expect(info).not.toBeNull();
    expect(info!.category).toBe("service_unavailable");
    expect(info!.suggestedAction).toBe("");
  });

  it("finds error among multiple messages", () => {
    const messages: Message[] = [
      { type: "human", content: "search" } as Message,
      makeToolMessage("tc-3", {
        status: "success",
        content: "result data",
      }),
      makeToolMessage("tc-target", {
        status: "error",
        name: "bash",
        content: "Error: Tool 'bash' failed with TimeoutError",
        additional_kwargs: {
          error_category: "timeout",
          suggested_action: "请稍等一下再试",
        },
      }),
    ];
    const info = findToolCallErrorInfo("tc-target", messages);
    expect(info).not.toBeNull();
    expect(info!.category).toBe("timeout");
    expect(info!.toolName).toBe("bash");
  });
});

describe("isRetryableError", () => {
  it("returns true for network_issue", () => {
    expect(isRetryableError("network_issue")).toBe(true);
  });

  it("returns true for timeout", () => {
    expect(isRetryableError("timeout")).toBe(true);
  });

  it("returns true for rate_limited", () => {
    expect(isRetryableError("rate_limited")).toBe(true);
  });

  it("returns false for service_unavailable", () => {
    expect(isRetryableError("service_unavailable")).toBe(false);
  });

  it("returns false for data_not_found", () => {
    expect(isRetryableError("data_not_found")).toBe(false);
  });

  it("returns false for permission_denied", () => {
    expect(isRetryableError("permission_denied")).toBe(false);
  });
});
