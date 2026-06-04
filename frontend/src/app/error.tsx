"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { AlertCircleIcon } from "@/components/ui/icons";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body>
        <div className="bg-background text-foreground relative flex min-h-dvh w-full flex-col items-center justify-center gap-6 text-center">
          <div className="noise-overlay" />
          <div className="text-muted-foreground mb-2">
            <AlertCircleIcon className="size-12" />
          </div>
          <div className="space-y-2">
            <h1 className="text-xl font-semibold tracking-tight">出错了</h1>
            <p className="text-muted-foreground text-sm max-w-sm text-balance">
              应用遇到了意外错误，请重试。如果问题持续，请联系技术支持。
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" size="sm" onClick={reset}>
              重试
            </Button>
            <Button
              size="sm"
              onClick={() => {
                window.location.href = "/";
              }}
            >
              返回首页
            </Button>
          </div>
        </div>
      </body>
    </html>
  );
}
