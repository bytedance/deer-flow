"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion, type MotionProps } from "motion/react";

import { cn } from "@/lib/utils";
import { AuroraText } from "./aurora-text";

interface WordRotateProps {
  words: string[];
  duration?: number;
  motionProps?: MotionProps;
  className?: string;
}

export function WordRotate({
  words,
  duration = 2200,
  motionProps = {
    initial: { opacity: 0, y: -50, filter: "blur(16px)" },
    animate: { opacity: 1, y: 0, filter: "blur(0px)" },
    exit: { opacity: 0, y: 50, filter: "blur(16px)" },
    transition: { duration: 0.3, ease: "easeOut" },
  },
  className,
}: WordRotateProps) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((prevIndex) => (prevIndex + 1) % words.length);
    }, duration);

    // Clean up interval on unmount
    return () => clearInterval(interval);
  }, [words, duration]);

  return (
    <div className="overflow-hidden py-2">
      <AnimatePresence mode="popLayout">
        <motion.h1
          key={words[index]}
          className={cn(className)}
          {...motionProps}
        >
          <AuroraText speed={3} colors={["#efefbb", "#e9c665", "#e3a812"]}>
            {words[index]}
          </AuroraText>
        </motion.h1>
      </AnimatePresence>
    </div>
  );
}
