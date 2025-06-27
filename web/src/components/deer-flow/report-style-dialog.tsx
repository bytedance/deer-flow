// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useTranslations } from "next-intl";
import { useState } from "react";
import { Check, FileText, Newspaper, Users, GraduationCap } from "lucide-react";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { setReportStyle, useSettingsStore } from "~/core/store";
import { cn } from "~/lib/utils";

import { Tooltip } from "./tooltip";

const REPORT_STYLES = [
  {
    value: "academic" as const,
    labelKey: "academic",
    descriptionKey: "academicDesc",
    icon: GraduationCap,
  },
  {
    value: "popular_science" as const,
    labelKey: "popularScience",
    descriptionKey: "popularScienceDesc",
    icon: FileText,
  },
  {
    value: "news" as const,
    labelKey: "news",
    descriptionKey: "newsDesc",
    icon: Newspaper,
  },
  {
    value: "social_media" as const,
    labelKey: "socialMedia",
    descriptionKey: "socialMediaDesc",
    icon: Users,
  },
];

export function ReportStyleDialog() {
  const t = useTranslations("settings.reportStyle");
  const [open, setOpen] = useState(false);
  const currentStyle = useSettingsStore((state) => state.general.reportStyle);

  const handleStyleChange = (
    style: "academic" | "popular_science" | "news" | "social_media",
  ) => {
    setReportStyle(style);
    setOpen(false);
  };

  const currentStyleConfig =
    REPORT_STYLES.find((style) => style.value === currentStyle) ||
    REPORT_STYLES[0]!;
  const CurrentIcon = currentStyleConfig.icon;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip
        className="max-w-60"
        title={
          <div>
            <h3 className="mb-2 font-bold">
              {t("writingStyle")}: {t(currentStyleConfig.labelKey)}
            </h3>
            <p>{t("chooseDesc")}</p>
          </div>
        }
      >
        <DialogTrigger asChild>
          <Button
            className="!border-brand !text-brand rounded-2xl"
            variant="outline"
          >
            <CurrentIcon className="h-4 w-4" /> {t(currentStyleConfig.labelKey)}
          </Button>
        </DialogTrigger>
      </Tooltip>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{t("chooseTitle")}</DialogTitle>
          <DialogDescription>{t("chooseDesc")}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-4">
          {REPORT_STYLES.map((style) => {
            const Icon = style.icon;
            const isSelected = currentStyle === style.value;

            return (
              <button
                key={style.value}
                className={cn(
                  "hover:bg-accent flex items-start gap-3 rounded-lg border p-4 text-left transition-colors",
                  isSelected && "border-primary bg-accent",
                )}
                onClick={() => handleStyleChange(style.value)}
              >
                <Icon className="mt-0.5 h-5 w-5 shrink-0" />
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium">{t(style.labelKey)}</h4>
                    {isSelected && <Check className="text-primary h-4 w-4" />}
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {t(style.descriptionKey)}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
