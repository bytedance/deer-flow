"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useSettingsDialog } from "@/components/workspace/settings/settings-dialog-store";
import { useSkin } from "@/core/skins";
import { prefersReducedMotion } from "@/core/skins/storage";

type Seed = {
  id: number;
  corner: 0 | 1 | 2;
  ox: number;
  oy: number;
  rate: number;
};
type Star = { id: number; x: number; y: number; rate: number };

const SEEDS: Seed[] = Array.from({ length: 17 }, (_, i) => {
  const corner = (i % 3) as 0 | 1 | 2;
  const ring = 36 + Math.floor(i / 3) * 28;
  const ang = i * 1.17 + corner * 0.4;
  return {
    id: i,
    corner,
    ox: Math.cos(ang) * ring,
    oy: Math.sin(ang) * ring * 0.82,
    rate: 0.65 + (i % 5) * 0.18,
  };
});

function readContentLeft() {
  const inset = document.querySelector<HTMLElement>(
    '[data-slot="sidebar-inset"]',
  );
  if (inset) {
    const rect = inset.getBoundingClientRect();
    if (rect.left > 8) return rect.left + 18;
  }
  const sidebar =
    document.querySelector<HTMLElement>('[data-slot="sidebar-container"]') ??
    document.querySelector<HTMLElement>('[data-slot="sidebar"]');
  if (!sidebar) return 18;
  return Math.max(18, sidebar.getBoundingClientRect().right + 18);
}

function targetOf(
  star: Star,
  mouse: { x: number; y: number },
  minX: number,
  maxX: number,
  maxY: number,
) {
  const dx = star.x - mouse.x;
  const dy = star.y - mouse.y;
  const dist = Math.hypot(dx, dy) || 1;
  if (dist > 86) return { x: star.x, y: star.y };
  const force = ((86 - dist) / 86) * 26 * star.rate;
  return {
    x: Math.min(maxX, Math.max(minX, star.x + (dx / dist) * force)),
    y: Math.min(maxY, Math.max(10, star.y + (dy / dist) * force)),
  };
}

export function PointerPlay({
  extraStars = [],
}: {
  extraStars?: Array<{ id: string; x: number; y: number }>;
}) {
  const { skin } = useSkin();
  const { open: settingsOpen } = useSettingsDialog();
  const [mouse, setMouse] = useState({ x: -400, y: -400 });
  const [size, setSize] = useState({ w: 1440, h: 900 });
  const [gutter, setGutter] = useState(280);
  const [stars, setStars] = useState<Star[]>([]);
  const starsRef = useRef<Star[]>([]);
  const mouseRef = useRef(mouse);
  const homesRef = useRef<Star[]>([]);

  const homes = useMemo(() => {
    const pad = 36;
    const spots = [
      { x: gutter + 56, y: pad + 48 },
      { x: size.w - pad - 48, y: pad + 48 },
      { x: gutter + 56, y: size.h - pad - 48 },
    ];
    return SEEDS.map((seed) => {
      const home = spots[seed.corner] ?? { x: gutter + 56, y: 80 };
      return {
        id: seed.id,
        rate: seed.rate,
        x: Math.min(size.w - 14, Math.max(gutter + 12, home.x + seed.ox)),
        y: Math.min(size.h - 14, Math.max(14, home.y + seed.oy)),
      };
    });
  }, [gutter, size.h, size.w]);

  useEffect(() => {
    homesRef.current = homes;
    if (starsRef.current.length === 0) {
      starsRef.current = homes.map((star) => ({ ...star }));
      setStars(starsRef.current);
    }
  }, [homes]);

  useEffect(() => {
    mouseRef.current = mouse;
  }, [mouse]);

  useEffect(() => {
    if (skin !== "observatory" || prefersReducedMotion() || settingsOpen)
      return;
    let frame = 0;
    const tick = () => {
      frame = 0;
      let moved = false;
      const next = homesRef.current.map((home, index) => {
        const current = starsRef.current[index] ?? home;
        const goal = targetOf(
          home,
          mouseRef.current,
          gutter + 12,
          size.w - 14,
          size.h - 14,
        );
        const x = current.x + (goal.x - current.x) * 0.06;
        const y = current.y + (goal.y - current.y) * 0.06;
        if (Math.abs(x - current.x) > 0.05 || Math.abs(y - current.y) > 0.05) {
          moved = true;
        }
        return { ...home, x, y };
      });
      if (moved) {
        starsRef.current = next;
        setStars(next);
        setMouse(mouseRef.current);
        frame = window.requestAnimationFrame(tick);
      }
    };
    const arm = () => {
      if (!frame) frame = window.requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", arm, { passive: true });
    arm();
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", arm);
    };
  }, [gutter, settingsOpen, size.h, size.w, skin]);

  const visible = stars.length ? stars : homes;
  const LINK_PX = 91;
  const dustLinks = visible
    .map((star) => ({
      ...star,
      d: Math.hypot(star.x - mouse.x, star.y - mouse.y),
    }))
    .filter((star) => star.d < LINK_PX)
    .map((star) => [
      { x: star.x, y: star.y },
      { x: mouse.x, y: mouse.y },
    ]);
  const cornerLink = extraStars
    .map((star) => ({
      ...star,
      d: Math.hypot(star.x - mouse.x, star.y - mouse.y),
    }))
    .filter((star) => star.d < LINK_PX)
    .sort((a, b) => a.d - b.d)
    .slice(0, 1)
    .map((star) => [
      { x: star.x, y: star.y },
      { x: mouse.x, y: mouse.y },
    ]);
  const links = [...dustLinks, ...cornerLink];

  useEffect(() => {
    if (skin !== "observatory") return;
    const sync = () => {
      setSize({ w: window.innerWidth, h: window.innerHeight });
      setGutter(readContentLeft());
    };
    sync();
    const watched = [
      document.querySelector('[data-slot="sidebar-inset"]'),
      document.querySelector('[data-slot="sidebar-container"]'),
      document.querySelector('[data-slot="sidebar"]'),
    ].filter(Boolean) as Element[];
    const observer = new ResizeObserver(sync);
    watched.forEach((node) => observer.observe(node));
    window.addEventListener("resize", sync);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", sync);
    };
  }, [skin]);

  useEffect(() => {
    if (skin !== "observatory") return;
    const onMove = (event: PointerEvent) => {
      mouseRef.current = { x: event.clientX, y: event.clientY };
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [skin]);

  if (skin !== "observatory" || settingsOpen) return null;

  return (
    <div className="obs-pointer-layer" aria-hidden="true">
      {visible.map((star) => (
        <i
          key={star.id}
          className="obs-pointer-dust"
          style={{ left: star.x, top: star.y }}
        />
      ))}
      {links.length > 0 ? (
        <svg className="obs-pointer-link" width={size.w} height={size.h}>
          {links.map((pair, index) => {
            const from = pair[0];
            const to = pair[1];
            if (!from || !to) return null;
            return (
              <line key={index} x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
            );
          })}
        </svg>
      ) : null}
    </div>
  );
}
