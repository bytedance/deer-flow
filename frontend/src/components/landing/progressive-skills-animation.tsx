"use client";

import {
  Folder,
  FileText,
  Search,
  Globe,
  Check,
  Sparkles,
  Terminal,
  Play,
  Pause,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useState, useEffect, useRef } from "react";

import { Tooltip } from "@/components/workspace/tooltip";

type AnimationPhase =
  | "idle"
  | "user-input"
  | "scanning"
  | "load-skill"
  | "load-template"
  | "researching"
  | "load-frontend"
  | "building"
  | "load-deploy"
  | "deploying"
  | "done";

interface FileItem {
  name: string;
  type: "folder" | "file";
  indent: number;
  highlight?: boolean;
  active?: boolean;
  done?: boolean;
  dragging?: boolean;
}

const searchSteps = [
  { type: "search", text: "mRNA lipid nanoparticle delivery 2024" },
  { type: "fetch", text: "nature.com/articles/s41587-024..." },
  { type: "search", text: "LNP ionizable lipids efficiency" },
  { type: "fetch", text: "pubs.acs.org/doi/10.1021/..." },
  { type: "search", text: "targeted mRNA tissue-specific" },
];

// Animation duration configuration - adjust the duration for each step here
const ANIMATION_DELAYS = {
  "user-input": 0, // User input phase duration (milliseconds)
  scanning: 2000, // Scanning phase duration
  "load-skill": 1500, // Load skill phase duration
  "load-template": 1200, // Load template phase duration
  researching: 800, // Researching phase duration
  "load-frontend": 800, // Load frontend phase duration
  building: 1200, // Building phase duration
  "load-deploy": 2500, // Load deploy phase duration
  deploying: 1200, // Deploying phase duration
  done: 2500, // Done phase duration (final step)
} as const;

