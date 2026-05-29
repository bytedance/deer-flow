import { describe, expect, test } from "vitest";

import {
  CHAT_COMPOSER_INPUT_BOX_CLASSNAME,
  getChatComposerDockClassName,
  getChatComposerFrameClassName,
} from "@/components/workspace/chat-composer-layout";

describe("chat composer layout", () => {
  test("applies the vertical offset on the dock instead of the input box", () => {
    expect(getChatComposerDockClassName()).toContain("-translate-y-4");
    expect(CHAT_COMPOSER_INPUT_BOX_CLASSNAME).not.toContain("-translate-y-4");
  });

  test("uses the centered new-thread layout when starting a conversation", () => {
    const className = getChatComposerFrameClassName(true);

    expect(className).toContain("-translate-y-[calc(50vh-96px)]");
    expect(className).toContain("max-w-(--container-width-sm)");
  });

  test("uses the wider dock width for existing conversations", () => {
    const className = getChatComposerFrameClassName(false);

    expect(className).not.toContain("-translate-y-[calc(50vh-96px)]");
    expect(className).toContain("max-w-(--container-width-md)");
  });
});
