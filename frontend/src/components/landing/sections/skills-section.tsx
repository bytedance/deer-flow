"use client";

import dynamic from "next/dynamic";
import { useRef } from "react";

import { useRenderActivity } from "@/core/dom/render-activity";
import { cn } from "@/lib/utils";

import { Section } from "../section";

const ProgressiveSkillsAnimation = dynamic(
  () => import("../progressive-skills-animation"),
  { ssr: false },
);

export function SkillsSection({ className }: { className?: string }) {
  const animationRef = useRef<HTMLDivElement>(null);
  const renderAnimation = useRenderActivity(animationRef, false);

  return (
    <Section
      className={cn("h-[calc(100vh-64px)] w-full bg-white/2", className)}
      title="Agent Skills"
      subtitle={
        <div>
          Agent Skills are loaded progressively — only what&apos;s needed, when
          it&apos;s needed.
          <br />
          Extend DeerFlow with your own skill files, or use our built-in
          library.
        </div>
      }
    >
      <div ref={animationRef} className="relative min-h-96 overflow-hidden">
        {renderAnimation && <ProgressiveSkillsAnimation />}
      </div>
    </Section>
  );
}
