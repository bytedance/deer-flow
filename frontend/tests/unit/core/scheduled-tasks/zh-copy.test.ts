import { describe, expect, test } from "@rstest/core";

import { fill } from "@/components/workspace/scheduled-tasks/shared";
import { zhCN } from "@/core/i18n/locales/zh-CN";

/** Every string leaf of a copy tree, with its dotted path. */
function leaves(node: unknown, path: string): [string, string][] {
  if (typeof node === "string") {
    return [[path, node]];
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([key, value]) =>
      leaves(value, `${path}.${key}`),
    );
  }
  return [];
}

describe("zh-CN scheduled-task copy", () => {
  test("an interpolated time, date or number is followed by a space before Chinese", () => {
    const glued = leaves(zhCN.scheduledTasks, "scheduledTasks").filter(
      ([, text]) => /\{[a-z_]+\}[一-鿿]/i.test(text),
    );
    expect(glued).toEqual([]);
  });

  test("times read with a space on both sides of the clock", () => {
    const st = zhCN.scheduledTasks;
    expect(fill(st.stop.reached, { time: "今天 16:48" })).toBe(
      "已于今天 16:48 满足",
    );
    expect(fill(st.notice.pausedByAgentBody, { time: "今天 16:48" })).toMatch(
      /^在今天 16:48 的运行中，/,
    );
  });
});
