import { redirect } from "next/navigation";

import { getWorkspaceHomePath } from "@/core/auth/role-routing";
import { getServerSideUser } from "@/core/auth/server";

export default async function HomePage() {
  const result = await getServerSideUser();
  if (result.tag === "authenticated") {
    redirect(getWorkspaceHomePath(result.user.system_role));
  }
  if (result.tag === "needs_setup" || result.tag === "system_setup_required") {
    redirect("/setup");
  }
  if (result.tag === "config_error") {
    throw new Error(result.message);
  }
  redirect("/login");
}
