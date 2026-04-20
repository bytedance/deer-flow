"use client";

import { SparklesIcon, TagsIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { useLocalSettings } from "@/core/settings/hooks";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import {
  getSkillRouteCategoryLabel,
  SKILL_ROUTE_CATEGORIES,
  type SkillRouteCategory,
} from "@/core/skills/routing";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

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
  const { t } = useI18n();
  const router = useRouter();
  const [filter, setFilter] = useState<string>("public");
  const [settings, setSettings] = useLocalSettings();
  const { mutate: enableSkill } = useEnableSkill();
  const filteredSkills = useMemo(
    () => skills.filter((skill) => skill.category === filter),
    [skills, filter],
  );
  const categoryBindings = settings.context.skill_category_bindings ?? {};
  const categoryLabels = useMemo(
    () =>
      ({
        programming: t.inputBox.skillCategoryProgramming,
        data_analysis: t.inputBox.skillCategoryDataAnalysis,
        ppt_generation: t.inputBox.skillCategoryPpt,
        image_generation: t.inputBox.skillCategoryImage,
      }) satisfies Record<SkillRouteCategory, string>,
    [
      t.inputBox.skillCategoryDataAnalysis,
      t.inputBox.skillCategoryImage,
      t.inputBox.skillCategoryPpt,
      t.inputBox.skillCategoryProgramming,
    ],
  );
  const handleCategoryBindingChange = (
    skillName: string,
    category: SkillRouteCategory,
    checked: boolean,
  ) => {
    const nextBindings = { ...categoryBindings };
    const current = new Set(nextBindings[category] ?? []);
    if (checked) {
      current.add(skillName);
    } else {
      current.delete(skillName);
    }
    nextBindings[category] = Array.from(current);
    const contextUpdate = {
      skill_category_bindings: nextBindings,
      ...(settings.context.skill_category === category
        ? { selected_skill_names: nextBindings[category] }
        : {}),
    };
    setSettings("context", contextUpdate);
  };
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    disabled={
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                      !skill.enabled
                    }
                    aria-label={t.settings.skills.bindCategory}
                  >
                    <TagsIcon className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuLabel className="text-muted-foreground text-xs">
                    {t.settings.skills.bindCategory}
                  </DropdownMenuLabel>
                  <DropdownMenuGroup>
                    {SKILL_ROUTE_CATEGORIES.map((category) => (
                      <DropdownMenuCheckboxItem
                        key={category}
                        checked={(categoryBindings[category] ?? []).includes(
                          skill.name,
                        )}
                        onCheckedChange={(checked) =>
                          handleCategoryBindingChange(
                            skill.name,
                            category,
                            checked,
                          )
                        }
                      >
                        {getSkillRouteCategoryLabel(category, categoryLabels)}
                      </DropdownMenuCheckboxItem>
                    ))}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
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
