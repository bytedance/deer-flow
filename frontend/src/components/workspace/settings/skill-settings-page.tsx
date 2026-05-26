"use client";

import { SparklesIcon, FactoryIcon, WrenchIcon } from "lucide-react";
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
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import type { Skill, SkillTier } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

const TIER_BADGE_STYLES: Record<SkillTier, string> = {
  "core-industrial":
    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  foundation:
    "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

const TIER_LABELS: Record<SkillTier, { en: string; zh: string }> = {
  "core-industrial": { en: "Industrial", zh: "工业智能" },
  foundation: { en: "Foundation", zh: "基础工具" },
};

function TierBadge({ tier, locale }: { tier: SkillTier; locale: string }) {
  const label =
    locale.startsWith("zh")
      ? TIER_LABELS[tier].zh
      : TIER_LABELS[tier].en;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${TIER_BADGE_STYLES[tier]}`}
    >
      {tier === "core-industrial" && (
        <FactoryIcon className="mr-0.5 size-2.5" />
      )}
      {tier === "foundation" && <WrenchIcon className="mr-0.5 size-2.5" />}
      {label}
    </span>
  );
}

export function SkillSettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n();
  const { skills, isLoading, error } = useSkills();
  return (
    <SettingsSection
      title={t.settings.skills.title}
      description={t.settings.skills.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
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
  const { t, locale } = useI18n();
  const router = useRouter();
  const [categoryFilter, setCategoryFilter] = useState<string>("public");
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const { mutate: enableSkill } = useEnableSkill();
  const filteredSkills = useMemo(() => {
    let result = skills.filter((skill) => skill.category === categoryFilter);
    if (tierFilter !== "all") {
      result = result.filter((skill) => skill.tier === tierFilter);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.trim().toLowerCase();
      result = skills.filter(
        (skill) =>
          skill.name.toLowerCase().includes(query) ||
          skill.description.toLowerCase().includes(query),
      );
    }
    return result;
  }, [skills, categoryFilter, tierFilter, searchQuery]);

  const handleCreateSkill = () => {
    onClose?.();
    router.push("/workspace/chats/new?mode=skill");
  };

  return (
    <div className="flex w-full flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2">
          <Tabs
            defaultValue="public"
            onValueChange={setCategoryFilter}
          >
            <TabsList variant="line">
              <TabsTrigger value="public">{t.common.public}</TabsTrigger>
              <TabsTrigger value="custom">{t.common.custom}</TabsTrigger>
            </TabsList>
          </Tabs>
          <Tabs defaultValue="all" onValueChange={setTierFilter}>
            <TabsList variant="line">
              <TabsTrigger value="all">
                {locale.startsWith("zh") ? "全部" : "All"}
              </TabsTrigger>
              <TabsTrigger value="core-industrial">
                <FactoryIcon className="mr-1 size-3" />
                {locale.startsWith("zh") ? "工业智能" : "Industrial"}
              </TabsTrigger>
              <TabsTrigger value="foundation">
                <WrenchIcon className="mr-1 size-3" />
                {locale.startsWith("zh") ? "基础工具" : "Foundation"}
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder={
              locale.startsWith("zh") ? "搜索技能..." : "Search skills..."
            }
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="border-input bg-background placeholder:text-muted-foreground focus-visible:ring-ring h-8 w-40 rounded-md border px-3 text-sm focus-visible:ring-1 focus-visible:outline-none"
          />
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
                  {skill.name}
                  <TierBadge tier={skill.tier} locale={locale} />
                </div>
              </ItemTitle>
              <ItemDescription className="line-clamp-4">
                {skill.description}
              </ItemDescription>
            </ItemContent>
            <ItemActions>
              <Switch
                checked={skill.enabled}
                disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
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
