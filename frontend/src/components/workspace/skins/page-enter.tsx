"use client";

import { usePathname } from "next/navigation";
import { useLayoutEffect, useState } from "react";

import { useSkin } from "@/core/skins";

export function PageEnter({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { skin } = useSkin();
  const [on, setOn] = useState(true);

  useLayoutEffect(() => {
    if (skin !== "observatory") {
      setOn(true);
      return;
    }
    setOn(false);
    const id = window.requestAnimationFrame(() => setOn(true));
    return () => window.cancelAnimationFrame(id);
  }, [pathname, skin]);

  if (skin !== "observatory") {
    return children;
  }

  return (
    <div
      className={
        on
          ? "obs-page-enter is-on min-h-0 flex-1"
          : "obs-page-enter min-h-0 flex-1"
      }
    >
      {children}
    </div>
  );
}
