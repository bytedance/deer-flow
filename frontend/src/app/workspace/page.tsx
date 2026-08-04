import { redirect } from "next/navigation";

import { getWorkspaceHomePath } from "@/core/auth/role-routing";
import { getServerSideUser } from "@/core/auth/server";

export default async function WorkspacePage() {
  const result = await getServerSideUser();
  if (result.tag === "authenticated") {
    redirect(getWorkspaceHomePath(result.user.system_role));
  }
  redirect("/login");
}
