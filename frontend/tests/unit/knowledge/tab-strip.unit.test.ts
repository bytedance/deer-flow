/**
 * tab 行折叠边界纯函数（spec 2026-09-28-kb-tabs-overflow §2 D1 乙）：
 * - 全放得下（无溢出）⇒ 全留平铺侧、不扣遮罩宽；
 * - 溢出 ⇒ 有效宽 = 容器宽 − 遮罩宽，"完整放得下"才留平铺侧；
 * - 半露 / 被遮罩盖住的项一律归折叠侧（宁可多收，不截断）。
 */
import { describe, expect, it } from "@rstest/core";

import { computeFoldCount } from "@/components/workspace/knowledge/tab-strip.utils";

describe("computeFoldCount（D1 乙 固定折叠边界）", () => {
  it("① 全放得下：N=全部、不扣遮罩宽", () => {
    // 480 在 500 内完整放下；若误扣 40 ⇒ 480 > 460 被折，暴露退化。
    expect(computeFoldCount(500, [100, 200, 480], 40)).toBe(3);
  });

  it("② 溢出：有效宽扣遮罩宽，只留完整项", () => {
    expect(computeFoldCount(300, [100, 200, 300, 400], 40)).toBe(2);
  });

  it("③ 半露 / 被遮罩盖住的项归折叠侧", () => {
    // 330 完整在容器内但落在 40px 遮罩区 ⇒ 归尾；400 半露 ⇒ 归尾。
    expect(computeFoldCount(350, [100, 200, 330, 400], 40)).toBe(2);
  });

  it("④ 仅 1 个放得下（有效宽恰等）", () => {
    expect(computeFoldCount(120, [80, 200, 300], 40)).toBe(1);
  });

  it("⑤ 空表 0", () => {
    expect(computeFoldCount(500, [], 40)).toBe(0);
  });
});
