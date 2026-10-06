/**
 * 知识面板格式化纯函数（node 环境）。
 *  - formatKnowledgeTimestamp / formatKnowledgeRelativeTime（2026-09-02，方案 Task 2）：
 *    绝对 + 相对时间。相对时间用 Intl.RelativeTimeFormat；测试注入固定 now + 明确时间差，
 *    断言单位关键字（不精确匹配数字格式，规避 ICU 版本差异），"刚刚/just now" 为硬编码精确断言。
 *  - stripSummaryHeading（2026-09-03）：后端 summary = content[:120]，content 以 markdown
 *    「# 实体名」H1 开头，故剥掉这行标题、保留正文（正文里的标题按用户口径保留、不去重）。
 */
import { describe, expect, test } from "@rstest/core";

import {
  formatKnowledgeRelativeTime,
  formatKnowledgeTimestamp,
  stripSummaryHeading,
} from "@/core/knowledge/format";

const NOW = Date.UTC(2026, 8, 2, 12, 0, 0); // 2026-09-02T12:00:00Z
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function iso(msBeforeNow: number): string {
  return new Date(NOW - msBeforeNow).toISOString();
}

describe("formatKnowledgeTimestamp（绝对，现有）", () => {
  test("渲染年-月-日 时:分（zh-CN）", () => {
    const out = formatKnowledgeTimestamp("2026-09-02T12:00:00Z", "zh-CN");
    expect(out).toContain("2026");
    expect(out).toContain("09");
    expect(out).toContain("02");
  });

  test("不可解析值原样返回", () => {
    expect(formatKnowledgeTimestamp("not-a-date", "zh-CN")).toBe("not-a-date");
  });
});

describe("formatKnowledgeRelativeTime（相对，新增）", () => {
  test("<1 分钟：刚刚 / just now（硬编码，不走 Intl）", () => {
    expect(formatKnowledgeRelativeTime(iso(30_000), "zh-CN", NOW)).toBe("刚刚");
    expect(formatKnowledgeRelativeTime(iso(30_000), "en-US", NOW)).toBe(
      "just now",
    );
  });

  test("分钟档", () => {
    expect(formatKnowledgeRelativeTime(iso(5 * MIN), "zh-CN", NOW)).toContain(
      "分钟",
    );
    expect(formatKnowledgeRelativeTime(iso(5 * MIN), "en-US", NOW)).toContain(
      "minute",
    );
  });

  test("小时档", () => {
    expect(formatKnowledgeRelativeTime(iso(3 * HOUR), "zh-CN", NOW)).toContain(
      "小时",
    );
    expect(formatKnowledgeRelativeTime(iso(3 * HOUR), "en-US", NOW)).toContain(
      "hour",
    );
  });

  test("天档", () => {
    expect(formatKnowledgeRelativeTime(iso(3 * DAY), "zh-CN", NOW)).toContain(
      "天",
    );
    expect(formatKnowledgeRelativeTime(iso(3 * DAY), "en-US", NOW)).toContain(
      "day",
    );
  });

  test("月档", () => {
    expect(formatKnowledgeRelativeTime(iso(90 * DAY), "zh-CN", NOW)).toContain(
      "个月",
    );
    expect(formatKnowledgeRelativeTime(iso(90 * DAY), "en-US", NOW)).toContain(
      "month",
    );
  });

  test("年档", () => {
    expect(formatKnowledgeRelativeTime(iso(800 * DAY), "zh-CN", NOW)).toContain(
      "年",
    );
    expect(formatKnowledgeRelativeTime(iso(800 * DAY), "en-US", NOW)).toContain(
      "year",
    );
  });

  test("未来时间也正确（N 分钟后）", () => {
    expect(
      formatKnowledgeRelativeTime(
        new Date(NOW + 5 * MIN).toISOString(),
        "zh-CN",
        NOW,
      ),
    ).toContain("分钟");
  });

  test("不可解析值原样返回", () => {
    expect(formatKnowledgeRelativeTime("not-a-date", "zh-CN", NOW)).toBe(
      "not-a-date",
    );
  });
});

describe("stripSummaryHeading（剥摘要开头 H1 标题行，2026-09-03）", () => {
  test("剥掉开头的 markdown 一级标题行，保留正文", () => {
    expect(
      stripSummaryHeading(
        "# DeerFlow\n\nDeerFlow 是一个 LangGraph 超级代理系统",
      ),
    ).toBe("DeerFlow 是一个 LangGraph 超级代理系统");
  });

  test("标题与正文间的多个空行一并清掉", () => {
    expect(stripSummaryHeading("# Gateway\n\n\n网关负责统一鉴权与路由")).toBe(
      "网关负责统一鉴权与路由",
    );
  });

  test("无空格的 #标题 也剥", () => {
    expect(stripSummaryHeading("#沙箱\n代码在隔离环境中执行")).toBe(
      "代码在隔离环境中执行",
    );
  });

  test("正文里再次出现的标题保留（有语义的定义句，不去重）", () => {
    expect(stripSummaryHeading("# DeerFlow\n\nDeerFlow 具备沙箱执行能力")).toBe(
      "DeerFlow 具备沙箱执行能力",
    );
  });

  test("只有标题行、无正文时返回空串", () => {
    expect(stripSummaryHeading("# DeerFlow")).toBe("");
    expect(stripSummaryHeading("# DeerFlow\n")).toBe("");
  });

  test("不以 # 开头时原样返回（人工卡片内容通常无 H1）", () => {
    expect(stripSummaryHeading("周五下午不发布")).toBe("周五下午不发布");
  });

  test("只剥开头一行标题，正文中的 ## 子标题不动", () => {
    expect(stripSummaryHeading("# 标题\n\n## 小节\n正文")).toBe(
      "## 小节\n正文",
    );
  });

  test("多级标题（## / ###）也能剥", () => {
    expect(stripSummaryHeading("## 二级标题\n正文内容")).toBe("正文内容");
  });
});
