"use client";

import { FileQuestionIcon, HomeIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

export default function NotFound() {
  const { t } = useI18n();

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="flex max-w-md flex-col items-center gap-6 text-center">
        <div className="text-muted-foreground/50 rounded-full p-4">
          <FileQuestionIcon className="size-16" strokeWidth={1} />
        </div>
        <div className="flex flex-col gap-2">
          <h1 className="text-4xl font-bold tracking-tight">404</h1>
          <p className="text-muted-foreground text-sm">
            {t.errorPage.notFoundDescription}
          </p>
        </div>
        <Button asChild>
          <Link href="/">
            <HomeIcon className="mr-2 size-4" />
            {t.errorPage.goHome}
          </Link>
        </Button>
      </div>
    </div>
  );
}
