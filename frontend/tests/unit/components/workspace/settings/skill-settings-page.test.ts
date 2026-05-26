import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";
import type { Skill } from "@/core/skills/type";

const mockSkills: Skill[] = [
  {
    id: "skill-1",
    name: "vibration-fault-diagnosis",
    description: "振动分析与故障诊断",
    tier: "core-industrial",
    enabled: true,
    category: "public",
  },
  {
    id: "skill-2",
    name: "trend-report",
    description: "生成趋势报告",
    tier: "core-industrial",
    enabled: true,
    category: "public",
  },
  {
    id: "skill-3",
    name: "data-analysis",
    description: "通用数据分析",
    tier: "foundation",
    enabled: true,
    category: "public",
  },
  {
    id: "skill-4",
    name: "custom-industrial-skill",
    description: "自定义工业技能",
    tier: "core-industrial",
    enabled: false,
    category: "custom",
  },
];

vi.mock("@/core/skills/hooks", () => ({
  useSkills: vi.fn(() => ({
    skills: mockSkills,
    isLoading: false,
    error: null,
  })),
  useEnableSkill: vi.fn(() => ({
    mutate: vi.fn(),
  })),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: vi.fn(() => ({
    t: {
      settings: {
        skills: {
          title: "Skills",
          description: "Manage your skills",
          createSkill: "Create Skill",
          emptyTitle: "No skills",
          emptyDescription: "Create your first skill",
          emptyButton: "Create",
        },
      },
      common: {
        loading: "Loading...",
        public: "Public",
        custom: "Custom",
      },
    },
    locale: "en",
  })),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
  })),
}));

vi.mock("@/env", () => ({
  env: {
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false",
  },
}));

describe("SkillSettingsPage", () => {
  it("renders skill list with tier badges", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    expect(html).toContain("vibration-fault-diagnosis");
    expect(html).toContain("trend-report");
    expect(html).toContain("data-analysis");

    // Tier labels are rendered (Industrial/Foundation text)
    expect(html).toContain("Industrial");
    expect(html).toContain("Foundation");
  });

  it("renders tier filter tabs", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    expect(html).toContain(">All<");
    expect(html).toContain("Industrial");
    expect(html).toContain("Foundation");
  });

  it("renders category tabs and search input", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    expect(html).toContain(">Public<");
    expect(html).toContain(">Custom<");
    expect(html).toContain('placeholder="Search skills..."');
  });

  it("renders skill descriptions", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    expect(html).toContain("振动分析与故障诊断");
    expect(html).toContain("生成趋势报告");
    expect(html).toContain("通用数据分析");
  });

  it("renders create skill button", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    expect(html).toContain("Create Skill");
  });

  it("renders tier icons via SVG paths", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    // Factory icon (industrial tier) has distinctive path
    expect(html).toContain("lucide-factory");
    // Wrench icon (foundation tier) has distinctive path
    expect(html).toContain("lucide-wrench");
  });

  it("shows skills grouped by tier correctly", () => {
    const html = renderToStaticMarkup(React.createElement(SkillSettingsPage));

    // Two public industrial skills + one custom industrial = 3 Industrial badges
    // One foundation skill = 1 Foundation badge
    const industrialMatches = html.match(/Industrial/g);
    const foundationMatches = html.match(/Foundation/g);

    expect(industrialMatches).not.toBeNull();
    expect(industrialMatches!.length).toBeGreaterThanOrEqual(2);
    expect(foundationMatches).not.toBeNull();
    expect(foundationMatches!.length).toBeGreaterThanOrEqual(1);
  });
});
