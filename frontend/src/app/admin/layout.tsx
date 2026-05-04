"use client";

import { AdminSidebar } from "@/components/admin/admin-sidebar";
import { useAdminGuard } from "@/core/admin/auth-guard";

export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { allowed } = useAdminGuard();

  if (allowed === null) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (allowed === false) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-destructive">Access denied. Admin privileges required.</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <AdminSidebar />
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}
