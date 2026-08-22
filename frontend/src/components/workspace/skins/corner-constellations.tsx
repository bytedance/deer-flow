"use client";

import { useEffect, useRef, useState } from "react";

import { useSkin } from "@/core/skins";
import { prefersReducedMotion } from "@/core/skins/storage";

export type CornerStar = { id: string; x: number; y: number; r: number };

type Home = { id: string; x: number; y: number; r: number; rate: number };

const HOMES: Home[] = [
  { id: "c0", x: 22, y: 22, r: 1.8, rate: 1.4 },
  { id: "c1", x: 48, y: 48, r: 2.2, rate: 0.8 },
  { id: "c2", x: 86, y: 30, r: 2, rate: 1.2 },
  { id: "c3", x: 118, y: 72, r: 2.3, rate: 0.65 },
  { id: "c4", x: 142, y: 54, r: 1.7, rate: 1.05 },
];

const EDGES: Array<[string, string]> = [
  ["c0", "c1"],
  ["c1", "c2"],
  ["c2", "c3"],
  ["c3", "c4"],
];

function goalOf(star: Home, mx: number, my: number) {
  const dx = star.x - mx;
  const dy = star.y - my;
  const dist = Math.hypot(dx, dy) || 1;
  if (dist > 70) return star;
  const force = ((70 - dist) / 70) * 22 * star.rate;
  return {
    ...star,
    x: Math.min(158, Math.max(2, star.x + (dx / dist) * force)),
    y: Math.min(118, Math.max(2, star.y + (dy / dist) * force)),
  };
}

function toScreen(star: Home, box: DOMRect): CornerStar {
  return {
    id: star.id,
    r: star.r,
    x: box.left + (star.x / 160) * box.width,
    y: box.top + (star.y / 120) * box.height,
  };
}

export function CornerConstellations({
  onStars,
}: {
  onStars?: (stars: CornerStar[]) => void;
}) {
  const { skin } = useSkin();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [placed, setPlaced] = useState(HOMES);
  const placedRef = useRef(HOMES);
  const localRef = useRef({ x: -200, y: -200 });
  const armRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (skin !== "observatory") return;
    const onMove = (event: PointerEvent) => {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      localRef.current = {
        x: ((event.clientX - rect.left) / rect.width) * 160,
        y: ((event.clientY - rect.top) / rect.height) * 120,
      };
      armRef.current?.();
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [skin]);

  useEffect(() => {
    if (skin !== "observatory" || prefersReducedMotion()) {
      onStars?.([]);
      return;
    }
    let frame = 0;
    const tick = () => {
      let moved = false;
      const next = HOMES.map((home, index) => {
        const current = placedRef.current[index] ?? home;
        const goal = goalOf(home, localRef.current.x, localRef.current.y);
        const x = current.x + (goal.x - current.x) * 0.06;
        const y = current.y + (goal.y - current.y) * 0.06;
        if (Math.abs(x - current.x) > 0.05 || Math.abs(y - current.y) > 0.05) {
          moved = true;
        }
        return { ...home, x, y };
      });
      if (moved) {
        placedRef.current = next;
        setPlaced(next);
        const box = svgRef.current?.getBoundingClientRect();
        if (box) onStars?.(next.map((star) => toScreen(star, box)));
        frame = window.requestAnimationFrame(tick);
      } else {
        frame = 0;
        const box = svgRef.current?.getBoundingClientRect();
        if (box)
          onStars?.(placedRef.current.map((star) => toScreen(star, box)));
      }
    };
    const arm = () => {
      if (frame === 0) frame = window.requestAnimationFrame(tick);
    };
    armRef.current = arm;
    arm();
    const onResize = () => {
      const box = svgRef.current?.getBoundingClientRect();
      if (box) onStars?.(placedRef.current.map((star) => toScreen(star, box)));
      arm();
    };
    window.addEventListener("resize", onResize);
    return () => {
      armRef.current = null;
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, [onStars, skin]);

  const byId = Object.fromEntries(placed.map((star) => [star.id, star]));

  if (skin !== "observatory") return null;

  return (
    <div className="obs-corner-sky" aria-hidden="true">
      <svg
        ref={svgRef}
        className="obs-corner obs-corner--br"
        viewBox="0 0 160 120"
      >
        {EDGES.map(([a, b]) => {
          const from = byId[a];
          const to = byId[b];
          if (!from || !to) return null;
          return (
            <path
              key={`${a}-${b}`}
              d={`M${from.x} ${from.y} L${to.x} ${to.y}`}
            />
          );
        })}
        {placed.map((star) => (
          <circle key={star.id} cx={star.x} cy={star.y} r={star.r} />
        ))}
      </svg>
    </div>
  );
}
