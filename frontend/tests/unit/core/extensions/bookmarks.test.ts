import { expect, rs, test } from "@rstest/core";

import bookmarks from "../../../../../examples/deerflow-extension-bookmarks/deerflow_extension_bookmarks/static/dist/index.mjs";

const prefix = "a".repeat(77);

test.each([
  ["split surrogate pair", `${prefix}\t b😀 remaining answer`, `${prefix} b`],
  ["complete surrogate pair", `${prefix}\t😀`, `${prefix} 😀`],
  ["consecutive emoji", "😀".repeat(80), "😀".repeat(40)],
  [
    "unpaired surrogates",
    "a\uD800b\uDC00c",
    "a\uFFFDb\uFFFDc",
    "a\uFFFDb\uFFFDc",
  ],
])(
  "keeps bookmark labels within 80 UTF-16 units: %s",
  async (_name, answer, label, savedAnswer = answer) => {
    const text = `  ${answer}\n`;
    const callBackend = rs.fn();
    const action = bookmarks.conversationActions(undefined, "en").actions[0]!;

    await action.execute(
      { thread: { thread_id: "thread-1" } },
      {
        latestVisibleAnswer: async () => ({ id: "answer-1", text }),
        callBackend,
        showMessage: rs.fn(),
      },
    );

    expect(callBackend).toHaveBeenCalledExactlyOnceWith("save", {
      thread_id: "thread-1",
      message_id: "answer-1",
      label,
      text: `  ${savedAnswer}\n`,
    });
  },
);
