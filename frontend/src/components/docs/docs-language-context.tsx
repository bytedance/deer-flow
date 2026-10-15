"use client";

import { createContext, useContext, type ReactNode } from "react";

const DocsLanguageContext = createContext<string | undefined>(undefined);

export function DocsLanguageProvider({
  lang,
  children,
}: {
  lang: string | undefined;
  children: ReactNode;
}) {
  return (
    <DocsLanguageContext.Provider value={lang}>
      {children}
    </DocsLanguageContext.Provider>
  );
}

export function useDocsLanguage() {
  return useContext(DocsLanguageContext);
}
