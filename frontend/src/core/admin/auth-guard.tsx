"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAdminStats } from "./api";

export function useAdminGuard(): { allowed: boolean | null } {
  const router = useRouter();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAdminStats()
      .then(() => {
        if (!cancelled) setAllowed(true);
      })
      .catch((err) => {
        if (!cancelled) {
          setAllowed(false);
          if ((err as Error).message.includes("401") || (err as Error).message.includes("403")) {
            router.push("/");
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return { allowed };
}
