/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IndustrialOnboardingOverlay } from "@/components/workspace/industrial-onboarding-overlay";
import { LOCAL_SETTINGS_KEY } from "@/core/settings/local";
import { updateLocalSettings } from "@/core/settings/store";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
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
            { id: "compressor-201", name: "C-201 Compressor", type: "compressor" },
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

vi.mock("@/core/industrial-skills/telemetry", () => ({
  trackOnboardingComplete: vi.fn(),
  trackOnboardingSkip: vi.fn(),
  trackOnboardingStarted: vi.fn(),
}));

vi.mock("lucide-react", () => ({
  X: () => React.createElement("span", null, "X"),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("button", props, children),
}));

function findButton(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (element) => element.textContent?.includes(text),
  );

  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button not found: ${text}`);
  }

  return button;
}

describe("IndustrialOnboardingOverlay interactions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    pushMock.mockReset();
    window.localStorage.removeItem(LOCAL_SETTINGS_KEY);
    updateLocalSettings("onboarding", {
      industrialCompleted: false,
      industrialOperations: [],
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    window.localStorage.removeItem(LOCAL_SETTINGS_KEY);
    updateLocalSettings("onboarding", {
      industrialCompleted: false,
      industrialOperations: [],
    });
  });

  it("stays visible after selecting a device and can advance to quick analysis", () => {
    React.act(() => {
      root.render(React.createElement(IndustrialOnboardingOverlay));
    });

    expect(container.textContent).toContain("Welcome to Industrial Intelligence");

    React.act(() => {
      findButton(container, "Next").click();
    });

    expect(container.textContent).toContain("Select a Device");
    expect(findButton(container, "Next").disabled).toBe(true);

    React.act(() => {
      findButton(container, "P-101A Pump").click();
    });

    expect(container.textContent).toContain("Select a Device");
    expect(findButton(container, "Next").disabled).toBe(false);

    React.act(() => {
      findButton(container, "Next").click();
    });

    expect(container.textContent).toContain("Run Analysis");
  });
});
