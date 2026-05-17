import { useMemo } from "react";

import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
};

export function Footer({ className }: FooterProps) {
  const year = useMemo(() => new Date().getFullYear(), []);
  return (
    <footer
      className={cn(
        "container-md mx-auto mt-32 flex flex-col items-center justify-center",
        className,
      )}
    >
      <hr className="from-border/0 via-border/40 to-border/0 m-0 h-px w-full border-none bg-linear-to-r" />
      <div className="text-muted-foreground container mb-8 mt-6 flex flex-col items-center justify-center gap-1 text-xs">
        <p>&copy; {year} 沈阳因思科技有限公司</p>
        <p>
          <a
            href="mailto:support@inscphm.com"
            className="hover:text-foreground transition-colors"
          >
            support@inscphm.com
          </a>
        </p>
      </div>
    </footer>
  );
}
