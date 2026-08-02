"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, type RefObject } from "react";

import { type BentoCardProps } from "@/components/ui/magic-bento";
import {
  usePrefersReducedMotion,
  useRenderActivity,
} from "@/core/dom/render-activity";
import { cn } from "@/lib/utils";

import { Section } from "../section";

const MagicBento = dynamic(() => import("@/components/ui/magic-bento"), {
  ssr: false,
});

const COLOR = "#0a0a0a";
const features: BentoCardProps[] = [
  {
    color: COLOR,
    label: "Context Engineering",
    title: "Long/Short-term Memory",
    description: "Now the agent can better understand you",
  },
  {
    color: COLOR,
    label: "Long Task Running",
    title: "Planning and Sub-tasking",
    description:
      "Plans ahead, reasons through complexity, then executes sequentially or in parallel",
  },
  {
    color: COLOR,
    label: "Extensible",
    title: "Skills and Tools",
    description:
      "Plug, play, or even swap built-in tools. Build the agent you want.",
  },

  {
    color: COLOR,
    label: "Persistent",
    title: "Sandbox with File System",
    description: "Read, write, run — like a real computer",
  },
  {
    color: COLOR,
    label: "Flexible",
    title: "Multi-Model Support",
    description: "Doubao, DeepSeek, OpenAI, Gemini, etc.",
  },
  {
    color: COLOR,
    label: "Free",
    title: "Open Source",
    description: "MIT License, self-hosted, full control",
  },
];

export function WhatsNewSection({ className }: { className?: string }) {
  const bentoContainerRef = useRef<HTMLDivElement>(null);
  const renderBento = useRenderActivity(bentoContainerRef, false, false);
  const reducedMotion = usePrefersReducedMotion();
  useBentoSpotlight(bentoContainerRef, renderBento && !reducedMotion);

  return (
    <Section
      className={cn("", className)}
      title="Whats New in DeerFlow 2.0"
      subtitle="DeerFlow is now evolving from a Deep Research agent into a full-stack Super Agent"
    >
      <div
        ref={bentoContainerRef}
        className="flex min-h-96 w-full items-center justify-center"
      >
        {renderBento && (
          <MagicBento
            data={features}
            disableAnimations={reducedMotion}
            enableSpotlight={false}
          />
        )}
      </div>
    </Section>
  );
}

function useBentoSpotlight(
  containerRef: RefObject<HTMLDivElement | null>,
  active: boolean,
) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !active) return;

    let pendingPointerFrame: number | undefined;
    let pointer: { x: number; y: number } | undefined;

    const clearGlow = () => {
      container
        .querySelectorAll<HTMLElement>(".magic-bento-card")
        .forEach((card) => card.style.setProperty("--glow-intensity", "0"));
    };
    const renderPointer = () => {
      pendingPointerFrame = undefined;
      if (!pointer) return;
      const { x, y } = pointer;
      pointer = undefined;
      const radius = 300;
      const proximity = radius * 0.5;
      const fadeDistance = radius * 0.75;
      container
        .querySelectorAll<HTMLElement>(".magic-bento-card")
        .forEach((card) => {
          const rect = card.getBoundingClientRect();
          const centerX = rect.left + rect.width / 2;
          const centerY = rect.top + rect.height / 2;
          const distance =
            Math.hypot(x - centerX, y - centerY) -
            Math.max(rect.width, rect.height) / 2;
          const effectiveDistance = Math.max(0, distance);
          const intensity =
            effectiveDistance <= proximity
              ? 1
              : effectiveDistance <= fadeDistance
                ? (fadeDistance - effectiveDistance) /
                  (fadeDistance - proximity)
                : 0;
          card.style.setProperty(
            "--glow-x",
            `${((x - rect.left) / rect.width) * 100}%`,
          );
          card.style.setProperty(
            "--glow-y",
            `${((y - rect.top) / rect.height) * 100}%`,
          );
          card.style.setProperty("--glow-intensity", intensity.toString());
          card.style.setProperty("--glow-radius", `${radius}px`);
        });
    };
    const handlePointerMove = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY };
      if (pendingPointerFrame !== undefined) return;
      pendingPointerFrame = requestAnimationFrame(renderPointer);
    };

    container.addEventListener("pointermove", handlePointerMove, {
      passive: true,
    });
    container.addEventListener("pointerleave", clearGlow);
    return () => {
      if (pendingPointerFrame !== undefined) {
        cancelAnimationFrame(pendingPointerFrame);
      }
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerleave", clearGlow);
      clearGlow();
    };
  }, [active, containerRef]);
}
