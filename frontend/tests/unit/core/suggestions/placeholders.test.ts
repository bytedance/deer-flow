import { describe, expect, test } from "@rstest/core";

import { hasUnreplacedPlaceholder } from "@/core/suggestions/placeholders";

describe("hasUnreplacedPlaceholder", () => {
  test("detects Chinese [主题] placeholder", () => {
    expect(
      hasUnreplacedPlaceholder("深入浅出的研究一下[主题]，并总结发现。"),
    ).toBe(true);
  });

  test("detects English [topic] placeholder", () => {
    expect(
      hasUnreplacedPlaceholder(
        "Write a blog post about the latest trends on [topic]",
      ),
    ).toBe(true);
  });

  test("detects Chinese [来源] placeholder", () => {
    expect(hasUnreplacedPlaceholder("从[来源]收集数据并创建报告。")).toBe(true);
  });

  test("detects English [source] placeholder", () => {
    expect(
      hasUnreplacedPlaceholder(
        "Collect data from [source] and create a report.",
      ),
    ).toBe(true);
  });

  test("does not flag normal user text without brackets", () => {
    expect(hasUnreplacedPlaceholder("研究一下2025年最流行的Python框架")).toBe(
      false,
    );
  });

  test("does not flag text with unrelated brackets", () => {
    expect(hasUnreplacedPlaceholder("check [this link] for details")).toBe(
      false,
    );
  });

  test("does not flag empty text", () => {
    expect(hasUnreplacedPlaceholder("")).toBe(false);
  });

  test("does not flag text with only brackets removed", () => {
    expect(hasUnreplacedPlaceholder("深入浅出的研究一下，并总结发现。")).toBe(
      false,
    );
  });

  test("detects placeholder even when surrounded by user text", () => {
    expect(hasUnreplacedPlaceholder("帮我研究一下[主题]然后写个报告")).toBe(
      true,
    );
  });

  test("detects placeholder case-insensitively for English", () => {
    expect(hasUnreplacedPlaceholder("Research [Topic] deeply")).toBe(true);
    expect(hasUnreplacedPlaceholder("Research [TOPIC] deeply")).toBe(true);
  });
});
