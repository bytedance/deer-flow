import Link from "next/link";

import { Card } from "@/components/ui/card";
import { pathOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

import { Section } from "../section";

export function CaseStudySection({ className }: { className?: string }) {
  const caseStudies = [
    {
      threadId: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
      title: "Forecast 2026 Agent Trends and Opportunities",
      description:
        "Create a webpage with a Deep Research report forecasting the agent technology trends and opportunities in 2026.",
    },
    {
      threadId: "4f3e55ee-f853-43db-bfb3-7d1a411f03cb",
      title: 'Generate a Video Based On the Novel "Pride and Prejudice"',
      description:
        'Search the specific scene from the novel "Pride and Prejudice", then generate a video as well as a reference image based on the scenes.',
    },
    {
      threadId: "21cfea46-34bd-4aa6-9e1f-3009452fbeb9",
      title: "Doraemon Explains the MOE Architecture",
      description:
        "Generate a Doraemon comic strip explaining the MOE architecture to the teenagers who are interested in AI.",
    },
    {
      threadId: "ad76c455-5bf9-4335-8517-fc03834ab828",
      title: "An Exploratory Data Analysis of the Titanic Dataset",
      description:
        "Explore the Titanic dataset and identify the key factors that influenced survival rates with visualizations and insights.",
    },
    {
      threadId: "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98",
      title: "Watch Y Combinator's Video then Conduct a Deep Research",
      description:
        "Watch the given Y Combinator's YouTube video and conduct a deep research on the YC's tips for technical startup founders.",
    },
    {
      threadId: "3823e443-4e2b-4679-b496-a9506eae462b",
      title: "Collect and Summarize Dr. Fei Fei Li's Podcasts",
      description:
        "Collect all the podcast appearances of Dr. Fei Fei Li in the last 6 months, then summarize them into a comprehensive report.",
    },
  ];
  return (
    <Section
      className={className}
      title="Case Studies"
      subtitle="See how DeerFlow is used in the wild"
    >
      <div className="container-md mt-8 grid grid-cols-1 gap-4 px-20 md:grid-cols-2 lg:grid-cols-3">
        {caseStudies.map((caseStudy) => (
          <Link
            key={caseStudy.title}
            href={pathOfThread(caseStudy.threadId)}
            target="_blank"
          >
            <Card className="group/card relative h-64 overflow-hidden">
              <div
                className="absolute inset-0 z-0 bg-cover bg-center bg-no-repeat transition-all duration-300 group-hover/card:scale-110 group-hover/card:brightness-90"
                style={{
                  backgroundImage: `url(/images/${caseStudy.threadId}.jpg)`,
                }}
              ></div>
              <div
                className={cn(
                  "flex h-full w-full translate-y-[calc(100%-60px)] flex-col items-center",
                  "transition-all duration-300",
                  "group-hover/card:translate-y-[calc(100%-128px)]",
                )}
              >
                <div
                  className="flex w-full flex-col p-4"
                  style={{
                    background:
                      "linear-gradient(to bottom, rgba(0, 0, 0, 0) 0%, rgba(0, 0, 0, 1) 100%)",
                  }}
                >
                  <div className="flex flex-col gap-2">
                    <h3 className="flex h-14 items-center text-xl font-bold text-shadow-black">
                      {caseStudy.title}
                    </h3>
                    <p className="box-shadow-black overflow-hidden text-sm text-white/85 text-shadow-black">
                      {caseStudy.description}
                    </p>
                  </div>
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </Section>
  );
}
