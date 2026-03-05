import { ChevronRightIcon } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { WordRotate } from "@/components/ui/word-rotate";
import { useAppConfig } from "@/core/config";
import { cn } from "@/lib/utils";
export function Hero({ className }: { className?: string }) {
  const { brand } = useAppConfig();

  return (
    <div
      className={cn(
        "relative flex size-full flex-col items-center justify-center overflow-hidden",
        className,
      )}
    >
      <div className="absolute inset-0 z-0 bg-[#0a0a0a]" aria-hidden="true">
        <div
          className="absolute inset-0 bg-no-repeat opacity-[0.16]"
          style={{
            backgroundImage: `url(/images/world-map-dots.svg)`,
            backgroundSize: "105% auto",
            backgroundPosition: "50% 30%",
            filter: "grayscale(0.4) saturate(0.5) brightness(0.55)",
          }}
        />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.025)_0%,rgba(255,255,255,0)_60%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,10,10,0)_0%,rgba(10,10,10,0.7)_60%,rgba(10,10,10,1)_100%)]" />
      </div>
      <div className="container-md relative z-10 mx-auto flex h-screen flex-col items-center justify-center">
        <h1 className="flex items-center gap-2 text-4xl font-bold md:text-6xl">
          <WordRotate
            words={[
              "Deep Research",
              "Collect Data",
              "Analyze Data",
              // "Generate Webpages",
              // "Vibe Coding",
              // "Generate Slides",
              // "Generate Images",
              // "Generate Podcasts",
              // "Generate Videos",
              // "Generate Songs",
              "Organize Workflows",
              // "Do Anything",
              "Learn Anything",
            ]}
          />{" "}
          <div>with {brand.name}</div>
        </h1>
        <p
          className="mt-8 scale-105 text-center text-2xl text-shadow-sm"
          style={{ color: "rgb(184,184,192)" }}
        >
          An Intelligent SuperAgent harness that researches, analyzes, and creates insights.
          With
          <br />
          the help of sandboxes, memories, tools, skills and agent swarms, it
          handles
          <br />
          different levels of tasks that could take minutes to hours.
        </p>
        <Link to="/workspace">
          <Button className="size-lg mt-8 scale-108" size="lg">
            <span className="text-md">Get Started</span>
            <ChevronRightIcon className="size-4" />
          </Button>
        </Link>
      </div>
    </div>
  );
}
