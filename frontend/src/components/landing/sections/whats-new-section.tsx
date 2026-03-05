"use client";

import MagicBento, { type BentoCardProps } from "@/components/ui/magic-bento";
import { useAppConfig } from "@/core/config";
import { cn } from "@/lib/utils";

import { Section } from "../section";

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
    description: "OpenAI, Anthropic, Gemini, Kimi, Z.ai, etc.",
  },
  {
    color: COLOR,
    label: "Sovereign",
    title: "Secure and Private",
    description: "Securely hosted, fully private, fully controlled, fully auditable",
  },
];

export function WhatsNewSection({ className }: { className?: string }) {
  const { brand } = useAppConfig();

  return (
    <Section
      className={cn("", className)}
      title={`Whats New in ${brand.name} 2.0`}
      subtitle={`${brand.name} is now evolving from a Deep Research agent into a full-stack Super Agent`}
    >
      <div className="flex w-full items-center justify-center">
        <MagicBento data={features} />
      </div>
    </Section>
  );
}
