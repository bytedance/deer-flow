// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Bike, Building, Film, Github, Ham, Home, Pizza } from "lucide-react";
import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

import { BentoCard } from "~/components/magicui/bento-grid";

import { SectionHeader } from "../components/section-header";

const caseStudyIcons = [
  { id: "eiffel-tower-vs-tallest-building", icon: Building },
  { id: "github-top-trending-repo", icon: Github },
  { id: "nanjing-traditional-dishes", icon: Ham },
  { id: "rental-apartment-decoration", icon: Home },
  { id: "review-of-the-professional", icon: Film },
  { id: "china-food-delivery", icon: Bike },
  { id: "ultra-processed-foods", icon: Pizza },
  { id: "ai-twin-insurance", icon: Bot },
];

export function CaseStudySection() {
  const t = useTranslations("landing.caseStudies");
  const cases = t.raw("cases") as Array<{ title: string; description: string }>;

  return (
    <section className="relative container hidden flex-col items-center justify-center md:flex">
      <SectionHeader
        anchor="case-studies"
        title={t("title")}
        description={t("description")}
      />
      <div className="grid w-3/4 grid-cols-1 gap-2 sm:w-full sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {cases.map((caseStudy, index) => {
          const iconData = caseStudyIcons[index];
          return (
            <div key={caseStudy.title} className="w-full p-2">
              <BentoCard
                {...{
                  Icon: iconData?.icon ?? Building,
                  name: caseStudy.title,
                  description: caseStudy.description,
                  href: `/chat?replay=${iconData?.id}`,
                  cta: t("clickToWatch"),
                  className: "w-full h-full",
                }}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}
