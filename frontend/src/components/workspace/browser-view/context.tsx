"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface BrowserViewFrame {
  screenshot: string;
  url?: string;
  title?: string;
  action?: string;
}

interface BrowserViewContextValue {
  open: boolean;
  latestFrame: BrowserViewFrame | null;
  pushFrame: (frame: BrowserViewFrame) => void;
  openPanel: () => void;
  close: () => void;
}

const BrowserViewContext = createContext<BrowserViewContextValue | null>(null);

export function BrowserViewProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [latestFrame, setLatestFrame] = useState<BrowserViewFrame | null>(null);

  const pushFrame = useCallback((frame: BrowserViewFrame) => {
    setLatestFrame((prev) => {
      const sameFrame =
        prev?.screenshot === frame.screenshot &&
        prev?.url === frame.url &&
        prev?.title === frame.title &&
        prev?.action === frame.action;
      if (sameFrame) {
        return prev;
      }
      if (prev?.screenshot !== frame.screenshot) {
        // A new browser frame arrived — surface the panel automatically.
        setOpen(true);
      }
      return frame;
    });
  }, []);

  const openPanel = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);

  const value = useMemo(
    () => ({ open, latestFrame, pushFrame, openPanel, close }),
    [open, latestFrame, pushFrame, openPanel, close],
  );

  return (
    <BrowserViewContext.Provider value={value}>
      {children}
    </BrowserViewContext.Provider>
  );
}

export function useMaybeBrowserView(): BrowserViewContextValue | null {
  return useContext(BrowserViewContext);
}

export function useBrowserView(): BrowserViewContextValue {
  const ctx = useContext(BrowserViewContext);
  if (!ctx) {
    throw new Error("useBrowserView must be used within a BrowserViewProvider");
  }
  return ctx;
}
