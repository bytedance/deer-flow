"use client";

import { AlertTriangleIcon, HomeIcon, RefreshCwIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { t } = useI18n();

  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="flex max-w-md flex-col items-center gap-6 text-center">
        <div className="bg-destructive/10 text-destructive rounded-full p-4">
          <AlertTriangleIcon className="size-10" />
        </div>
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold tracking-tight">
            {t.errorPage.title}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t.errorPage.description}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" onClick={reset}>
            <RefreshCwIcon className="mr-2 size-4" />
            {t.errorPage.retry}
          </Button>
          <Button asChild>
            <Link href="/">
              <HomeIcon className="mr-2 size-4" />
              {t.errorPage.goHome}
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
