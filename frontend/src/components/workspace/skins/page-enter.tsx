"use client";

import { usePathname } from "next/navigation";
import { useLayoutEffect, useState } from "react";

import { useSkin } from "@/core/skins";

export function PageEnter({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { skin } = useSkin();
  const [on, setOn] = useState(false);

  useLayoutEffect(() => {
    if (skin !== "observatory") {
      setOn(true);
      return;
    }
    setOn(false);
    const id = window.requestAnimationFrame(() => setOn(true));
    return () => window.cancelAnimationFrame(id);
  }, [pathname, skin]);

  return (
    <div
      className={
        skin === "observatory"
          ? on
            ? "obs-page-enter is-on min-h-0 flex-1"
            : "obs-page-enter min-h-0 flex-1"
          : "min-h-0 flex-1"
      }
    >
      {children}
    </div>
  );
}
