"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  trackOnboardingComplete,
  trackOnboardingSkip,
  trackOnboardingStarted,
} from "@/core/industrial-skills/telemetry";
import { useIndustrialOnboarding } from "@/core/settings";
import { cn } from "@/lib/utils";

type OnboardingStep = 0 | 1 | 2 | 3 | 4;

export function IndustrialOnboardingOverlay() {
  const { t } = useI18n();
  const { shouldShowOnboarding, completeOnboarding, recordOperation } =
    useIndustrialOnboarding();
  const router = useRouter();
  const [isVisible, setIsVisible] = useState(shouldShowOnboarding);
  const [currentStep, setCurrentStep] = useState<OnboardingStep>(0);
  const [selectedDevice, setSelectedDevice] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisComplete, setAnalysisComplete] = useState(false);

  useEffect(() => {
    if (shouldShowOnboarding) {
      trackOnboardingStarted();
    }
  }, [shouldShowOnboarding]);

  useEffect(() => {
    if (shouldShowOnboarding) {
      setIsVisible(true);
    }
  }, [shouldShowOnboarding]);

  if (!isVisible) {
    return null;
  }

  const handleSkip = () => {
    setIsVisible(false);
    trackOnboardingSkip();
    completeOnboarding();
  };

  const handleNext = () => {
    if (currentStep < 4) {
      setCurrentStep((currentStep + 1) as OnboardingStep);
    } else {
      completeOnboarding();
    }
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep((currentStep - 1) as OnboardingStep);
    }
  };

  const handleSelectDevice = (deviceId: string) => {
    setSelectedDevice(deviceId);
    recordOperation("device_diagnosis");
  };

  const handleRunAnalysis = async () => {
    setIsAnalyzing(true);
    // Simulate analysis delay
    await new Promise((resolve) => setTimeout(resolve, 2000));
    setIsAnalyzing(false);
    setAnalysisComplete(true);
    recordOperation("monitoring_analysis");
  };

  const handleFinish = () => {
    setIsVisible(false);
    trackOnboardingComplete();
    recordOperation("trend_report");
    completeOnboarding();
    router.push("/workspace/chats/new");
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Semi-transparent backdrop - workspace visible behind */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
      />

      {/* Overlay content */}
      <div className="relative z-10 mx-4 w-full max-w-2xl rounded-lg bg-background shadow-2xl">
        {/* Close button */}
        <button
          onClick={handleSkip}
          className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Close"
        >
          <X className="size-5" />
        </button>

        {/* Step indicator */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="text-sm text-muted-foreground">
            {currentStep + 1} / 5
          </div>
          <div className="flex gap-1">
            {[0, 1, 2, 3, 4].map((step) => (
              <div
                key={step}
                className={cn(
                  "h-1 w-8 rounded-full transition-colors",
                  step === currentStep
                    ? "bg-primary"
                    : step < currentStep
                      ? "bg-primary/50"
                      : "bg-muted",
                )}
              />
            ))}
          </div>
        </div>

        {/* Step content */}
        <div className="min-h-[300px] px-6 py-8">
          {currentStep === 0 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-semibold">
                {t.onboarding.welcome.title}
              </h2>
              <p className="text-muted-foreground">
                {t.onboarding.welcome.description}
              </p>
            </div>
          )}

          {currentStep === 1 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-semibold">
                {t.onboarding.selectDevice.title}
              </h2>
              <p className="text-muted-foreground">
                {t.onboarding.selectDevice.description}
              </p>
              <div className="grid gap-3 pt-4">
                {t.onboarding.selectDevice.sampleDevices.map((device) => (
                  <button
                    key={device.id}
                    onClick={() => handleSelectDevice(device.id)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border p-4 text-left transition-all hover:bg-muted",
                      selectedDevice === device.id &&
                        "border-primary bg-primary/5",
                    )}
                  >
                    <div className="flex-1">
                      <div className="font-medium">{device.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {device.type}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {currentStep === 2 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-semibold">
                {t.onboarding.quickAnalysis.title}
              </h2>
              <p className="text-muted-foreground">
                {t.onboarding.quickAnalysis.description}
              </p>
              <div className="flex justify-center pt-8">
                <Button
                  onClick={handleRunAnalysis}
                  disabled={isAnalyzing || analysisComplete}
                  size="lg"
                >
                  {isAnalyzing
                    ? t.onboarding.quickAnalysis.analyzing
                    : analysisComplete
                      ? "✓ " + t.onboarding.viewReport.title
                      : t.onboarding.quickAnalysis.runAnalysis}
                </Button>
              </div>
            </div>
          )}

          {currentStep === 3 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-semibold">
                {t.onboarding.viewReport.title}
              </h2>
              <p className="text-muted-foreground">
                {t.onboarding.viewReport.description}
              </p>
              <div className="rounded-lg border bg-muted/50 p-6 text-center">
                <div className="space-y-2 text-sm">
                  <div className="font-medium">📊 {t.onboarding.viewReport.title}</div>
                  <div className="text-muted-foreground">
                    {selectedDevice || "Device"} - {new Date().toLocaleDateString()}
                  </div>
                  <div className="pt-4 text-xs">
                    ✓ Vibration levels normal<br />
                    ✓ Temperature within range<br />
                    ✓ No anomalies detected
                  </div>
                </div>
              </div>
            </div>
          )}

          {currentStep === 4 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-semibold">
                {t.onboarding.finish.title}
              </h2>
              <p className="text-muted-foreground">
                {t.onboarding.finish.description}
              </p>
            </div>
          )}
        </div>

        {/* Navigation buttons */}
        <div className="flex items-center justify-between border-t px-6 py-4">
          <Button variant="ghost" onClick={handleSkip}>
            {t.onboarding.skip}
          </Button>
          <div className="flex gap-2">
            {currentStep > 0 && (
              <Button variant="outline" onClick={handleBack}>
                {t.onboarding.back}
              </Button>
            )}
            {currentStep === 4 ? (
              <Button onClick={handleFinish}>
                {t.onboarding.finish.startUsing}
              </Button>
            ) : (
              <Button
                onClick={handleNext}
                disabled={currentStep === 1 && !selectedDevice}
              >
                {t.onboarding.next}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
