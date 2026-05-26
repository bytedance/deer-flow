import { describe, expect, it } from "vitest";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

describe("i18n industrial-first suggestions", () => {
  describe("en-US", () => {
    const suggestions = enUS.inputBox.suggestions;

    it("has industrial suggestions as the first three", () => {
      expect(suggestions[0]!.suggestion).toBe("Trend");
      expect(suggestions[1]!.suggestion).toBe("Diagnose");
      expect(suggestions[2]!.suggestion).toBe("Spectrum");
    });

    it("all four suggestions are industrial scenarios", () => {
      const labels = suggestions.map((s) => s.suggestion);
      expect(labels).toEqual(["Trend", "Diagnose", "Spectrum", "Daily Report"]);
    });

    it("suggestion prompts reference equipment tags", () => {
      expect(suggestions[0]!.prompt).toContain("[tag]");
      expect(suggestions[1]!.prompt).toContain("[tag]");
      expect(suggestions[2]!.prompt).toContain("[tag]");
    });

    it("placeholder mentions equipment and tag", () => {
      expect(enUS.inputBox.placeholder).toContain("equipment");
      expect(enUS.inputBox.placeholder).toContain("tag");
    });

    it("welcome description mentions equipment and skills", () => {
      expect(enUS.welcome.description).toContain("equipment");
      expect(enUS.welcome.description).toContain("skills");
    });
  });

  describe("zh-CN", () => {
    const suggestions = zhCN.inputBox.suggestions;

    it("has industrial suggestions as the first three", () => {
      expect(suggestions[0]!.suggestion).toBe("趋势");
      expect(suggestions[1]!.suggestion).toBe("诊断");
      expect(suggestions[2]!.suggestion).toBe("频谱");
    });

    it("all four suggestions are industrial scenarios", () => {
      const labels = suggestions.map((s) => s.suggestion);
      expect(labels).toEqual(["趋势", "诊断", "频谱", "日报"]);
    });

    it("placeholder mentions device and tag number", () => {
      expect(zhCN.inputBox.placeholder).toContain("设备");
      expect(zhCN.inputBox.placeholder).toContain("位号");
    });

    it("welcome description mentions device and tag", () => {
      expect(zhCN.welcome.description).toContain("设备");
      expect(zhCN.welcome.description).toContain("位号");
    });
  });
});
