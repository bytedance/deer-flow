"use client";

import { MonitorSmartphoneIcon, MoonIcon, SunIcon } from "lucide-react";
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
import { AsterismMark } from "@/components/workspace/skins/asterism-mark";
import { enUS, isLocale, zhCN, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { useSkin, type SkinId } from "@/core/skins";
import { applyObservatoryTheme } from "@/core/skins/theme-transition";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const languageOptions: { value: Locale; label: string }[] = [
  { value: "en-US", label: enUS.locale.localName },
  { value: "zh-CN", label: zhCN.locale.localName },
];

export function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme, systemTheme, resolvedTheme } = useTheme();
  const { skin, setSkin } = useSkin();
  const currentTheme = (theme ?? "system") as "system" | "light" | "dark";

  const themeOptions = useMemo(
    () => [
      {
        id: "system",
        label: t.settings.appearance.system,
        description: t.settings.appearance.systemDescription,
        icon: MonitorSmartphoneIcon,
      },
      {
        id: "light",
        label: t.settings.appearance.light,
        description: t.settings.appearance.lightDescription,
        icon: SunIcon,
      },
      {
        id: "dark",
        label: t.settings.appearance.dark,
        description: t.settings.appearance.darkDescription,
        icon: MoonIcon,
      },
    ],
    [
      t.settings.appearance.dark,
      t.settings.appearance.darkDescription,
      t.settings.appearance.light,
      t.settings.appearance.lightDescription,
      t.settings.appearance.system,
      t.settings.appearance.systemDescription,
    ],
  );

  return (
    <div className="obs-appearance space-y-8">
      <SettingsSection
        title={t.settings.appearance.skinTitle}
        description={t.settings.appearance.skinDescription}
      >
        <div className="grid gap-3 lg:grid-cols-2">
          <SkinCard
            id="classic"
            active={skin === "classic"}
            name={t.skins.classic.name}
            tagline={t.skins.classic.tagline}
            preview="classic"
            onSelect={setSkin}
          />
          <SkinCard
            id="observatory"
            active={skin === "observatory"}
            name={t.skins.observatory.name}
            tagline={t.skins.observatory.tagline}
            preview="observatory"
            onSelect={setSkin}
          />
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div className="grid gap-3 lg:grid-cols-3">
          {themeOptions.map((option) => (
            <ThemePreviewCard
              key={option.id}
              icon={option.icon}
              label={option.label}
              description={option.description}
              active={currentTheme === option.id}
              mode={option.id as "system" | "light" | "dark"}
              systemTheme={systemTheme}
              onSelect={(value) => {
                if (skin === "observatory") {
                  applyObservatoryTheme(
                    value,
                    resolvedTheme,
                    setTheme,
                    systemTheme,
                  );
                  return;
                }
                setTheme(value);
              }}
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
  systemTheme,
  onSelect,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  active: boolean;
  mode: "system" | "light" | "dark";
  systemTheme?: string;
  onSelect: (mode: "system" | "light" | "dark") => void;
}) {
  const previewMode =
    mode === "system" ? (systemTheme === "dark" ? "dark" : "light") : mode;
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      className={cn(
        "obs-theme-card group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
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
          previewMode === "dark"
            ? "border-neutral-800 bg-neutral-900 text-neutral-200"
            : "border-slate-200 bg-white text-slate-900",
        )}
      >
        <div className="border-border/50 flex items-center gap-2 border-b px-3 py-2">
          <div
            className={cn(
              "h-2 w-2 rounded-full",
              previewMode === "dark" ? "bg-emerald-400" : "bg-emerald-500",
            )}
          />
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

function SkinCard({
  id,
  active,
  name,
  tagline,
  preview,
  onSelect,
}: {
  id: SkinId;
  active: boolean;
  name: string;
  tagline: string;
  preview: "classic" | "observatory";
  onSelect: (id: SkinId) => void;
}) {
  const observatory = preview === "observatory";
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className={cn(
        "obs-skin-card relative flex h-full flex-col gap-3 overflow-hidden rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-sm ring-2"
          : "hover:border-border hover:shadow-sm",
      )}
    >
      {active && observatory ? (
        <AsterismMark className="text-primary absolute top-3 right-3 size-5" />
      ) : null}
      <div
        className={cn(
          "relative h-20 overflow-hidden rounded-md border",
          observatory ? "bg-[#0b1020]" : "bg-[#f6f1e7]",
        )}
      >
        {observatory ? (
          <div
            className="absolute inset-0 opacity-80"
            style={{
              backgroundImage:
                "radial-gradient(1.4px 1.4px at 18% 30%, rgba(231,236,246,.55) 50%, transparent 51%), radial-gradient(1px 1px at 42% 70%, rgba(126,182,255,.7) 50%, transparent 51%), radial-gradient(1.6px 1.6px at 76% 24%, rgba(231,236,246,.45) 50%, transparent 51%)",
            }}
          />
        ) : null}
        <div
          className={cn(
            "absolute top-2 bottom-2 left-2 w-10 rounded-sm",
            observatory ? "bg-[#10182c]" : "bg-[#efe6d6]",
          )}
        />
        <div
          className={cn(
            "absolute top-5 right-3 h-6 w-16 rounded-sm",
            observatory ? "bg-[#7eb6ff]" : "bg-[#3a352d]",
          )}
        />
      </div>
      <div className="space-y-1">
        <div className="text-sm font-semibold">{name}</div>
        <p className="text-muted-foreground text-xs leading-snug">{tagline}</p>
      </div>
    </button>
  );
}
