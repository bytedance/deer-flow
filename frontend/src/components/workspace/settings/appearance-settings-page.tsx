"use client";

import {
  Code2Icon,
  FactoryIcon,
  GaugeIcon,
  PaletteIcon,
} from "@/components/ui/icons";
import { useTheme } from "next-themes";
import { useMemo, type ComponentType, type SVGProps } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { enUS, isLocale, zhCN, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const languageOptions: { value: Locale; label: string }[] = [
  { value: "en-US", label: enUS.locale.localName },
  { value: "zh-CN", label: zhCN.locale.localName },
];

type ThemeId =
  | "industrial-light"
  | "industrial-dark"
  | "industrial-blue"
  | "minimal-modern";

export function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const currentTheme = (theme ?? "minimal-modern") as ThemeId;

  const themeOptions = useMemo(
    () => [
      {
        id: "industrial-blue" as const,
        label: "工业蓝",
        description: "蓝色底调深色工业主题，营造控制室冷光质感",
        icon: PaletteIcon,
      },
      {
        id: "industrial-dark" as const,
        label: t.settings.appearance.industrialDark,
        description: t.settings.appearance.industrialDarkDescription,
        icon: FactoryIcon,
      },
      {
        id: "industrial-light" as const,
        label: t.settings.appearance.industrialLight,
        description: t.settings.appearance.industrialLightDescription,
        icon: GaugeIcon,
      },
      {
        id: "minimal-modern" as const,
        label: t.settings.appearance.minimalModern,
        description: t.settings.appearance.minimalModernDescription,
        icon: Code2Icon,
      },
    ],
    [
      t.settings.appearance.industrialDark,
      t.settings.appearance.industrialDarkDescription,
      t.settings.appearance.industrialLight,
      t.settings.appearance.industrialLightDescription,
      t.settings.appearance.minimalModern,
      t.settings.appearance.minimalModernDescription,
    ],
  );

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {themeOptions.map((option) => (
            <ThemePreviewCard
              key={option.id}
              icon={option.icon}
              label={option.label}
              description={option.description}
              active={currentTheme === option.id}
              mode={option.id}
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.languageTitle}
        description={t.settings.appearance.languageDescription}
      >
        <Select
          value={locale}
          onValueChange={(value) => {
            if (isLocale(value)) {
              changeLocale(value);
            }
          }}
        >
          <SelectTrigger className="w-[220px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languageOptions.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsSection>
    </div>
  );
}

function ThemePreviewCard({
  icon: Icon,
  label,
  description,
  active,
  mode,
  onSelect,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  active: boolean;
  mode: ThemeId;
  onSelect: (mode: ThemeId) => void;
}) {
  const isDarkPreview = mode === "industrial-dark" || mode === "industrial-blue";
  const isBlue = mode === "industrial-blue";
  const isMinimalModern = mode === "minimal-modern";
  const previewBg = isBlue
    ? "border-blue-900/50 bg-blue-950/60 text-blue-100"
    : isDarkPreview
      ? "border-neutral-700 bg-neutral-800 text-neutral-100"
      : "border-neutral-200 bg-white text-neutral-800";
  const previewAccent = isBlue
    ? "bg-blue-500"
    : isMinimalModern
      ? "bg-[#087CFA]"
      : "bg-sky-500";
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-sm ring-2"
          : "hover:border-border hover:shadow-sm",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="bg-muted rounded-md p-2">
          <Icon className="size-4" />
        </div>
        <div className="space-y-1">
          <div className="text-sm leading-none font-semibold">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
      <div
        className={cn(
          "relative overflow-hidden rounded-md border text-xs transition-colors",
          previewBg,
        )}
      >
        <div className="border-border/50 flex items-center gap-2 border-b px-3 py-2">
          <div className={cn("h-2 w-2 rounded-full", previewAccent)} />
          <div className="h-2 w-10 rounded-full bg-current/20" />
          <div className="h-2 w-6 rounded-full bg-current/15" />
        </div>
        <div className="grid grid-cols-[1fr_240px] gap-3 px-3 py-3">
          <div className="space-y-2">
            <div className="h-3 w-3/4 rounded-full bg-current/15" />
            <div className="h-3 w-1/2 rounded-full bg-current/10" />
            <div className="h-[90px] rounded-md border border-current/10 bg-current/5" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-md bg-current/10" />
              <div className="space-y-2">
                <div className="h-2 w-14 rounded-full bg-current/15" />
                <div className="h-2 w-10 rounded-full bg-current/10" />
              </div>
            </div>
            <div className="flex flex-col gap-1 rounded-md border border-dashed border-current/15 p-2">
              <div className="h-2 w-3/5 rounded-full bg-current/15" />
              <div className="h-2 w-2/5 rounded-full bg-current/10" />
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}
