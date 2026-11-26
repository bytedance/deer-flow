import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";
import { pathOfPublicDemoThread } from "@/core/threads/static-demo";

import { Section } from "../section";

type CaseStudyItem = {
  threadId: string;
  category: string;
  title: string;
  description: string;
};

type CaseStudyCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  inspectReplay: string;
  items: CaseStudyItem[];
};

const CASE_STUDY_COPY: Record<Locale, CaseStudyCopy> = {
  "en-US": {
    eyebrow: "Case Studies",
    title: "Case Studies",
    subtitle:
      "Inspect full execution replays showing how DeerFlow plans, researches, writes code, and ships real deliverables.",
    inspectReplay: "Inspect replay",
    items: [
      {
        threadId: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
        category: "Deep Research",
        title: "Forecast 2026 Agent Trends and Opportunities",
        description:
          "Create a webpage with a Deep Research report forecasting the agent technology trends and opportunities in 2026.",
      },
      {
        threadId: "4f3e55ee-f853-43db-bfb3-7d1a411f03cb",
        category: "Multimodal",
        title: 'Generate a Video Based On the Novel "Pride and Prejudice"',
        description:
          'Search the specific scene from the novel "Pride and Prejudice", then generate a video as well as a reference image based on the scenes.',
      },
      {
        threadId: "21cfea46-34bd-4aa6-9e1f-3009452fbeb9",
        category: "Visual Story",
        title: "Doraemon Explains the MOE Architecture",
        description:
          "Generate a Doraemon comic strip explaining the MOE architecture to the teenagers who are interested in AI.",
      },
      {
        threadId: "ad76c455-5bf9-4335-8517-fc03834ab828",
        category: "Data Analysis",
        title: "An Exploratory Data Analysis of the Titanic Dataset",
        description:
          "Explore the Titanic dataset and identify the key factors that influenced survival rates with visualizations and insights.",
      },
      {
        threadId: "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98",
        category: "Video Research",
        title: "Watch Y Combinator's Video then Conduct a Deep Research",
        description:
          "Watch the given Y Combinator's YouTube video and conduct a deep research on the YC's tips for technical startup founders.",
      },
      {
        threadId: "3823e443-4e2b-4679-b496-a9506eae462b",
        category: "Podcast Digest",
        title: "Collect and Summarize Dr. Fei Fei Li's Podcasts",
        description:
          "Collect all the podcast appearances of Dr. Fei Fei Li in the last 6 months, then summarize them into a comprehensive report.",
      },
    ],
  },
  "zh-CN": {
    eyebrow: "真实回放",
    title: "实战案例",
    subtitle:
      "回放真实执行会话，观察 DeerFlow 如何规划步骤、检索资料、编写代码并交付完整成果。",
    inspectReplay: "查看回放",
    items: [
      {
        threadId: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
        category: "深度研究",
        title: "预测 2026 年 Agent 技术趋势与机会",
        description:
          "撰写一份关于 2026 年智能体技术趋势与机会的深度研究报告，并生成可交互网页。",
      },
      {
        threadId: "4f3e55ee-f853-43db-bfb3-7d1a411f03cb",
        category: "多模态创作",
        title: "基于《傲慢与偏见》原著片段生成视频",
        description:
          "检索小说《傲慢与偏见》的经典场景，并据此生成参考图与完整视频片段。",
      },
      {
        threadId: "21cfea46-34bd-4aa6-9e1f-3009452fbeb9",
        category: "视觉科普",
        title: "用哆啦A梦漫画讲解 MoE 架构",
        description:
          "面向对人工智能感兴趣的青少年，生成一组生动易懂的 MoE 架构科普漫画。",
      },
      {
        threadId: "ad76c455-5bf9-4335-8517-fc03834ab828",
        category: "数据分析",
        title: "泰坦尼克号数据集探索性分析",
        description:
          "分析泰坦尼克号数据集，通过可视化图表与统计结论揭示影响生还率的关键因素。",
      },
      {
        threadId: "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98",
        category: "视频研究",
        title: "观看 YC 视频并展开技术创业深度研究",
        description:
          "解析 Y Combinator 的 YouTube 视频内容，系统梳理面向技术创始人的创业建议。",
      },
      {
        threadId: "3823e443-4e2b-4679-b496-a9506eae462b",
        category: "播客汇总",
        title: "整理并总结李飞飞博士近半年播客访谈",
        description:
          "搜集李飞飞博士近 6 个月参与的全部播客节目，提炼核心观点并生成综合报告。",
      },
    ],
  },
};

export function CaseStudySection({
  className,
  locale = DEFAULT_LOCALE,
}: {
  className?: string;
  locale?: Locale;
}) {
  const copy = CASE_STUDY_COPY[locale] ?? CASE_STUDY_COPY["en-US"];

  return (
    <Section
      id="case-studies"
      index="01"
      variant="soft"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {copy.items.map((caseStudy, idx) => (
          <Link
            key={caseStudy.threadId}
            href={pathOfPublicDemoThread(caseStudy.threadId)}
            target="_blank"
            rel="noopener noreferrer"
            className="group focus-visible:ring-ring/50 block h-full min-w-0 rounded-xl focus-visible:ring-2 focus-visible:outline-none"
          >
            <article className="flex h-full min-w-0 flex-col overflow-hidden rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-[var(--df-accent)]/50 group-hover:shadow-[0_10px_28px_var(--df-shadow)] motion-reduce:transform-none">
              <div className="relative aspect-[16/9] w-full overflow-hidden border-b border-[var(--df-border)] bg-[var(--df-muted)]">
                <Image
                  src={`/images/${caseStudy.threadId}.jpg`}
                  alt={`${caseStudy.title} preview`}
                  width={640}
                  height={360}
                  loading="lazy"
                  decoding="async"
                  sizes="(min-width: 1024px) 380px, (min-width: 768px) 50vw, 100vw"
                  className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02] motion-reduce:transform-none"
                />
              </div>

              <div className="flex flex-1 flex-col p-5 sm:p-6">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center rounded-full bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] px-2.5 py-0.5 font-mono text-[11px] font-medium tracking-[0.08em] text-[var(--df-accent)] uppercase">
                    {caseStudy.category}
                  </span>
                  <span className="font-mono text-[11px] text-[var(--df-muted-fg)] tabular-nums">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                </div>

                <h3 className="mt-3.5 text-base leading-snug font-semibold text-[var(--df-ink)] transition-colors duration-150 group-hover:text-[var(--df-accent)] sm:text-lg">
                  {caseStudy.title}
                </h3>

                <p className="mt-2 mb-5 line-clamp-2 text-sm leading-6 text-[var(--df-muted-fg)]">
                  {caseStudy.description}
                </p>

                <div className="mt-auto flex items-center justify-between border-t border-[var(--df-border-soft)] pt-4 text-xs">
                  <span className="inline-flex items-center gap-1.5 font-mono font-medium text-[var(--df-accent)]">
                    <span>{copy.inspectReplay}</span>
                    <ArrowRight
                      className="size-3.5 transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:transform-none"
                      aria-hidden="true"
                    />
                  </span>
                </div>
              </div>
            </article>
          </Link>
        ))}
      </div>
    </Section>
  );
}
