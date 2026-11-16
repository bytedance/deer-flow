"use client";

import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

interface IncognitoModeValue {
  incognito: boolean;
  setIncognito: (active: boolean) => void;
}

const IncognitoModeContext = createContext<IncognitoModeValue | null>(null);

/**
 * Publishes "an incognito chat is open" from the chat page to the workspace
 * shell, which then stops rendering the sidebar. The URL alone cannot tell:
 * an existing incognito thread is recognized from its metadata after it loads.
 */
export function IncognitoModeProvider({ children }: { children: ReactNode }) {
  const [incognito, setIncognito] = useState(false);
  const value = useMemo(() => ({ incognito, setIncognito }), [incognito]);
  return (
    <IncognitoModeContext.Provider value={value}>
      {children}
    </IncognitoModeContext.Provider>
  );
}

/** Whether the workspace is showing an incognito chat; false without a provider. */
export function useIncognitoMode() {
  return useContext(IncognitoModeContext)?.incognito ?? false;
}

/**
 * Publishes the current surface's incognito state while it renders. A layout
 * effect keeps the sidebar from painting even once before it is hidden, and
 * unmounting the chat page releases the flag for whatever renders next.
 */
export function usePublishIncognitoMode(active: boolean) {
  const setIncognito = useContext(IncognitoModeContext)?.setIncognito;
  useLayoutEffect(() => {
    if (!setIncognito) {
      return;
    }
    setIncognito(active);
    return () => setIncognito(false);
  }, [active, setIncognito]);
}
