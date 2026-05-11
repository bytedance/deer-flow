"use client";

import {
  AnimatedSpan,
  Terminal,
  TypingAnimation,
} from "@/components/ui/terminal";

import { Section } from "../section";

export function SandboxSection({ className }: { className?: string }) {
  return (
    <Section
      className={className}
      title="Agent Runtime Environment"
      subtitle={
        <p>
          We give DeerFlow a &quot;computer&quot;, which can execute commands,
          manage files, and run long tasks — all in a secure Docker-based
          sandbox
        </p>
      }
    >
      <div className="mt-8 flex w-full max-w-6xl flex-col items-center gap-12 lg:flex-row lg:gap-16">
        {/* Left: Terminal */}
        <div className="w-full flex-1">
          <Terminal className="h-[360px] w-full">
            {/* Scene 1: Build a Game */}
            <TypingAnimation>$ cat requirements.txt</TypingAnimation>
            <AnimatedSpan delay={800} className="text-zinc-400">
              pygame==2.5.0
            </AnimatedSpan>

            <TypingAnimation delay={1200}>
              $ pip install -r requirements.txt
            </TypingAnimation>
            <AnimatedSpan delay={2000} className="text-green-500">
              ✔ Installed pygame
            </AnimatedSpan>

            <TypingAnimation delay={2400}>
              $ write game.py --lines 156
            </TypingAnimation>
            <AnimatedSpan delay={3200} className="text-blue-500">
              ✔ Written 156 lines
            </AnimatedSpan>

            <TypingAnimation delay={3600}>
              $ python game.py --test
            </TypingAnimation>
            <AnimatedSpan delay={4200} className="text-green-500">
              ✔ All sprites loaded
            </AnimatedSpan>
            <AnimatedSpan delay={4500} className="text-green-500">
              ✔ Physics engine OK
            </AnimatedSpan>
            <AnimatedSpan delay={4800} className="text-green-500">
              ✔ 60 FPS stable
            </AnimatedSpan>

            {/* Scene 2: Data Analysis */}
            <TypingAnimation delay={5400}>
              $ curl -O sales-2024.csv
            </TypingAnimation>
            <AnimatedSpan delay={6200} className="text-zinc-400">
              Downloaded 12.4 MB
            </AnimatedSpan>
          </Terminal>
        </div>

        {/* Right: Description */}
        <div className="w-full flex-1 space-y-6">
          <div className="space-y-4">
            <p className="text-sm font-medium tracking-wider text-purple-400 uppercase">
              Open-source
            </p>
            <h2 className="text-4xl font-bold tracking-tight lg:text-5xl">
              <a
                href="https://github.com/agent-infra/sandbox"
                target="_blank"
                rel="noopener noreferrer"
              >
                AIO Sandbox
              </a>
            </h2>
          </div>

          <div className="space-y-4 text-lg text-zinc-400">
            <p>
              We recommend using{" "}
              <a
                href="https://github.com/agent-infra/sandbox"
                className="underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                All-in-One Sandbox
              </a>{" "}
              that combines Browser, Shell, File, MCP and VSCode Server in a
              single Docker container.
            </p>
          </div>

          {/* Feature Tags */}
          <div className="flex flex-wrap gap-3 pt-4">
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300">
              Isolated
            </span>
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300">
              Safe
            </span>
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300">
              Persistent
            </span>
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300">
              Mountable FS
            </span>
            <span className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300">
              Long-running
            </span>
          </div>
        </div>
      </div>
    </Section>
  );
}
