// import { Footer } from "@/components/landing/footer";
// import { Header } from "@/components/landing/header";
// import { Hero } from "@/components/landing/hero";
// import { CaseStudySection } from "@/components/landing/sections/case-study-section";
// import { CommunitySection } from "@/components/landing/sections/community-section";
// import { SandboxSection } from "@/components/landing/sections/sandbox-section";
// import { SkillsSection } from "@/components/landing/sections/skills-section";
// import { WhatsNewSection } from "@/components/landing/sections/whats-new-section";

import { redirect } from "next/navigation";

export default function HomePage() {
  return redirect("/workspace");
}
