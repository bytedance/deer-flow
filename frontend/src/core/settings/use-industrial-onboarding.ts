import { useCallback, useMemo } from "react";

import { useLocalSettings } from "./hooks";
import { getLocalSettings } from "./local";
import { updateLocalSettings } from "./store";

export type IndustrialOperationType =
  | "device_diagnosis"
  | "monitoring_analysis"
  | "trend_report";

export function useIndustrialOnboarding() {
  const [settings] = useLocalSettings();

  const isCompleted = settings.onboarding.industrialCompleted;
  const operations = settings.onboarding.industrialOperations;
  const hasIndustrialOperations = operations.length > 0;
  const shouldShowOnboarding = !isCompleted && !hasIndustrialOperations;

  const completeOnboarding = useCallback(() => {
    updateLocalSettings("onboarding", { industrialCompleted: true });
  }, []);

  const recordOperation = useCallback((operation: IndustrialOperationType) => {
    const current = getLocalSettings();
    const existing = current.onboarding.industrialOperations;
    if (!existing.includes(operation)) {
      updateLocalSettings("onboarding", {
        industrialOperations: [...existing, operation],
      });
    }
  }, []);

  const resetOnboarding = useCallback(() => {
    updateLocalSettings("onboarding", {
      industrialCompleted: false,
      industrialOperations: [],
    });
  }, []);

  return useMemo(
    () => ({
      isCompleted,
      operations,
      hasIndustrialOperations,
      shouldShowOnboarding,
      completeOnboarding,
      recordOperation,
      resetOnboarding,
    }),
    [
      isCompleted,
      operations,
      hasIndustrialOperations,
      shouldShowOnboarding,
      completeOnboarding,
      recordOperation,
      resetOnboarding,
    ],
  );
}
