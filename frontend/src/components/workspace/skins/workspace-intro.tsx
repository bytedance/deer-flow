"use client";

import { useEffect } from "react";

import { useSkin } from "@/core/skins";
import { prefersReducedMotion } from "@/core/skins/storage";

const INTRO_MS = 520;
const REPLAY_EVENT = "deerflow:workspace-intro";

export function playWorkspaceIntro() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(REPLAY_EVENT));
}

export function WorkspaceIntro() {
  const { skin } = useSkin();

  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    let timer = 0;

    const finish = () => {
      root.classList.remove("ws-intro-opening");
      root.classList.add("ws-intro-ready");
    };

    const play = () => {
      window.clearTimeout(timer);
      root.classList.remove("ws-intro-ready");
      if (skin !== "observatory" || prefersReducedMotion()) {
        finish();
        return;
      }
      root.classList.add("ws-intro-opening");
      timer = window.setTimeout(finish, INTRO_MS);
    };

    play();
    window.addEventListener(REPLAY_EVENT, play);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(REPLAY_EVENT, play);
      root.classList.remove("ws-intro-opening", "ws-intro-ready");
    };
  }, [skin]);

  return null;
}
