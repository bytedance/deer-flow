import { AdminSidebar } from "@/components/admin/admin-sidebar";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { buildLoginUrl, type User } from "@/core/auth/types";
import { redirect } from "next/navigation";

export default async function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const authResult = await getServerSideUser();
  let initialUser: User | null = null;

  if (authResult.tag === "authenticated" || authResult.tag === "needs_setup") {
    initialUser = authResult.user;
  } else if (authResult.tag === "unauthenticated") {
    redirect(buildLoginUrl("/admin"));
  }

  if (initialUser?.system_role !== "admin") {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-destructive">Access denied. Admin privileges required.</p>
      </div>
    );
  }

  return (
    <AuthProvider initialUser={initialUser}>
      <div className="flex h-screen">
        <AdminSidebar />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </AuthProvider>
  );
}
