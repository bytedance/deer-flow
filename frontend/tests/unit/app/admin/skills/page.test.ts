import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

const mockSkills = [
  {
    id: "skill-1",
    name: "vibration-fault-diagnosis",
    description: "Vibration analysis and fault diagnosis",
    tier: "core-industrial" as const,
    enabled: true,
    category: "industrial",
  },
  {
    id: "skill-2",
    name: "trend-report",
    description: "Generate trend reports",
    tier: "core-industrial" as const,
    enabled: true,
    category: "industrial",
  },
  {
    id: "skill-3",
    name: "data-analysis",
    description: "General data analysis",
    tier: "foundation" as const,
    enabled: true,
    category: "general",
  },
];

vi.mock("@/core/skills/hooks", () => ({
  useSkills: vi.fn(() => ({
    skills: mockSkills,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

vi.mock("@/core/skills/admin-api", () => ({
  updateSkillTier: vi.fn(() => Promise.resolve({ success: true, message: "OK" })),
  batchUpdateSkillTier: vi.fn(() =>
    Promise.resolve({ success: true, updated: 2, message: "OK" }),
  ),
}));

vi.mock("@/components/ui/table", () => ({
  Table: ({ children }: { children: React.ReactNode }) =>
    React.createElement("table", null, children),
  TableBody: ({ children }: { children: React.ReactNode }) =>
    React.createElement("tbody", null, children),
  TableCell: ({ children }: { children: React.ReactNode }) =>
    React.createElement("td", null, children),
  TableHead: ({ children }: { children: React.ReactNode }) =>
    React.createElement("th", null, children),
  TableHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement("thead", null, children),
  TableRow: ({ children }: { children: React.ReactNode }) =>
    React.createElement("tr", null, children),
}));

import AdminSkillsPage from "@/app/admin/skills/page";

describe("AdminSkillsPage", () => {
  test("renders skills table with tier column", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain("Skill Management");
    expect(html).toContain("vibration-fault-diagnosis");
    expect(html).toContain("trend-report");
    expect(html).toContain("data-analysis");
    expect(html).toContain(">Tier<");
  });

  test("displays tier badges correctly", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain("Core Industrial");
    expect(html).toContain("Foundation");
  });

  test("shows skill descriptions", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain("Vibration analysis and fault diagnosis");
    expect(html).toContain("Generate trend reports");
    expect(html).toContain("General data analysis");
  });

  test("shows enabled status", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain("Enabled");
  });

  test("shows filter dropdown", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    // Radix Select renders a combobox button; options only appear when opened
    expect(html).toContain('role="combobox"');
    expect(html).toContain("w-[180px]");
  });

  test("shows skill count summary", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain("Showing 3 of 3 skills");
  });

  test("renders table headers", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain(">Name<");
    expect(html).toContain(">Category<");
    expect(html).toContain(">Status<");
    expect(html).toContain(">Tier<");
  });

  test("renders selection checkboxes", () => {
    const html = renderToStaticMarkup(React.createElement(AdminSkillsPage));

    expect(html).toContain('aria-label="Select all"');
    expect(html).toContain('aria-label="Select vibration-fault-diagnosis"');
    expect(html).toContain('aria-label="Select trend-report"');
    expect(html).toContain('aria-label="Select data-analysis"');
  });
});
