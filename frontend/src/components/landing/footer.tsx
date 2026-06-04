import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
};

export function Footer({ className }: FooterProps) {
  const year = new Date().getFullYear();
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
        <div className="flex gap-4 mt-2">
          <a
            href="/privacy"
            className="hover:text-foreground transition-colors"
          >
            隐私政策
          </a>
          <a
            href="/terms"
            className="hover:text-foreground transition-colors"
          >
            服务条款
          </a>
        </div>
        <p className="mt-2">
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
