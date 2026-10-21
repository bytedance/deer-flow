import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { buildConversationChapters } from "@/core/messages/conversation-outline";
import {
  getMessageCopyData,
  getMessageGroups,
  hasStructuredUploadContext,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import {
  formatThreadAsJSON,
  formatThreadAsMarkdown,
} from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";

const context = {
  version: 1,
  text: "<current_uploads>INTERNAL_FILE_OUTLINE</current_uploads>",
};
const thread = {
  thread_id: "thread",
  metadata: { title: "Uploads" },
  values: { messages: [] },
} as unknown as AgentThread;

function human(
  content: Message["content"],
  metadata: unknown = context,
): Message {
  return {
    type: "human",
    id: "turn",
    content,
    additional_kwargs: { deerflow_upload_context: metadata },
  } as Message;
}

describe("structured upload context", () => {
  it("keeps literal control-tag examples in grouping and conversation titles", () => {
    const message = human(
      "<slash_skill_activation>example</slash_skill_activation>",
    );
    expect(isHiddenFromUIMessage(message)).toBe(false);
    const chapters = buildConversationChapters(
      getMessageGroups([message]),
      "Attachment",
    );
    expect(chapters[0]?.title).toContain("<slash_skill_activation>");
  });
  it("preserves literal tag examples in copy and both export formats", () => {
    const text =
      "Explain <current_uploads>my example</current_uploads> and <memory>literal</memory>.";
    const message = human(text);
    expect(hasStructuredUploadContext(message)).toBe(true);
    expect(getMessageCopyData(message)).toBe(text);
    expect(formatThreadAsMarkdown(thread, [message])).toContain(text);
    const json = formatThreadAsJSON(thread, [message]);
    expect(JSON.parse(json).messages[0].content).toBe(text);
    expect(json).not.toContain("INTERNAL_FILE_OUTLINE");
    expect(json).not.toContain("deerflow_upload_context");
    expect(formatThreadAsMarkdown(thread, [message])).not.toContain(
      "INTERNAL_FILE_OUTLINE",
    );
  });

  it("keeps the historical inline cleanup for unversioned messages", () => {
    const message = human(
      "<current_uploads>legacy.pdf</current_uploads>\n\nQuestion",
      undefined,
    );
    delete message.additional_kwargs?.deerflow_upload_context;
    expect(getMessageCopyData(message)).toBe("Question");
    expect(formatThreadAsMarkdown(thread, [message])).not.toContain(
      "legacy.pdf",
    );
    expect(formatThreadAsJSON(thread, [message])).not.toContain("legacy.pdf");
  });

  it.each(["current_uploads", "uploaded_files"])(
    "contains recaptured legacy %s context in copy, exports and titles",
    (tag) => {
      const message = human(
        `<current_uploads>report.md\npath: /mnt/user-data/uploads/report.md\nDocument outline: NEW_INTERNAL_OUTLINE</current_uploads>\n\n` +
          `<${tag}>old.pdf\npath: /mnt/user-data/uploads/old.pdf\nOLD_INTERNAL_OUTLINE</${tag}>\n\nQuestion`,
      );
      delete message.additional_kwargs?.deerflow_upload_context;
      expect(hasStructuredUploadContext(message)).toBe(false);
      expect(isHiddenFromUIMessage(message)).toBe(false);
      expect(getMessageCopyData(message)).toBe("Question");
      const json = formatThreadAsJSON(thread, [message]);
      expect(JSON.parse(json).messages[0].content).toBe("Question");
      const markdown = formatThreadAsMarkdown(thread, [message]);
      expect(markdown).toContain("Question");
      const chapters = buildConversationChapters(
        getMessageGroups([message]),
        "Attachment",
      );
      expect(chapters[0]?.title).toBe("Question");
      for (const output of [json, markdown, chapters[0]?.title ?? ""]) {
        expect(output).not.toContain("/mnt/user-data/uploads/");
        expect(output).not.toContain("INTERNAL_OUTLINE");
      }
    },
  );

  it.each(
    [
      null,
      [],
      "context",
      { version: true, text: "x" },
      { version: 2, text: "x" },
      { version: 1, text: [] },
    ].map((metadata) => ({ metadata })),
  )(
    "does not disable legacy containment for unsupported metadata %j",
    ({ metadata }) => {
      const message = human(
        "<current_uploads>legacy.pdf</current_uploads>\n\nQuestion",
        metadata,
      );
      expect(hasStructuredUploadContext(message)).toBe(false);
      expect(getMessageCopyData(message)).toBe("Question");
    },
  );

  it("does not treat assistant metadata as a user-content declaration", () => {
    const message = {
      ...human("<memory>internal</memory>Answer"),
      type: "ai",
    } as Message;
    expect(hasStructuredUploadContext(message)).toBe(false);
    expect(formatThreadAsMarkdown(thread, [message])).not.toContain("internal");
  });

  it("retains multimodal user text and image links while excluding internal metadata", () => {
    const message = human([
      { type: "text", text: "<current_uploads>literal</current_uploads>" },
      {
        type: "image_url",
        image_url: { url: "https://example.com/image.png" },
      },
    ]);
    const copied = getMessageCopyData(message);
    expect(copied).toContain("<current_uploads>literal</current_uploads>");
    expect(copied).toContain("https://example.com/image.png");
  });
});
