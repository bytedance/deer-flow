"use client";

import { SparklesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Item,
  ItemActions,
  ItemTitle,
  ItemContent,
  ItemDescription,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { SkillRequestError } from "@/core/skills/api";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

const SKILL_ZH: Record<string, { name: string; description: string }> = {
  "deep-research": {
    name: "深度研究",
    description:
      "在任何内容生成任务（PPT、设计、文章、图片、视频、报告）之前使用此技能。提供系统化的方法论，进行多角度、全面的网络调研以收集信息。",
  },
  "frontend-design": {
    name: "前端设计",
    description:
      "创建具有高设计品质的生产级前端界面。当用户要求构建 Web 组件、页面、海报或应用时使用。生成有创意、精致的代码和 UI 设计。",
  },
  "github-deep-research": {
    name: "GitHub 深度研究",
    description:
      "对任意 GitHub 仓库进行多轮深度研究。适用于综合分析、时间线重建、竞品分析或深入调查。生成结构化 Markdown 报告，包含摘要、时间线、指标分析和图表。",
  },
  "image-generation": {
    name: "图片生成",
    description:
      "当用户请求生成、创建或想象图片（包括角色、场景、产品或任何视觉内容）时使用此技能。支持结构化提示词和参考图片引导生成。",
  },
  "music-generation": {
    name: "音乐生成",
    description:
      "当用户请求生成、创作或制作音乐或歌曲时使用此技能——背景音乐、主题曲、铃声或器乐曲目。通过 MiniMax 音乐 API 从风格/情绪提示词和可选歌词生成歌曲。",
  },
  "podcast-generation": {
    name: "播客生成",
    description:
      "当用户请求从文本内容生成、创建或制作播客时使用此技能。将书面内容转换为双主持人对话式播客音频格式，带有自然的对话风格。",
  },
  "ppt-generation": {
    name: "PPT 生成",
    description:
      "当用户请求生成、创建或制作演示文稿（PPT/PPTX）时使用此技能。通过为每张幻灯片生成图片并组合成 PowerPoint 文件，创建视觉丰富的幻灯片。",
  },
  "skill-creator": {
    name: "技能创建器",
    description:
      "创建有效技能的指南。当用户想要创建新技能（或更新现有技能）以扩展 Agent 的专业知识、工作流或工具集成能力时使用此技能。",
  },
  "vercel-deploy-claimable": {
    name: "Vercel 部署",
    description:
      "将应用和网站部署到 Vercel。当用户请求部署操作时使用，如“部署我的应用”、“部署到生产环境”、“创建预览部署”等。无需认证，返回预览 URL 和可认领的部署链接。",
  },
  "video-generation": {
    name: "视频生成",
    description:
      "当用户请求生成、创建或想象视频时使用此技能。支持结构化提示词和参考图片引导生成。",
  },
  "web-design-guidelines": {
    name: "Web 设计规范",
    description:
      "审查 UI 代码是否符合 Web 界面规范。当被要求“审查我的 UI”、“检查无障碍性”、“审计设计”、“审查用户体验”或“检查我的网站是否符合最佳实践”时使用。",
  },
  "academic-paper-review": {
    name: "学术论文审阅",
    description:
      "当用户请求审阅、分析、评论或总结学术论文、研究文章、预印本或科学出版物时使用此技能。支持全面的结构化审阅，包含方法论、贡献、局限性和改进建议。",
  },
  bootstrap: {
    name: "个性化引导",
    description:
      "通过温暖、自适应的对话式引导生成个性化的 SOUL.md，帮助 DeerFlow 了解你的偏好、工作方式和沟通习惯。",
  },
  "chart-visualization": {
    name: "图表可视化",
    description:
      "生成各种类型的图表和可视化，包括折线、柱状、饼图、散点、雷达、树状、思维导图、漏斗、热力图、箱线、小提琴、区域地图等多种图表类型。",
  },
  "claude-to-deerflow": {
    name: "Claude 迁移",
    description:
      "将 Claude 的对话历史和配置迁移到 DeerFlow，实现平台间的无缝切换。",
  },
  "code-documentation": {
    name: "代码文档",
    description:
      "为代码生成清晰、结构化的文档，包括函数说明、参数定义、示例和使用说明。",
  },
  "consulting-analysis": {
    name: "咨询分析",
    description:
      "提供专业的咨询分析能力，帮助用户梳理问题、制定策略并给出结构化的分析报告。",
  },
  "data-analysis": {
    name: "数据分析",
    description:
      "对数据进行深入分析，包括数据清洗、统计分析、趋势识别和可视化，生成洞察报告。",
  },
  "find-skills": {
    name: "技能发现",
    description:
      "搜索和发现可用的 Agent Skill，帮助用户找到适合自己需求的技能并安装。",
  },
  "newsletter-generation": {
    name: "新闻稿生成",
    description:
      "根据主题和内容生成精美的新闻稿和资讯摘要，支持自定义排版和风格。",
  },
  "surprise-me": {
    name: "小惊喜",
    description:
      "随机生成意想不到的创意内容，包括图片、文字、想法等，为用户带来灵感和乐趣。",
  },
  "systematic-literature-review": {
    name: "系统性文献综述",
    description:
      "进行系统性的文献综述，搜索和分析多个数据库中的相关文献，生成符合学术规范的综述报告。",
  },
};

function localizeSkill(skill: Skill, locale: string): Skill {
  if (!locale.startsWith("zh")) return skill;
  const zh = SKILL_ZH[skill.name];
  if (!zh) return skill;
  return { ...skill, name: zh.name, description: zh.description };
}

export function SkillSettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n();
  const { skills, isLoading, error } = useSkills();
  const adminRequired =
    error instanceof SkillRequestError && error.isAdminRequired;
  return (
    <SettingsSection
      title={t.settings.skills.title}
      description={t.settings.skills.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : adminRequired ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.skills.adminRequired}
        </div>
      ) : error ? (
        <div className="text-destructive text-sm">
          {t.settings.skills.loadError}: {error.message}
        </div>
      ) : (
        <SkillSettingsList skills={skills} onClose={onClose} />
      )}
    </SettingsSection>
  );
}

