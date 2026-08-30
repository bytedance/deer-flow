"use client";

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  applySkinToDocument,
  readStoredSkin,
  writeStoredSkin,
} from "./storage";
import { DEFAULT_SKIN, type SkinId } from "./types";

type SkinContextValue = {
  skin: SkinId;
  setSkin: (skin: SkinId) => void;
};

const SkinContext = createContext<SkinContextValue | null>(null);

export function SkinProvider({ children }: { children: ReactNode }) {
  const [skin, setSkinState] = useState<SkinId>(DEFAULT_SKIN);

  useLayoutEffect(() => {
    const stored = readStoredSkin();
    setSkinState(stored);
    applySkinToDocument(stored);
  }, []);

  const setSkin = useCallback((next: SkinId) => {
    setSkinState(next);
    writeStoredSkin(next);
    applySkinToDocument(next);
  }, []);

  const value = useMemo(() => ({ skin, setSkin }), [skin, setSkin]);

  return <SkinContext.Provider value={value}>{children}</SkinContext.Provider>;
}

export function useSkin() {
  const ctx = useContext(SkinContext);
  if (!ctx) {
    throw new Error("useSkin must be used within SkinProvider");
  }
  return ctx;
}
