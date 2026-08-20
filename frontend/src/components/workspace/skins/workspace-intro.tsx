"use client";

import { useEffect } from "react";

import { useSkin } from "@/core/skins";
import { prefersReducedMotion } from "@/core/skins/storage";

import { WORKSPACE_INTRO_EVENT } from "./workspace-intro-event";

const INTRO_MS = 0;

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
    window.addEventListener(WORKSPACE_INTRO_EVENT, play);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(WORKSPACE_INTRO_EVENT, play);
      root.classList.remove("ws-intro-opening", "ws-intro-ready");
    };
  }, [skin]);

  return null;
}
