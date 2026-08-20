"use client";

import { useEffect, useRef, useState } from "react";

import { useSkin } from "@/core/skins";
import { prefersReducedMotion } from "@/core/skins/storage";
import { cn } from "@/lib/utils";

const IDLE_MS = 45_000;

const FALLING = [
  { top: "4%", left: "18%", delay: "0s", duration: "9.6s", size: 3 },
  { top: "0%", left: "42%", delay: "2.4s", duration: "11s", size: 2.4 },
  { top: "8%", left: "67%", delay: "4.8s", duration: "10.2s", size: 2.8 },
  { top: "2%", left: "84%", delay: "1.2s", duration: "12.4s", size: 2.2 },
  { top: "12%", left: "31%", delay: "6.6s", duration: "10.8s", size: 2.6 },
] as const;

export function IdleMeteors() {
  const { skin } = useSkin();
  const [visible, setVisible] = useState(false);
  const idleTimer = useRef<number | null>(null);

  useEffect(() => {
    if (skin !== "observatory" || prefersReducedMotion()) {
      setVisible(false);
      return;
    }

    const clearIdle = () => {
      if (idleTimer.current != null) {
        window.clearTimeout(idleTimer.current);
        idleTimer.current = null;
      }
    };

    const armIdle = () => {
      clearIdle();
      if (document.hidden) return;
      idleTimer.current = window.setTimeout(() => {
        if (!document.hidden && !prefersReducedMotion()) {
          setVisible(true);
        }
      }, IDLE_MS);
    };

    const dismiss = () => {
      clearIdle();
      setVisible(false);
      if (!document.hidden) armIdle();
    };

    const onVisibility = () => {
      if (document.hidden) {
        clearIdle();
        setVisible(false);
        return;
      }
      armIdle();
    };

    armIdle();
    window.addEventListener("pointerdown", dismiss, { passive: true });
    window.addEventListener("pointermove", dismiss, { passive: true });
    window.addEventListener("keydown", dismiss);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearIdle();
      window.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("pointermove", dismiss);
      window.removeEventListener("keydown", dismiss);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [skin]);

  if (skin !== "observatory") return null;

  return (
    <div className={cn("obs-idle-sky", visible && "is-on")} aria-hidden="true">
      {FALLING.map((star, index) => (
        <span
          key={index}
          className="obs-idle-fall"
          style={{
            top: star.top,
            left: star.left,
            width: star.size,
            height: star.size,
            animationDelay: star.delay,
            animationDuration: star.duration,
          }}
        />
      ))}
    </div>
  );
}
