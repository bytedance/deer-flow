import { redirect } from "next/navigation";

import { getServerSideUser } from "@/core/auth/server";

import { AgentsClientLayout } from "./agents-client-layout";

export default async function AgentsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const result = await getServerSideUser();
  if (result.tag !== "authenticated") redirect("/login");
  if (result.user.system_role === "admin") redirect("/workspace/admin");

  return <AgentsClientLayout>{children}</AgentsClientLayout>;
}
