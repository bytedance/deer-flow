import { cn } from "@/lib/utils";

export function SettingsSection({
  className,
  title,
  description,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("space-y-4", className)}>
      <header className="space-y-1">
        <div className="text-[15px] font-semibold tracking-tight">{title}</div>
        {description && (
          <div className="text-muted-foreground text-[13px] leading-relaxed">
            {description}
          </div>
        )}
      </header>
      <main>{children}</main>
    </section>
  );
}
