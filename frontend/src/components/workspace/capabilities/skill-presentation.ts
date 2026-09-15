import {
  BookOpenIcon,
  ChartNoAxesCombinedIcon,
  CodeIcon,
  FileSearchIcon,
  ImageIcon,
  MicIcon,
  PresentationIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
  type LucideIcon,
} from "lucide-react";

import type { Skill } from "@/core/skills/type";

const builtin: Record<
  string,
  { title: string; description: string; icon: LucideIcon }
> = {
  "deep-research": {
    title: "深度研究",
    description: "围绕复杂问题检索、交叉验证资料，整理成有据可查的研究报告。",
    icon: SearchIcon,
  },
  "data-analysis": {
    title: "数据分析",
    description: "分析表格与结构化数据，发现规律，并用图表清晰呈现结论。",
    icon: ChartNoAxesCombinedIcon,
  },
  "academic-paper-review": {
    title: "学术论文审阅",
    description: "梳理论文的方法、贡献与不足，生成结构化评审和改进建议。",
    icon: BookOpenIcon,
  },
  "ppt-generation": {
    title: "演示文稿",
    description: "将想法与资料组织成完整的演示文稿，让内容更清晰、更易表达。",
    icon: PresentationIcon,
  },
  "frontend-design": {
    title: "前端设计",
    description: "设计并实现网页与交互界面，兼顾视觉表达和实际使用体验。",
    icon: CodeIcon,
  },
  "image-generation": {
    title: "图像创作",
    description: "根据描述生成图片，把构思变成可直接查看和使用的视觉素材。",
    icon: ImageIcon,
  },
  "podcast-generation": {
    title: "播客制作",
    description: "将资料和主题整理成播客内容，完成从脚本到音频的创作。",
    icon: MicIcon,
  },
  "skill-creator": {
    title: "技能创建",
    description: "把你的工作方法整理成可复用技能，帮助 Agent 掌握新的任务。",
    icon: SparklesIcon,
  },
  "skill-reviewer": {
    title: "技能审阅",
    description: "检查技能包的质量与潜在问题，给出可执行的改进建议。",
    icon: ShieldCheckIcon,
  },
  "systematic-literature-review": {
    title: "系统文献综述",
    description: "系统检索和整理研究文献，梳理主题、证据与尚待解决的问题。",
    icon: FileSearchIcon,
  },
};

export function presentSkill(skill: Skill, locale: string) {
  const presentation =
    skill.category === "public" && Object.hasOwn(builtin, skill.name)
      ? builtin[skill.name]
      : undefined;
  return {
    title: locale === "zh-CN" && presentation ? presentation.title : skill.name,
    description:
      locale === "zh-CN" && presentation
        ? presentation.description
        : skill.description,
    icon: presentation?.icon,
  };
}
