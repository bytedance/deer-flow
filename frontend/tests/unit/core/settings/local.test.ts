import { describe, it, expect } from "vitest";

import {
  type LocalSettings,
  DEFAULT_LOCAL_SETTINGS,
  mergeLocalSettings,
} from "@/core/settings/local";

describe("LocalSettings onboarding field", () => {
  it("has onboarding field in default settings", () => {
    expect(DEFAULT_LOCAL_SETTINGS.onboarding).toBeDefined();
    expect(DEFAULT_LOCAL_SETTINGS.onboarding.industrialCompleted).toBe(false);
    expect(DEFAULT_LOCAL_SETTINGS.onboarding.industrialOperations).toEqual([]);
  });

  it("preserves onboarding field when merging settings", () => {
    const partial: Partial<LocalSettings> = {
      onboarding: {
        industrialCompleted: true,
        industrialOperations: ["device_diagnosis"],
      },
    };

    const merged = mergeLocalSettings(partial);

    expect(merged.onboarding.industrialCompleted).toBe(true);
    expect(merged.onboarding.industrialOperations).toEqual(["device_diagnosis"]);
  });

  it("defaults onboarding to false and empty array when not provided", () => {
    const partial: Partial<LocalSettings> = {
      notification: { enabled: false },
    };

    const merged = mergeLocalSettings(partial);

    expect(merged.onboarding.industrialCompleted).toBe(false);
    expect(merged.onboarding.industrialOperations).toEqual([]);
  });

  it("can track multiple industrial operations", () => {
    const partial: Partial<LocalSettings> = {
      onboarding: {
        industrialCompleted: true,
        industrialOperations: [
          "device_diagnosis",
          "monitoring_analysis",
          "trend_report",
        ],
      },
    };

    const merged = mergeLocalSettings(partial);

    expect(merged.onboarding.industrialOperations).toHaveLength(3);
    expect(merged.onboarding.industrialOperations).toContain("device_diagnosis");
    expect(merged.onboarding.industrialOperations).toContain("monitoring_analysis");
    expect(merged.onboarding.industrialOperations).toContain("trend_report");
  });

  it("allows marking onboarding as completed", () => {
    const partial: Partial<LocalSettings> = {
      onboarding: {
        industrialCompleted: true,
        industrialOperations: [],
      },
    };

    const merged = mergeLocalSettings(partial);

    expect(merged.onboarding.industrialCompleted).toBe(true);
  });

  it("can reset onboarding state", () => {
    const initial: Partial<LocalSettings> = {
      onboarding: {
        industrialCompleted: true,
        industrialOperations: ["device_diagnosis"],
      },
    };

    const merged1 = mergeLocalSettings(initial);
    expect(merged1.onboarding.industrialCompleted).toBe(true);

    const reset: Partial<LocalSettings> = {
      onboarding: {
        industrialCompleted: false,
        industrialOperations: [],
      },
    };

    const merged2 = mergeLocalSettings(reset);
    expect(merged2.onboarding.industrialCompleted).toBe(false);
    expect(merged2.onboarding.industrialOperations).toEqual([]);
  });
});
