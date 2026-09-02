import { redirect } from "next/navigation";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { CaseStudySection } from "@/components/landing/sections/case-study-section";
import { CommunitySection } from "@/components/landing/sections/community-section";
import { SandboxSection } from "@/components/landing/sections/sandbox-section";
import { SkillsSection } from "@/components/landing/sections/skills-section";
import { WhatsNewSection } from "@/components/landing/sections/whats-new-section";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";
import { isStaticWebsiteOnly } from "@/core/static-mode";

// Auth/setup state must be resolved per-request, never statically cached,
// otherwise first-boot installs would always render the landing page.
// In static-website mode there is no auth check, so the landing stays a
// prerendered static page instead of per-request SSR. Next.js infers the
// rendering mode from the dynamic APIs actually used at build time:
// the full deployment calls cookies() (via getServerSideUser) and is
// rendered per-request, while the static-website build keeps the guard
// branch out (NEXT_PUBLIC_STATIC_WEBSITE_ONLY is inlined at build time)
// and is prerendered as a plain static page.

export default async function LandingPage() {
  // The marketing landing page is intended for the official static website
  // deployment (NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true). For full deployments
  // that ship with a backend, route the visitor straight into the app
  // instead of showing what looks like the official website (#3909).
  if (!isStaticWebsiteOnly()) {
    const result = await getServerSideUser();
    switch (result.tag) {
      case "authenticated":
        redirect("/workspace");
      case "needs_setup":
      case "system_setup_required":
        redirect("/setup");
      case "unauthenticated":
      case "gateway_unavailable":
        redirect("/login");
      case "config_error":
        // Configuration is broken — never fall through to the official-looking
        // marketing page in a non-static deployment. Match the app layouts:
        // surface the error so it is diagnosable instead of silently serving
        // the landing page (#3909).
        throw new Error(result.message);
      default:
        assertNever(result);
    }
  }

  return (
    <div className="min-h-screen w-full overflow-x-clip bg-[#0a0a0a]">
      <Header locale={DEFAULT_LOCALE} />
      <main className="flex w-full flex-col">
        <Hero />
        <CaseStudySection />
        <SkillsSection />
        <SandboxSection />
        <WhatsNewSection />
        <CommunitySection />
      </main>
      <Footer />
    </div>
  );
}
