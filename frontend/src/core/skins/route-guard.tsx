"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { SKIN_SCOPED_PREFIXES } from "./types";

function isSkinScoped(pathname: string): boolean {
  return SKIN_SCOPED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Keeps the observatory palette off routes that never mount SkinProvider.
 * The root-layout boot script applies data-skin before hydration for FOUC
 * protection; this clears it again whenever the app navigates (client-side)
 * to a public route, where nothing else would remove the attribute.
 */
export function SkinRouteGuard() {
  const pathname = usePathname();

  useEffect(() => {
    if (isSkinScoped(pathname)) {
      return;
    }
    delete document.documentElement.dataset.skin;
  }, [pathname]);

  return null;
}
