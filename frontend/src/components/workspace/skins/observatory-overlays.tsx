"use client";

import { useCallback, useEffect, useState } from "react";

import {
  CornerConstellations,
  type CornerStar,
} from "@/components/workspace/skins/corner-constellations";
import { IdleMeteors } from "@/components/workspace/skins/idle-meteors";
import { PointerPlay } from "@/components/workspace/skins/pointer-play";
import { useSkin } from "@/core/skins";
import {
  subscribeObservatoryHorizon,
  type HorizonDir,
} from "@/core/skins/theme-transition";
import { cn } from "@/lib/utils";

const HORIZON_MS = 2000;

export function ObservatoryOverlays() {
  const { skin } = useSkin();
  const [horizonOn, setHorizonOn] = useState(false);
  const [horizonDir, setHorizonDir] = useState<HorizonDir>("to-night");
  const [orbitKey, setOrbitKey] = useState(0);
  const [cornerStars, setCornerStars] = useState<CornerStar[]>([]);
  const onCornerStars = useCallback((stars: CornerStar[]) => {
    setCornerStars(stars);
  }, []);

  useEffect(() => {
    if (skin !== "observatory") return;
    return subscribeObservatoryHorizon((dir) => {
      setHorizonDir(dir);
      setOrbitKey((value) => value + 1);
      setHorizonOn(true);
      window.setTimeout(() => setHorizonOn(false), HORIZON_MS);
    });
  }, [skin]);

  if (skin !== "observatory") return null;

  return (
    <>
      <PointerPlay extraStars={cornerStars} />
      <CornerConstellations onStars={onCornerStars} />
      <IdleMeteors />
      <div
        className={cn("obs-horizon", horizonOn && "is-on")}
        data-dir={horizonDir}
        aria-hidden="true"
      >
        <div className="obs-horizon-sky" />
        <div key={orbitKey} className="obs-horizon-orbit">
          <span className="obs-planet sun" />
          <span className="obs-planet moon" />
        </div>
        <div className="obs-horizon-ground" />
      </div>
    </>
  );
}
