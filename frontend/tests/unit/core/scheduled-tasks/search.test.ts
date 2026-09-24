import { expect, test } from "@rstest/core";

import { matchesScheduledTaskQuery } from "@/core/scheduled-tasks/search";

const task = {
  title: "Weekly REPORT [draft]",
  prompt: "汇总项目进度 and revenue",
};

test.each([
  ["", true],
  ["   ", true],
  [" report ", true],
  ["REVENUE", true],
  ["项目进度", true],
  ["[draft]", true],
  [".*", false],
  ["missing", false],
  ["draft] 汇总", false],
])(
  "matches query %s as a literal title or prompt substring",
  (query, expected) => {
    expect(matchesScheduledTaskQuery(task, query)).toBe(expected);
  },
);
