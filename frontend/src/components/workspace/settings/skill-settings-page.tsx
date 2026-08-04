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
import { useI18n } from "@/core/i18n/hooks";
import { loadSkillDetails, SkillRequestError } from "@/core/skills/api";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import type { Skill, SkillDetails } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";
import { SkillMarketPage } from "./skill-market-page";

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
        <div>Error: {error.message}</div>
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
  const { t } = useI18n();
  const router = useRouter();
  const [filter, setFilter] = useState<string>("public");
  const { mutate: enableSkill } = useEnableSkill();
  const filteredSkills = useMemo(
    () => skills.filter((skill) => skill.category === filter),
    [skills, filter],
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
              <TabsTrigger value="market">技能市场</TabsTrigger>
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
      {filter === "market" ? (
        <SkillMarketPage />
      ) : filteredSkills.length === 0 ? (
        <EmptySkill onCreateSkill={handleCreateSkill} />
      ) : (
        filteredSkills.map((skill) => (
          <SkillSettingsItem
            key={skill.name}
            skill={skill}
            canManage={skill.editable}
            onEnabledChange={(enabled) =>
              enableSkill({ skillName: skill.name, enabled })
            }
          />
        ))
      )}
    </div>
  );
}

function SkillSettingsItem({
  skill,
  canManage,
  onEnabledChange,
}: {
  skill: Skill;
  canManage: boolean;
  onEnabledChange: (enabled: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [details, setDetails] = useState<SkillDetails | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const toggleDetails = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (details || isLoadingDetails) return;
    setIsLoadingDetails(true);
    setDetailsError(null);
    try {
      setDetails(await loadSkillDetails(skill.name));
    } catch (error) {
      setDetailsError(
        error instanceof Error ? error.message : "无法读取完整技能说明",
      );
    } finally {
      setIsLoadingDetails(false);
    }
  };
  return (
    <Item className="w-full" variant="outline">
      <ItemContent>
        <ItemTitle>
          <div className="flex items-center gap-2">{skill.name}</div>
        </ItemTitle>
        <ItemDescription className="line-clamp-4">
          {skill.description}
        </ItemDescription>
        <button
          type="button"
          className="text-primary mt-2 text-left text-xs"
          onClick={() => void toggleDetails()}
        >
          {expanded ? "收起详情" : "展开完整说明"}
        </button>
        {expanded && (
          <div className="bg-muted/40 mt-2 rounded-md p-3 text-sm">
            {isLoadingDetails ? (
              <p className="text-muted-foreground">正在加载完整说明…</p>
            ) : detailsError ? (
              <p className="text-destructive">{detailsError}</p>
            ) : details ? (
              <pre className="max-h-96 overflow-y-auto font-sans text-sm break-words whitespace-pre-wrap">
                {details.content}
              </pre>
            ) : null}
          </div>
        )}
      </ItemContent>
      <ItemActions>
        <Switch
          checked={skill.enabled}
          disabled={
            env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || !canManage
          }
          onCheckedChange={onEnabledChange}
        />
      </ItemActions>
    </Item>
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
