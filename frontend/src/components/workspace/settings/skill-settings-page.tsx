"use client";

import { SparklesIcon, UploadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

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
import {
  useEnableSkill,
  useInstallSkillFile,
  useSkills,
} from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

export function SkillSettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n();
  const { skills, isLoading, error } = useSkills();
  const [filter, setFilter] = useState<string>("public");
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
        <SkillSettingsList
          skills={skills}
          filter={filter}
          onFilterChange={setFilter}
          onClose={onClose}
        />
      )}
    </SettingsSection>
  );
}

function SkillSettingsList({
  skills,
  filter,
  onFilterChange,
  onClose,
}: {
  skills: Skill[];
  filter: string;
  onFilterChange: (filter: string) => void;
  onClose?: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { mutate: enableSkill } = useEnableSkill();
  const { mutateAsync: installSkillFile, isPending: isInstalling } =
    useInstallSkillFile();
  const canInstall =
    isAdmin && env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && !isInstalling;
  const filteredSkills = useMemo(
    () => skills.filter((skill) => skill.category === filter),
    [skills, filter],
  );
  const handleCreateSkill = () => {
    onClose?.();
    router.push("/workspace/chats/new?mode=skill");
  };
  const handleInstallSkill = () => {
    fileInputRef.current?.click();
  };
  const handleSkillFileChange = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) {
      return;
    }
    try {
      const result = await installSkillFile(file);
      toast.success(t.settings.skills.installSuccess(result.skill_name));
      onFilterChange("custom");
    } catch (error) {
      toast.error(
        error instanceof SkillRequestError
          ? error.message
          : t.settings.skills.installFailed,
      );
    } finally {
      input.value = "";
    }
  };
  return (
    <div className="flex w-full flex-col gap-4">
      <header className="flex justify-between">
        <div className="flex gap-2">
          <Tabs value={filter} onValueChange={onFilterChange}>
            <TabsList variant="line">
              <TabsTrigger value="public">{t.common.public}</TabsTrigger>
              <TabsTrigger value="custom">{t.common.custom}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        <div className="flex flex-col items-end gap-1">
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept=".skill"
            aria-label={t.settings.skills.installSkill}
            disabled={!canInstall}
            onChange={handleSkillFileChange}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!canInstall}
              title={
                isAdmin ? undefined : t.settings.skills.installAdminRequired
              }
              onClick={handleInstallSkill}
            >
              <UploadIcon className="size-4" />
              {isInstalling
                ? t.settings.skills.installingSkill
                : t.settings.skills.installSkill}
            </Button>
            <Button size="sm" onClick={handleCreateSkill}>
              <SparklesIcon className="size-4" />
              {t.settings.skills.createSkill}
            </Button>
          </div>
          {!isAdmin && (
            <span className="text-muted-foreground text-xs">
              {t.settings.skills.installAdminRequired}
            </span>
          )}
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
