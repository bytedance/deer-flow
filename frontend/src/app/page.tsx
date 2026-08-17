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
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

// Auth/setup state must be resolved per-request, never statically cached,
// otherwise first-boot installs would always render the landing page.
export const dynamic = "force-dynamic";

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
        // Render the landing as a safe fallback when configuration is broken.
        break;
      default:
        break;
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
