"use client";

import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { startUserPreferences } from "./user-preferences";

const useClientLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

export function UserPreferencesBoundary({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const owner =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;
  // SSR and initial hydration render the same workspace with the settings
  // store's safe server snapshot. Initialize the browser cache before paint.
  const [activeOwner, setActiveOwner] = useState(owner);
  useClientLayoutEffect(() => {
    const stop = owner ? startUserPreferences(owner) : undefined;
    setActiveOwner(owner);
    return stop;
  }, [owner]);
  // Only gate a subsequent account switch, keeping the old owner's settings
  // out of the new owner's consumers until the new cache is activated.
  if (owner !== activeOwner) return null;
  return children;
}
