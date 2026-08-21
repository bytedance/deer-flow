"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

const MARKS = [
  {
    viewBox: "0 0 72 28",
    path: "M8 20 L10 8 L26 22 L28 10 L42 8 L54 6 L66 4",
    stars: "8,20,1.8 10,8,2.1 26,22,1.7 28,10,1.6 42,8,2 54,6,1.7 66,4,1.8",
  },
  {
    viewBox: "0 0 72 36",
    path: "M12 6 L20 16 L36 18 L52 16 L60 6 M20 16 L24 30 M52 16 L48 30 M24 30 L36 18 L48 30",
    stars:
      "12,6,1.8 60,6,1.8 20,16,1.6 36,18,2.2 52,16,1.6 24,30,1.7 48,30,1.7",
  },
  {
    viewBox: "0 0 72 28",
    path: "M6 20 L20 8 L36 18 L52 6 L66 16",
    stars: "6,20,1.7 20,8,2 36,18,1.8 52,6,2.1 66,16,1.6",
  },
] as const;

export function AsterismMark({
  className,
  title,
}: {
  className?: string;
  title?: string;
}) {
  const [mark, setMark] = useState<(typeof MARKS)[number]>(() => MARKS[0]);

  useEffect(() => {
    const idx = Math.floor(Math.random() * MARKS.length);
    setMark(MARKS[idx] ?? MARKS[0]);
  }, []);
  return (
    <svg
      viewBox={mark.viewBox}
      fill="none"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      className={cn("h-8 w-20 shrink-0", className)}
    >
      {title ? <title>{title}</title> : null}
      <path
        d={mark.path}
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {mark.stars.split(" ").map((star) => {
        const [x, y, r] = star.split(",");
        return <circle key={star} cx={x} cy={y} r={r} fill="currentColor" />;
      })}
    </svg>
  );
}