export default function ProgressiveSkillsAnimation() {
  const [phase, setPhase] = useState<AnimationPhase>("idle");
  const [searchIndex, setSearchIndex] = useState(0);
  const [buildIndex, setBuildIndex] = useState(0);
  const [, setChatMessages] = useState<React.ReactNode[]>([]);
  const [, setShowWorkspace] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasPlayed, setHasPlayed] = useState(false);
  const [hasAutoPlayed, setHasAutoPlayed] = useState(false);
  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const timeoutsRef = useRef<NodeJS.Timeout[]>([]);

  // Additional display duration after the final step (done) completes, used to show the final result
  const FINAL_DISPLAY_DURATION = 3000; // milliseconds

  // Play animation only when isPlaying is true
  useEffect(() => {
    if (!isPlaying) {
      // Clear all timeouts when paused
      timeoutsRef.current.forEach(clearTimeout);
      timeoutsRef.current = [];
      return;
    }

    const timeline = [
      { phase: "user-input" as const, delay: ANIMATION_DELAYS["user-input"] },
      { phase: "scanning" as const, delay: ANIMATION_DELAYS.scanning },
      { phase: "load-skill" as const, delay: ANIMATION_DELAYS["load-skill"] },
      {
        phase: "load-template" as const,
        delay: ANIMATION_DELAYS["load-template"],
      },
      { phase: "researching" as const, delay: ANIMATION_DELAYS.researching },
      {
        phase: "load-frontend" as const,
        delay: ANIMATION_DELAYS["load-frontend"],
      },
      { phase: "building" as const, delay: ANIMATION_DELAYS.building },
      { phase: "load-deploy" as const, delay: ANIMATION_DELAYS["load-deploy"] },
      { phase: "deploying" as const, delay: ANIMATION_DELAYS.deploying },
      { phase: "done" as const, delay: ANIMATION_DELAYS.done },
    ];

    let totalDelay = 0;
    const timeouts: NodeJS.Timeout[] = [];

    timeline.forEach(({ phase, delay }) => {
      totalDelay += delay;
      timeouts.push(setTimeout(() => setPhase(phase), totalDelay));
    });

    // Reset after animation completes
    // Total duration for the final step = ANIMATION_DELAYS["done"] + FINAL_DISPLAY_DURATION
    timeouts.push(
      setTimeout(() => {
        setPhase("idle");
        setChatMessages([]);
        setSearchIndex(0);
        setBuildIndex(0);
        setShowWorkspace(false);
        setIsPlaying(false);
      }, totalDelay + FINAL_DISPLAY_DURATION),
    );

    timeoutsRef.current = timeouts;

    return () => {
      timeouts.forEach(clearTimeout);
      timeoutsRef.current = [];
    };
  }, [isPlaying]);

  const handlePlay = () => {
    setIsPlaying(true);
    setHasPlayed(true);
    setPhase("idle");
    setChatMessages([]);
    setSearchIndex(0);
    setBuildIndex(0);
    setShowWorkspace(false);
  };

  const handleTogglePlayPause = () => {
    if (isPlaying) {
      setIsPlaying(false);
    } else {
      // If animation hasn't started or is at idle, restart from beginning
      if (phase === "idle") {
        handlePlay();
      } else {
        // Resume from current phase
        setIsPlaying(true);
      }
    }
  };

  // Auto-play when component enters viewport for the first time
  useEffect(() => {
    if (hasAutoPlayed || !containerRef.current) return;

    const containerElement = containerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasAutoPlayed && !isPlaying) {
            setHasAutoPlayed(true);
            // Small delay before auto-playing for better UX
            setTimeout(() => {
              setIsPlaying(true);
              setHasPlayed(true);
              setPhase("idle");
              setChatMessages([]);
              setSearchIndex(0);
              setBuildIndex(0);
              setShowWorkspace(false);
            }, 300);
          }
        });
      },
      {
        threshold: 0.3, // Trigger when 30% of the component is visible
        rootMargin: "0px",
      },
    );

    observer.observe(containerElement);

    return () => {
      if (containerElement) {
        observer.unobserve(containerElement);
      }
    };
  }, [hasAutoPlayed, isPlaying]);

  // Handle search animation
  useEffect(() => {
    if (phase === "researching" && searchIndex < searchSteps.length) {
      const timer = setTimeout(() => {
        setSearchIndex((i) => i + 1);
      }, 350);
      return () => clearTimeout(timer);
    }
  }, [phase, searchIndex]);

  // Handle build animation
  useEffect(() => {
    if (phase === "building" && buildIndex < 3) {
      const timer = setTimeout(() => {
        setBuildIndex((i) => i + 1);
      }, 600);
      return () => clearTimeout(timer);
    }
    if (phase === "building") {
      setShowWorkspace(true);
    }
  }, [phase, buildIndex]);

  // Auto scroll chat to bottom when messages change
  useEffect(() => {
    if (chatMessagesRef.current && phase !== "idle") {
      chatMessagesRef.current.scrollTo({
        top: chatMessagesRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [phase, searchIndex, buildIndex]);

  const getFileTree = (): FileItem[] => {
    const base: FileItem[] = [
      {
        name: "deep-search",
        type: "folder",
        indent: 0,
        highlight: phase === "scanning",
        active: ["load-skill", "load-template", "researching"].includes(phase),
        done: [
          "researching",
          "load-frontend",
          "building",
          "load-deploy",
          "deploying",
          "done",
        ].includes(phase),
      },
      {
        name: "SKILL.md",
        type: "file",
        indent: 1,
        highlight: phase === "scanning",
        dragging: phase === "load-skill",
        done: [
          "load-template",
          "researching",
          "load-frontend",
          "building",
          "load-deploy",
          "deploying",
          "done",
        ].includes(phase),
      },
      {
        name: "biotech.md",
        type: "file",
        indent: 1,
        highlight: phase === "load-template",
        dragging: phase === "load-template",
        done: [
          "researching",
          "load-frontend",
          "building",
          "load-deploy",
          "deploying",
          "done",
        ].includes(phase),
      },
      { name: "computer-science.md", type: "file", indent: 1 },
      { name: "physics.md", type: "file", indent: 1 },
      {
        name: "frontend-design",
        type: "folder",
        indent: 0,
        highlight: phase === "scanning",
        active: ["load-frontend", "building"].includes(phase),
        done: ["building", "load-deploy", "deploying", "done"].includes(phase),
      },
      {
        name: "SKILL.md",
        type: "file",
        indent: 1,
        highlight: phase === "scanning",
        dragging: phase === "load-frontend",
        done: ["building", "load-deploy", "deploying", "done"].includes(phase),
      },
      {
        name: "deploy",
        type: "folder",
        indent: 0,
        highlight: phase === "scanning",
        active: ["load-deploy", "deploying"].includes(phase),
        done: ["deploying", "done"].includes(phase),
      },
      {
        name: "SKILL.md",
        type: "file",
        indent: 1,
        highlight: phase === "scanning",
        dragging: phase === "load-deploy",
        done: ["deploying", "done"].includes(phase),
      },
      {
        name: "scripts",
        type: "folder",
        indent: 1,
        done: ["deploying", "done"].includes(phase),
      },
      {
        name: "deploy.sh",
        type: "file",
        indent: 2,
        done: ["deploying", "done"].includes(phase),
      },
    ];
    return base;
  };

  const workspaceFiles = ["index.html", "index.css", "index.js"];

  return (
    <div
      ref={containerRef}
      className="relative flex h-[calc(100vh-280px)] w-full items-center justify-center overflow-hidden p-8"
    >
      {/* Overlay and Play Button */}
      <AnimatePresence>
        {!isPlaying && !hasPlayed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 flex items-center justify-center"
          >
            <motion.button
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              onClick={handlePlay}
              className="group flex flex-col items-center gap-4 transition-transform hover:scale-105 active:scale-95"
            >
              <div className="flex h-24 w-24 items-center justify-center rounded-full bg-white/10 backdrop-blur-md transition-all group-hover:bg-white/20">
                <Play
                  size={48}
                  className="ml-1 text-white transition-transform group-hover:scale-110"
                  fill="white"
                />
              </div>
              <span className="text-lg font-medium text-white">
                Click to play
              </span>
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Left Play/Pause Button */}
      <Tooltip content="Play / Pause">
        <div className="absolute bottom-12 left-12 z-40 flex items-center gap-2">
          <motion.button
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            onClick={handleTogglePlayPause}
            className="flex h-12 w-12 items-center justify-center rounded-full bg-white/10 backdrop-blur-md transition-all hover:scale-110 hover:bg-white/20 active:scale-95"
          >
            {isPlaying ? (
              <Pause size={24} className="text-white" fill="white" />
            ) : (
              <Play size={24} className="ml-0.5 text-white" fill="white" />
            )}
          </motion.button>
          <span className="text-lg font-medium">
            Click to {isPlaying ? "pause" : "play"}
          </span>
        </div>
      </Tooltip>

      <div className="flex h-full max-h-[700px] w-full max-w-6xl gap-8">
        {/* Left: File Tree */}
        <div className="flex flex-1 flex-col">
          <motion.div
            className="mb-4 font-mono text-sm text-zinc-500"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            /mnt/skills/
          </motion.div>

          <div className="space-y-2">
            {getFileTree().map((item, index) => (
              <motion.div
                key={`${item.name}-${index}`}
                className={`flex items-center gap-3 text-lg font-medium transition-all duration-300 ${
                  item.done
                    ? "text-green-500"
                    : item.dragging
                      ? "translate-x-8 scale-105 text-blue-400"
                      : item.active
                        ? "text-white"
                        : item.highlight
                          ? "text-purple-400"
                          : "text-zinc-600"
                }`}
                style={{ paddingLeft: `${item.indent * 24}px` }}
                animate={
                  item.done
                    ? {
                        scale: 1,
                        opacity: 1,
                      }
                    : {}
                }
              >
                {item.type === "folder" ? (
                  <Folder
                    size={20}
                    className={
                      item.done
                        ? "text-green-500"
                        : item.highlight
                          ? "text-purple-400"
                          : ""
                    }
                  />
                ) : (
                  <FileText
                    size={20}
                    className={
                      item.done
                        ? "text-green-500"
                        : item.highlight
                          ? "text-purple-400"
                          : ""
                    }
                  />
                )}
                <span>{item.name}</span>
                {item.done && <Check size={16} className="text-green-500" />}
                {item.highlight && !item.done && (
                  <Sparkles size={16} className="text-purple-400" />
                )}
              </motion.div>
            ))}
          </div>
        </div>

        {/* Right: Chat Interface */}
        <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/50">
          {/* Chat Header */}
          <div className="border-b border-zinc-800 p-4">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-green-500" />
              <span className="text-sm text-zinc-400">DeerFlow Agent</span>
            </div>
          </div>

          {/* Chat Messages */}
          <div
            ref={chatMessagesRef}
            className="flex-1 space-y-4 overflow-y-auto p-6"
          >
            {/* User Message */}
            <AnimatePresence>
              {phase !== "idle" && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex justify-end"
                >
                  <div className="max-w-[90%] rounded-2xl rounded-tr-sm bg-blue-600 px-5 py-3">
                    <p className="text-base">
                      Research mRNA delivery, build a landing page, deploy to
                      Vercel
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Agent Messages */}
            <AnimatePresence>
              {phase !== "idle" && phase !== "user-input" && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="space-y-3"
                >
                  {/* Found Skills */}
                  {[
                    "scanning",
                    "load-skill",
                    "load-template",
                    "researching",
                    "load-frontend",
                    "building",
                    "load-deploy",
                    "deploying",
                    "done",
                  ].includes(phase) && (
                    <div className="text-base text-zinc-300">
                      <span className="text-purple-400">✨</span> Found 3 skills
                    </div>
                  )}

                  {/* Researching Section */}
                  {[
                    "load-skill",
                    "load-template",
                    "researching",
                    "load-frontend",
                    "building",
                    "load-deploy",
                    "deploying",
                    "done",
                  ].includes(phase) && (
                    <div className="mt-4">
                      <hr className="mb-3 border-zinc-700" />
                      <div className="mb-3 text-zinc-300">
                        🔬 Researching...
                      </div>
                      <div className="mb-3 space-y-2">
                        {/* Loading SKILL.md */}
                        {[
                          "load-skill",
                          "load-template",
                          "researching",
                          "load-frontend",
                          "building",
                          "load-deploy",
                          "deploying",
                          "done",
                        ].includes(phase) && (
                          <div className="flex items-center gap-2 pl-4 text-zinc-400">
                            <FileText size={16} />
                            <span>Loading deep-search/SKILL.md...</span>
                          </div>
                        )}
                        {/* Loading biotech.md */}
                        {[
                          "load-template",
                          "researching",
                          "load-frontend",
                          "building",
                          "load-deploy",
                          "deploying",
                          "done",
                        ].includes(phase) && (
                          <div className="flex items-center gap-2 pl-4 text-zinc-400">
                            <FileText size={16} />
                            <span>
                              Found biotech related topic, loading
                              deep-search/biotech.md...
                            </span>
                          </div>
                        )}
                      </div>
                      {/* Search steps */}
                      {phase === "researching" && (
                        <div className="max-h-[180px] space-y-2 overflow-hidden pl-4">
                          {searchSteps.slice(0, searchIndex).map((step, i) => (
                            <motion.div
                              key={i}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              className="flex items-center gap-2 text-sm text-zinc-500"
                            >
                              {step.type === "search" ? (
                                <Search size={14} className="text-blue-400" />
                              ) : (
                                <Globe size={14} className="text-green-400" />
                              )}
                              <span className="truncate">{step.text}</span>
                            </motion.div>
                          ))}
                        </div>
                      )}
                      {[
                        "load-frontend",
                        "building",
                        "load-deploy",
                        "deploying",
                        "done",
                      ].includes(phase) && (
                        <div className="max-h-[180px] space-y-2 overflow-hidden pl-4">
                          {searchSteps.map((step, i) => (
                            <motion.div
                              key={i}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              className="flex items-center gap-2 text-sm text-zinc-500"
                            >
                              {step.type === "search" ? (
                                <Search size={14} className="text-blue-400" />
                              ) : (
                                <Globe size={14} className="text-green-400" />
                              )}
                              <span className="truncate">{step.text}</span>
                            </motion.div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Building */}
                  {["building", "load-deploy", "deploying", "done"].includes(
                    phase,
                  ) && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="mt-4"
                    >
                      <hr className="mb-3 border-zinc-700" />
                      <div className="mb-3 text-zinc-300">🔨 Building...</div>
                      <div className="mb-3 flex items-center gap-2 pl-4 text-zinc-400">
                        <FileText size={16} />
                        <span>Loading frontend-design/SKILL.md...</span>
                      </div>
                      <div className="space-y-2 pl-4">
                        {workspaceFiles.slice(0, buildIndex).map((file) => (
                          <motion.div
                            key={file}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="flex items-center gap-2 text-sm text-green-500"
                          >
                            <FileText size={14} />
                            <span>Generating {file}...</span>
                            <Check size={14} />
                          </motion.div>
                        ))}
                      </div>
                    </motion.div>
                  )}

                  {/* Deploying */}
                  {["load-deploy", "deploying", "done"].includes(phase) && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="mt-4"
                    >
                      <hr className="mb-3 border-zinc-700" />
                      <div className="mb-3 text-zinc-300">🚀 Deploying...</div>
                      <div className="mb-3 space-y-2">
                        <div className="flex items-center gap-2 pl-4 text-zinc-400">
                          <FileText size={16} />
                          <span>Loading deploy/SKILL.md...</span>
                        </div>
                        {["deploying", "done"].includes(phase) && (
                          <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="flex items-center gap-2 pl-4 text-zinc-400"
                          >
                            <Terminal size={16} />
                            <span>Executing scripts/deploy.sh</span>
                          </motion.div>
                        )}
                      </div>
                      {phase === "done" && (
                        <motion.div
                          initial={{ opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          className="mt-4 rounded-xl border border-green-500/30 bg-green-500/10 p-4"
                        >
                          <div className="text-lg font-medium text-green-500">
                            ✅ Live at biotech-startup.vercel.app
                          </div>
                        </motion.div>
                      )}
                    </motion.div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Chat Input (decorative) */}
          <div className="border-t border-zinc-800 p-4">
            <div className="rounded-xl bg-zinc-800 px-4 py-3 text-sm text-zinc-500">
              Ask DeerFlow anything...
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
