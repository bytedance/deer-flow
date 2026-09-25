import { redirect } from "next/navigation";

import LandingPage from "@/components/landing/landing-page";
import { getServerSideUser } from "@/core/auth/server";
import { isStaticWebsiteOnly } from "@/core/static-mode";

export const dynamic = "force-dynamic";

// Static-website deployments have no gateway session to inspect, so they
// keep the marketing landing page as the homepage. A full deployment instead
// routes `/` by auth state: first boot goes straight to admin setup, signed-in
// users to the workspace, and everyone else to login.
export default async function HomePage() {
  if (isStaticWebsiteOnly()) {
    return <LandingPage />;
  }

  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      redirect("/workspace");
    case "needs_setup":
    case "system_setup_required":
      redirect("/setup");
    default:
      redirect("/login");
  }
}
