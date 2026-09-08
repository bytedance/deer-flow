import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  buildConversationChapters,
  CONVERSATION_CHAPTER_TITLE_MAX_LENGTH,
  CONVERSATION_OUTLINE_MIN_TURNS,
} from "@/core/messages/conversation-outline";
import { getMessageGroups } from "@/core/messages/utils";

function message(
  type: Message["type"],
  id: string | undefined,
  content: Message["content"],
): Message {
  return { type, id, content } as Message;
}

describe("conversation outline model", () => {
  it("creates one ordered chapter per visible human turn", () => {
    const groups = getMessageGroups([
      message("human", "human-1", "First question"),
      message("ai", "assistant-1", "First answer"),
      message("human", "human-2", "Second question"),
      {
        ...message("ai", "tool-call", ""),
        tool_calls: [{ id: "call-1", name: "bash", args: {} }],
      } as Message,
      {
        ...message("tool", "tool-result", "done"),
        tool_call_id: "call-1",
      } as Message,
      message("ai", "assistant-2", "Second answer"),
    ]);

    expect(buildConversationChapters(groups, "Attachment")).toEqual([
      {
        id: "human-1",
        groupIndex: 0,
        title: "First question",
      },
      {
        id: "human-2",
        groupIndex: 2,
        title: "Second question",
      },
    ]);
  });

  it("normalizes whitespace and removes upload metadata", () => {
    const groups = getMessageGroups([
      message("human", "human-1", "  First line\n\n  second\tline  "),
      message(
        "human",
        "human-2",
        "<uploaded_files>\n- report.pdf\n</uploaded_files>\n\nSummarize the report",
      ),
    ]);

    expect(
      buildConversationChapters(groups, "Attachment").map(
        (chapter) => chapter.title,
      ),
    ).toEqual(["First line second line", "Summarize the report"]);
  });

  it("uses the localized fallback for attachment-only structured content", () => {
    const groups = getMessageGroups([
      message("human", "human-image", [
        { type: "image_url", image_url: { url: "data:image/png;base64,x" } },
      ]),
    ]);

    expect(buildConversationChapters(groups, "图片或文件消息")[0]?.title).toBe(
      "图片或文件消息",
    );
  });

  it("truncates by Unicode code points without splitting emoji", () => {
    const content = `${"问".repeat(CONVERSATION_CHAPTER_TITLE_MAX_LENGTH - 1)}😀结尾`;
    const groups = getMessageGroups([message("human", "human-long", content)]);

    const title = buildConversationChapters(groups, "Attachment")[0]?.title;

    expect(Array.from(title ?? "")).toHaveLength(
      CONVERSATION_CHAPTER_TITLE_MAX_LENGTH + 1,
    );
    expect(title?.endsWith("…")).toBe(true);
    expect(title).not.toContain("�");
  });

  it("falls back to a deterministic group key when message ids are absent", () => {
    const groups = getMessageGroups([
      message("human", undefined, "Question"),
      message("ai", undefined, "Answer"),
    ]);

    expect(buildConversationChapters(groups, "Attachment")[0]?.id).toBe(
      "human-turn:0",
    );
  });

  it("exposes the approved long-conversation threshold", () => {
    expect(CONVERSATION_OUTLINE_MIN_TURNS).toBe(5);
  });
});
