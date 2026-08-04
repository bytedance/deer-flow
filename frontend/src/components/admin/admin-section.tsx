import type { ReactNode } from "react";

export function AdminSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-6">
      <header className="border-b pb-5">
        <p className="text-muted-foreground text-sm">{description}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">{title}</h1>
      </header>
      {children}
    </section>
  );
}
