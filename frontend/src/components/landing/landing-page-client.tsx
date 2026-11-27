"use client";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { CaseStudySection } from "@/components/landing/sections/case-study-section";
import { CommunitySection } from "@/components/landing/sections/community-section";
import { SandboxSection } from "@/components/landing/sections/sandbox-section";
import { SkillsSection } from "@/components/landing/sections/skills-section";
import { WhatsNewSection } from "@/components/landing/sections/whats-new-section";
import {
  LandingLocaleProvider,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

function LandingPageContent() {
  const { locale } = useOptionalLandingLocale(DEFAULT_LOCALE);

  return (
    <div className="font-landing-sans min-h-screen w-full overflow-x-clip bg-[var(--df-bg)] text-[var(--df-ink)] antialiased">
      <Header locale={locale} showBanner />
      <main className="flex w-full flex-col">
        <Hero locale={locale} />
        <CaseStudySection locale={locale} />
        <SkillsSection locale={locale} />
        <SandboxSection locale={locale} />
        <WhatsNewSection locale={locale} />
        <CommunitySection locale={locale} />
      </main>
      <Footer locale={locale} />
    </div>
  );
}

export function LandingPageClient() {
  return (
    <LandingLocaleProvider initialLocale={DEFAULT_LOCALE}>
      <LandingPageContent />
    </LandingLocaleProvider>
  );
}
