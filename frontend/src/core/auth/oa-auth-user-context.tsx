"use client";

import { createContext, useContext } from "react";

import type { OaAuthUser } from "@/core/auth/oa-auth";

const OaAuthUserContext = createContext<OaAuthUser | null>(null);

export function OaAuthUserProvider({
  value,
  children,
}: {
  value: OaAuthUser | null;
  children: React.ReactNode;
}) {
  return (
    <OaAuthUserContext.Provider value={value}>
      {children}
    </OaAuthUserContext.Provider>
  );
}

export function useOaAuthUser(): OaAuthUser | null {
  return useContext(OaAuthUserContext);
}
