import Link from "next/link";

import { Button } from "@/components/ui/button";
import { CompassIcon } from "@/components/ui/icons";

export default function NotFound() {
  return (
    <div className="bg-background text-foreground relative flex min-h-dvh w-full flex-col items-center justify-center gap-6 text-center">
      <div className="noise-overlay" />
      <div className="text-[140px] leading-none font-bold text-primary/10 select-none">
        404
      </div>
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight">页面未找到</h1>
        <p className="text-muted-foreground text-sm max-w-sm text-balance">
          您访问的页面不存在或已被移除。请检查链接是否正确，或返回工作台。
        </p>
      </div>
      <div className="flex gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href="/">
            <CompassIcon className="size-4" />
            返回首页
          </Link>
        </Button>
        <Button size="sm" asChild>
          <Link href="/workspace">进入工作台</Link>
        </Button>
      </div>
    </div>
  );
}
