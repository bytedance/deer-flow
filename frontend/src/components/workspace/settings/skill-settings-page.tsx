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

const SKILL_ZH: Record<string, string> = {
  "deep-research": "深度研究",
  "frontend-design": "前端设计",
  "github-deep-research": "GitHub 深度研究",
  "image-generation": "图片生成",
  "music-generation": "音乐生成",
  "podcast-generation": "播客生成",
  "ppt-generation": "PPT 生成",
  "skill-creator": "技能创建器",
  "vercel-deploy-claimable": "Vercel 部署",
  "video-generation": "视频生成",
  "web-design-guidelines": "Web 设计规范",
  "academic-paper-review": "学术论文审阅",
  bootstrap: "个性化引导",
  "chart-visualization": "图表可视化",
  "claude-to-deerflow": "Claude 迁移",
  "code-documentation": "代码文档",
  "consulting-analysis": "咨询分析",
  "data-analysis": "数据分析",
  "find-skills": "技能发现",
  "newsletter-generation": "新闻稿生成",
  "surprise-me": "小惊喜",
  "systematic-literature-review": "系统性文献综述",
};

function localizeSkill(skill: Skill, locale: string): Skill {
  if (!locale.startsWith("zh")) return skill;
  const zh = SKILL_ZH[skill.name];
  if (!zh) return skill;
  return { ...skill, displayName: zh };
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
                <div className="flex items-center gap-2">
                  {skill.displayName ?? skill.name}
                </div>
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
