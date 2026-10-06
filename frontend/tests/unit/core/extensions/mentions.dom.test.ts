import { expect, it } from "@rstest/core";

import {
  referenceToken,
  renderReferenceEditor,
} from "@/components/workspace/mentions/inline-references";
import { extensionMentionId } from "@/core/extensions/mentions";

it("renders plugin references with a distinct glyph and color from conversations", () => {
  const root = document.createElement("div");
  const plugin = referenceToken(
    "extension",
    extensionMentionId({
      namespace: "community.team",
      provider: "people",
      id: "alice",
      label: "Alice",
    }),
    "Alice",
  );
  const conversation = referenceToken("conversation", "thread", "Conversation");
  renderReferenceEditor(root, `${plugin} ${conversation}`);
  const extensionChip = root.querySelector<HTMLElement>(
    '[data-reference-kind="extension"]',
  )!;
  const conversationChip = root.querySelector<HTMLElement>(
    '[data-reference-kind="conversation"]',
  )!;
  expect(extensionChip.firstElementChild?.textContent).toBe("◈");
  expect(conversationChip.firstElementChild?.textContent).toBe("◉");
  expect(extensionChip.className).not.toBe(conversationChip.className);
});
