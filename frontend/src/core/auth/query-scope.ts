"use client";

import { createContext } from "react";

// undefined: public route or unknown auth; null: confirmed signed out.
export const AuthQueryScopeContext = createContext<string | null | undefined>(
  undefined,
);
