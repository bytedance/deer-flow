"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import Galaxy from "@/components/ui/galaxy";
import { WordRotate } from "@/components/ui/word-rotate";
import { cn } from "@/lib/utils";

export function Hero({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-full flex-col items-center justify-center",
        className,
      )}
    >
      <div className="absolute inset-0 z-0 bg-black/40">
        <Galaxy
          mouseRepulsion={false}
          starSpeed={0.2}
          density={0.6}
          glowIntensity={0.35}
          twinkleIntensity={0.3}
          speed={0.5}
        />
      </div>
      <FlickeringGrid
        className="absolute inset-0 z-0 translate-y-8 mask-[url(/images/deer.svg)] mask-size-[100vw] mask-center mask-no-repeat md:mask-size-[72vh]"
        squareSize={4}
        gridGap={4}
        color={"white"}
        maxOpacity={0.3}
        flickerChance={0.25}
      />
      <div className="container-md relative z-10 mx-auto flex h-screen flex-col items-center justify-center">
        <h1 className="flex items-center gap-2 text-4xl font-bold md:text-6xl">
          <WordRotate
            words={[
              "Deep Research",
              "Collect Data",
              "Analyze Data",
              "Generate Webpages",
              "Vibe Coding",
              "Generate Slides",
              "Generate Images",
              "Generate Podcasts",
              "Generate Videos",
              "Generate Songs",
              "Organize Emails",
              "Do Anything",
              "Learn Anything",
            ]}
          />{" "}
          <div>with DeerFlow</div>
        </h1>
        <p
          className="mt-8 scale-105 text-center text-2xl text-shadow-sm"
          style={{ color: "rgb(184,184,192)" }}
        >
          An open-source SuperAgent harness that researches, codes, and creates.
          With
          <br />
          the help of sandboxes, memories, tools, skills and subagents, it
          handles
          <br />
          different levels of tasks that could take minutes to hours.
        </p>
        <Link href="/workspace">
          <Button className="size-lg mt-8 scale-108" size="lg">
            <span className="text-md">Get Started with 2.0</span>
            <ChevronRightIcon className="size-4" />
          </Button>
        </Link>
      </div>
    </div>
  );
}
