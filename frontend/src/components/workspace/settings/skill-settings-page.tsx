"use client";

import { SparklesIcon, UploadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
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
  useInstallSkill,
  useSkills,
} from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

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
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const [filter, setFilter] = useState<string>("public");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { mutate: enableSkill } = useEnableSkill();
  const installSkill = useInstallSkill();
  const filteredSkills = useMemo(
    () => skills.filter((skill) => skill.category === filter),
    [skills, filter],
  );
  const handleCreateSkill = () => {
    onClose?.();
    router.push("/workspace/chats/new?mode=skill");
  };
  const handleInstallSkill = (file: File) => {
    if (!file.name.toLowerCase().endsWith(".skill")) {
      toast.error(t.settings.skills.invalidPackage);
      return;
    }
    installSkill.mutate(file, {
      onSuccess: (result) => {
        if (result.success) {
          setFilter("custom");
          toast.success(result.message);
        } else {
          toast.error(result.message || t.settings.skills.installFailed);
        }
      },
      onError: (installError) => {
        if (
          installError instanceof SkillRequestError &&
          installError.isAdminRequired
        ) {
          toast.error(t.settings.skills.installAdminRequired);
        } else {
          toast.error(
            installError instanceof Error
              ? installError.message
              : t.settings.skills.installFailed,
          );
        }
      },
    });
  };
  return (
    <div className="flex w-full flex-col gap-4">
      <header className="flex flex-wrap justify-between gap-2">
        <div className="flex gap-2">
          <Tabs value={filter} onValueChange={setFilter}>
            <TabsList variant="line">
              <TabsTrigger value="public">{t.common.public}</TabsTrigger>
              <TabsTrigger value="custom">{t.common.custom}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept=".skill"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleInstallSkill(file);
              event.target.value = "";
            }}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={
              installSkill.isPending ||
              env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
              !isAdmin
            }
            onClick={() => fileInputRef.current?.click()}
          >
            <UploadIcon className="size-4" />
            {installSkill.isPending
              ? t.settings.skills.installing
              : t.settings.skills.installPackage}
          </Button>
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
