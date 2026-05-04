import { cn } from "@/lib/utils";

/**
 * Top-level section under a settings page (e.g. "Theme", "Change password").
 * Title sits flush with the page; description gives a one-line summary;
 * children render below in a `mt-4` block.
 */
export function SettingsSection({
  className,
  title,
  description,
  children,
}: {
  className?: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  const hasHeader = Boolean(title) || Boolean(description);
  return (
    <section className={cn(className)}>
      {hasHeader && (
        <header className="mb-4 space-y-1">
          {title && (
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          )}
          {description && (
            <div className="text-muted-foreground text-sm">{description}</div>
          )}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

/**
 * Bordered container that groups related rows. Children are separated by a
 * subtle divider (`divide-y`).
 */
export function SettingsCard({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "bg-background divide-border divide-y rounded-lg border",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * Single row within a SettingsCard. Label/description on the left, control on
 * the right. Falls back to stacked layout on small screens.
 *
 * Use `size="compact"` for dense form rows (e.g. password fields) where the
 * default vertical padding feels too airy.
 */
export function SettingsRow({
  label,
  description,
  control,
  className,
  align = "center",
  size = "default",
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  control: React.ReactNode;
  className?: string;
  align?: "center" | "start";
  size?: "default" | "compact";
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:justify-between sm:gap-6",
        size === "compact" ? "px-5 py-2.5" : "px-5 py-4",
        align === "center" ? "sm:items-center" : "sm:items-start",
        className,
      )}
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="text-sm font-medium">{label}</div>
        {description && (
          <p className="text-muted-foreground text-sm">{description}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">{control}</div>
    </div>
  );
}