function SkillSettingsList({
  skills,
  onClose,
}: {
  skills: Skill[];
  onClose?: () => void;
}) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const [filter, setFilter] = useState<string>("public");
  const { mutate: enableSkill } = useEnableSkill();
  const filteredSkills = useMemo(
    () =>
      skills
        .filter((skill) => skill.category === filter)
        .map((skill) => localizeSkill(skill, locale)),
    [skills, filter, locale],
  );
  const handleCreateSkill = () => {
    onClose?.();
    router.push("/workspace/chats/new?mode=skill");
  };
  return (
    <div className="flex w-full flex-col gap-4">
      <header className="flex justify-between">
        <div className="flex gap-2">
          <Tabs defaultValue="public" onValueChange={setFilter}>
            <TabsList variant="line">
              <TabsTrigger value="public">{t.common.public}</TabsTrigger>
              <TabsTrigger value="custom">{t.common.custom}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        <div>
          <Button size="sm" onClick={handleCreateSkill}>
            <SparklesIcon className="size-4" />
            {t.settings.skills.createSkill}
          </Button>
        </div>
      </header>
      {filteredSkills.length === 0 && (
        <EmptySkill onCreateSkill={handleCreateSkill} />
      )}
      {filteredSkills.length > 0 &&
        filteredSkills.map((skill) => (
          <Item className="w-full" variant="outline" key={skill.name}>
            <ItemContent>
              <ItemTitle>
                <div className="flex items-center gap-2">{skill.name}</div>
              </ItemTitle>
              <ItemDescription className="line-clamp-4">
                {skill.description}
              </ItemDescription>
            </ItemContent>
            <ItemActions>
              <Switch
                checked={skill.enabled}
                disabled={
                  env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || !isAdmin
                }
                onCheckedChange={(checked) =>
                  enableSkill({ skillName: skill.name, enabled: checked })
                }
              />
            </ItemActions>
          </Item>
        ))}
    </div>
  );
}

function EmptySkill({ onCreateSkill }: { onCreateSkill: () => void }) {
  const { t } = useI18n();
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SparklesIcon />
        </EmptyMedia>
        <EmptyTitle>{t.settings.skills.emptyTitle}</EmptyTitle>
        <EmptyDescription>
          {t.settings.skills.emptyDescription}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onCreateSkill}>{t.settings.skills.emptyButton}</Button>
      </EmptyContent>
    </Empty>
  );
}
