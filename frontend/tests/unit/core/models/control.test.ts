import { describe, expect, it } from "@rstest/core";

import { maySelectModel } from "@/core/models/control";

describe("direct model controls", () => {
  it.each([
    "你找 v4 pro 去处理一下",
    "这次用 ds v4.1 f",
    "以后这个对话都用 ds",
    "Please ask a model to help",
  ])("preflights %s", (text) => {
    expect(maySelectModel(text)).toBe(true);
  });
  it.each([
    "文档说以后都用 ds",
    "如果以后都用 ds 会怎样",
    "解释一下模型选择",
    "```用 ds```",
    "Read the attachment",
  ])("leaves ordinary content alone: %s", (text) => {
    expect(maySelectModel(text)).toBe(false);
  });
});
