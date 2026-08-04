import { redirect } from "next/navigation";

import { AdminShell } from "@/components/admin/admin-shell";
import { getServerSideUser } from "@/core/auth/server";

export default async function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSideUser();
  if (result.tag !== "authenticated") {
    redirect("/login");
  }
  if (result.user.system_role !== "admin") {
    redirect("/workspace/chats/new");
  }
  return <AdminShell>{children}</AdminShell>;
}
