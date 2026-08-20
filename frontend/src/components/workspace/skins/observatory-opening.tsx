"use client";

import { useEffect, useState } from "react";

import { useSkin } from "@/core/skins";
import {
  hasPlayedObservatoryOpening,
  markObservatoryOpeningPlayed,
  prefersReducedMotion,
} from "@/core/skins/storage";
const OPENING_MS = 2800;

export function ObservatoryOpening({ active }: { active: boolean }) {
  const { skin } = useSkin();
  const [phase, setPhase] = useState<"idle" | "opening" | "ready">("idle");

  useEffect(() => {
    if (!active || skin !== "observatory") {
      setPhase("idle");
      return;
    }
    if (prefersReducedMotion() || hasPlayedObservatoryOpening()) {
      setPhase("ready");
      return;
    }
    setPhase("opening");
    const timer = window.setTimeout(() => {
      markObservatoryOpeningPlayed();
      setPhase("ready");
    }, OPENING_MS);
    return () => window.clearTimeout(timer);
  }, [active, skin]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    if (phase === "opening") {
      root.classList.add("obs-is-opening");
      root.classList.remove("obs-is-ready");
    } else if (phase === "ready") {
      root.classList.remove("obs-is-opening");
      root.classList.add("obs-is-ready");
    } else {
      root.classList.remove("obs-is-opening", "obs-is-ready");
    }
    return () => {
      root.classList.remove("obs-is-opening", "obs-is-ready");
    };
  }, [phase]);

  if (!active || skin !== "observatory" || phase === "idle") return null;

  return (
    <>
      <div className="obs-opening" aria-hidden="true">
        <span
          className="obs-opening-star"
          style={{ left: "18%", top: "22%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "32%", top: "68%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "46%", top: "30%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "58%", top: "16%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "71%", top: "54%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "84%", top: "28%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "27%", top: "44%" }}
        />
        <span
          className="obs-opening-star"
          style={{ left: "63%", top: "78%" }}
        />
        <svg viewBox="0 0 700 360" className="obs-opening-svg">
          <path className="obs-opening-line" d="M180 170 L350 70 L520 130" />
        </svg>
      </div>
    </>
  );
}
