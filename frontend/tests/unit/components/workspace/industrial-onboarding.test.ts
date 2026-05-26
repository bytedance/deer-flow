import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mockShouldShowOnboarding = vi.fn();
const mockCompleteOnboarding = vi.fn();
const mockRecordOperation = vi.fn();

vi.mock("@/core/settings", () => ({
  useIndustrialOnboarding: () => ({
    shouldShowOnboarding: mockShouldShowOnboarding(),
    completeOnboarding: mockCompleteOnboarding,
    recordOperation: mockRecordOperation,
  }),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      onboarding: {
        welcome: {
          title: "Welcome to Industrial Intelligence",
          description: "Platform helps you monitor equipment.",
        },
        selectDevice: {
          title: "Select a Device",
          description: "Choose a sample device.",
          sampleDevices: [
            { id: "pump-101", name: "P-101A Pump", type: "pump" },
          ],
        },
        quickAnalysis: {
          title: "Run Analysis",
          description: "Analyze vibration data.",
          runAnalysis: "Start",
          analyzing: "Analyzing...",
        },
        viewReport: {
          title: "View Results",
          description: "Analysis complete.",
          viewReport: "View",
        },
        finish: {
          title: "Ready",
          description: "You're all set!",
          startUsing: "Start Using",
        },
        skip: "Skip",
        next: "Next",
        back: "Back",
      },
    },
  }),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: (string | undefined | false)[]) => args.filter(Boolean).join(" "),
}));

vi.mock("lucide-react", () => ({
  X: () => React.createElement("span", null, "X"),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("button", { onClick, ...props }, children),
}));

import { IndustrialOnboardingOverlay } from "@/components/workspace/industrial-onboarding-overlay";

describe("IndustrialOnboardingOverlay", () => {
  it("returns null when shouldShowOnboarding is false", () => {
    mockShouldShowOnboarding.mockReturnValue(false);
    const html = renderToStaticMarkup(
      React.createElement(IndustrialOnboardingOverlay),
    );
    expect(html).toBe("");
  });

  it("renders welcome step when shouldShowOnboarding is true", () => {
    mockShouldShowOnboarding.mockReturnValue(true);
    const html = renderToStaticMarkup(
      React.createElement(IndustrialOnboardingOverlay),
    );
    expect(html).toContain("Welcome to Industrial Intelligence");
    expect(html).toContain("Skip");
    expect(html).toContain("Next");
    expect(html).toContain("1 / 5");
  });

  it("shows step indicator with 5 dots", () => {
    mockShouldShowOnboarding.mockReturnValue(true);
    const html = renderToStaticMarkup(
      React.createElement(IndustrialOnboardingOverlay),
    );
    expect(html).toContain("1 / 5");
  });

  it("shows skip button on all steps", () => {
    mockShouldShowOnboarding.mockReturnValue(true);
    const html = renderToStaticMarkup(
      React.createElement(IndustrialOnboardingOverlay),
    );
    expect(html).toContain("Skip");
  });
});
