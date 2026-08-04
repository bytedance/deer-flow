import { redirect } from "next/navigation";

import { getServerSideUser } from "@/core/auth/server";

export default async function ChatsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSideUser();
  if (result.tag === "authenticated" && result.user.system_role === "admin") {
    redirect("/workspace/admin");
  }
  return children;
}
