"use client";

import { useI18n } from "@/core/i18n/hooks";

interface RememberSessionOptionProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

export function RememberSessionOption({
  checked,
  onCheckedChange,
}: RememberSessionOptionProps) {
  const { t } = useI18n();

  return (
    <label className="text-muted-foreground flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onCheckedChange(event.currentTarget.checked)}
        className="border-input mt-1 h-4 w-4 rounded"
      />
      <span>
        <span className="text-foreground block font-medium">
          {t.login.rememberMe}
        </span>
        <span>{t.login.rememberMeDescription}</span>
      </span>
    </label>
  );
}
