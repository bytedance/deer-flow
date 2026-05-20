"use client";

import {
  BrainIcon,
  ChevronDownIcon,
  HelpCircleIcon,
  MonitorSmartphoneIcon,
  MoonIcon,
  SunIcon,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useMemo, type ComponentType, type SVGProps } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { enUS, isLocale, zhCN, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const languageOptions: { value: Locale; label: string }[] = [
  { value: "en-US", label: enUS.locale.localName },
  { value: "zh-CN", label: zhCN.locale.localName },
];

export function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme, systemTheme } = useTheme();
  const [settings, setSettings] = useLocalSettings();
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
    <div className="space-y-8">
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
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.preferencesTitle}
        description={t.settings.appearance.preferencesDescription}
      >
        <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <div className="text-sm leading-none font-medium">
                {t.settings.appearance.collapsedThinkingStepTitle}
              </div>
              <HoverCard openDelay={150}>
                <HoverCardTrigger asChild>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground rounded-sm transition-colors"
                    aria-label={t.settings.appearance.collapsedThinkingStepHelp}
                  >
                    <HelpCircleIcon className="size-4" />
                  </button>
                </HoverCardTrigger>
                <HoverCardContent className="w-80">
                  <div className="space-y-3">
                    <p className="text-muted-foreground text-xs leading-relaxed">
                      {t.settings.appearance.collapsedThinkingStepHelp}
                    </p>
                    <CollapsedThinkingStepPreview />
                  </div>
                </HoverCardContent>
              </HoverCard>
            </div>
            <p className="text-muted-foreground text-sm">
              {t.settings.appearance.collapsedThinkingStepDescription}
            </p>
          </div>
          <Switch
            checked={settings.appearance.showCollapsedThinkingStep}
            onCheckedChange={(showCollapsedThinkingStep) =>
              setSettings("appearance", { showCollapsedThinkingStep })
            }
            aria-label={t.settings.appearance.collapsedThinkingStepTitle}
          />
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

function CollapsedThinkingStepPreview() {
  const { t } = useI18n();
  const preview = t.settings.appearance.collapsedThinkingStepPreview;

  return (
    <div className="space-y-2">
      <ThinkingPreviewRow label={preview.off} state={preview.offState} />
      <ThinkingPreviewRow
        label={preview.on}
        state={preview.onState}
        step={preview.sampleStep}
      />
    </div>
  );
}

function ThinkingPreviewRow({
  label,
  state,
  step,
}: {
  label: string;
  state: string;
  step?: string;
}) {
  return (
    <div className="rounded-md border p-2">
      <div className="text-muted-foreground mb-2 text-[11px] font-medium">
        {label}
      </div>
      <div className="bg-muted/40 flex items-center gap-2 rounded-md px-3 py-2 text-xs">
        <BrainIcon className="text-muted-foreground size-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <span>{state}</span>
          {step && (
            <span className="text-primary ml-2 inline-block max-w-full truncate align-bottom">
              {step}
            </span>
          )}
        </div>
        <ChevronDownIcon className="text-muted-foreground size-4 shrink-0" />
      </div>
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
