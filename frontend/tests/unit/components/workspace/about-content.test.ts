import { describe, expect, it } from "vitest";

import { aboutMarkdown } from "@/components/workspace/settings/about-content";

describe("about-content", () => {
  it("contains industrial positioning headline", () => {
    expect(aboutMarkdown).toContain("工业设备智能诊断与监测平台");
  });

  it("mentions the target industry", () => {
    expect(aboutMarkdown).toContain("石油石化");
  });

  it("lists core capabilities", () => {
    expect(aboutMarkdown).toContain("实时监测");
    expect(aboutMarkdown).toContain("智能诊断");
    expect(aboutMarkdown).toContain("运行报告");
    expect(aboutMarkdown).toContain("对话操作");
  });

  it("includes industrial intelligence vision statement", () => {
    expect(aboutMarkdown).toContain("工业智能愿景");
  });

  it("contains contact information", () => {
    expect(aboutMarkdown).toContain("support@inscphm.com");
  });
});
