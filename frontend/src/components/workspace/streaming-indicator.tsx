import { useEffect, useState } from "react";

import {
  TurnUsageDisplay,
  type TurnUsageEstimate,
} from "@/components/workspace/messages/turn-usage-display";
import { cn } from "@/lib/utils";

const ACTION_VERBS = [
  "Ruminating",
  "Sparkling",
  "Conjuring",
  "Dreaming",
  "Noodling",
  "Percolating",
  "Blossoming",
  "Musing",
  "Imagining",
  "Crafting",
  "Weaving",
  "Brainstorming",
  "Tinkering",
  "Brewing",
  "Flourishing",
  "Doodling",
  "Wondering",
  "Concocting",
  "Simmering",
  "Daydreaming",
  "Hatching",
  "Sculpting",
  "Whirring",
  "Puzzling",
  "Illuminating",
  "Germinating",
  "Mulling",
  "Pondering",
  "Kindling",
  "Frolicking",
  "Composing",
  "Unfurling",
  "Meandering",
  "Crystallizing",
  "Distilling",
  "Forging",
  "Marinating",
  "Orchestrating",
  "Spellcasting",
  "Gallivanting",
  "Scribbling",
  "Harmonizing",
  "Unraveling",
  "Synthesizing",
  "Incubating",
  "Perusing",
  "Contemplating",
  "Effervescing",
  "Enchanting",
  "Assembling",
] as const;

export function StreamingIndicator({
  className,
  size = "normal",
  showUsage = false,
  isLoading = false,
  usageEstimate,
}: {
  className?: string;
  size?: "normal" | "sm";
  showUsage?: boolean;
  isLoading?: boolean;
  usageEstimate?: TurnUsageEstimate;
}) {
  const dotSize = size === "sm" ? "w-1.5 h-1.5 mx-0.5" : "w-2 h-2 mx-1";
  const pickRandomVerb = () =>
    ACTION_VERBS[Math.floor(Math.random() * ACTION_VERBS.length)] ??
    ACTION_VERBS[0] ??
    "Thinking";
  const pickNextVerb = (current?: (typeof ACTION_VERBS)[number]): (typeof ACTION_VERBS)[number] => {
    if (ACTION_VERBS.length <= 1) {
      return ACTION_VERBS[0] ?? "Thinking";
    }
    let next = pickRandomVerb();
    if (current && next === current) {
      const currentIndex = ACTION_VERBS.indexOf(current);
      const offset = Math.floor(Math.random() * (ACTION_VERBS.length - 1)) + 1;
      next =
        ACTION_VERBS[(currentIndex + offset) % ACTION_VERBS.length] ??
        ACTION_VERBS[0] ??
        "Thinking";
    }
    return next;
  };
  const [verb, setVerb] = useState<(typeof ACTION_VERBS)[number]>(() =>
    pickRandomVerb(),
  );

  useEffect(() => {
    if (!isLoading) return;
    const interval = setInterval(() => {
      setVerb((current) => pickNextVerb(current));
    }, 3000);
    return () => clearInterval(interval);
  }, [isLoading]);

  return (
    <div className={cn("flex flex-wrap items-center gap-3", className)}>
      <div className="flex items-center gap-2">
        <span className="text-[#f0a46b]">*</span>
        <span className="text-[#f0a46b]">{verb}</span>
        <div className="flex">
          <div
            className={cn(
              dotSize,
              "animate-bouncing rounded-full bg-[#f0a46b] opacity-100",
            )}
          />
          <div
            className={cn(
              dotSize,
              "animate-bouncing rounded-full bg-[#f0a46b] opacity-100 [animation-delay:0.2s]",
            )}
          />
          <div
            className={cn(
              dotSize,
              "animate-bouncing rounded-full bg-[#f0a46b] opacity-100 [animation-delay:0.4s]",
            )}
          />
        </div>
      </div>
      {showUsage && (
        <TurnUsageDisplay
          isLoading={isLoading}
          estimate={usageEstimate}
          variant="inline"
        />
      )}
    </div>
  );
}
