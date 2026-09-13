"use client";

import { useLayoutEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { startUserPreferences } from "./user-preferences";

export function UserPreferencesBoundary({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const owner =
    !isStaticWebsiteOnly() && user?.id !== "default" ? user?.id : undefined;
  const [activeOwner, setActiveOwner] = useState<string | undefined>();
  useLayoutEffect(() => {
    const stop = owner ? startUserPreferences(owner) : undefined;
    setActiveOwner(owner);
    return stop;
  }, [owner]);
  // Initialize the account cache before any composer consumes defaults.
  if (owner !== activeOwner) return null;
  return children;
}
