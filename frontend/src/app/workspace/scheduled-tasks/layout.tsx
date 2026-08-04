import { redirect } from "next/navigation";

import { getServerSideUser } from "@/core/auth/server";

export default async function ScheduledTasksLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const result = await getServerSideUser();
  if (result.tag !== "authenticated") redirect("/login");
  if (result.user.system_role === "admin") redirect("/workspace/admin");
  return children;
}
