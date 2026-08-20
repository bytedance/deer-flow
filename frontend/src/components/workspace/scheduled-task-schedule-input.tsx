"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import {
  pad2,
  parseCron,
  serializeCron,
  utcToZonedLocalInput,
  zonedLocalToUtcIso,
  WEEKDAYS,
  type CronParts,
  type CronPreset,
  type Weekday,
} from "@/core/scheduled-tasks/cron";

export type ScheduleValue = {
  schedule_type: "once" | "cron";
  schedule_spec: { cron?: string; run_at?: string };
  timezone: string;
};

const PRESETS: CronPreset[] = [
  "hourly",
  "daily",
  "weekly",
  "monthly",
  "custom",
];

// 只保留最常用的几个时区，避免选项过多难以选择。
const COMMON_TIMEZONES: Array<{ value: string; label: string }> = [
  { value: "UTC", label: "世界标准时间 (UTC)" },
  { value: "Asia/Shanghai", label: "中国标准时间 (上海)" },
  { value: "Asia/Hong_Kong", label: "香港时间" },
  { value: "Asia/Tokyo", label: "日本标准时间 (东京)" },
  { value: "Asia/Singapore", label: "新加坡时间" },
  { value: "Asia/Seoul", label: "韩国标准时间 (首尔)" },
  { value: "Europe/London", label: "伦敦" },
  { value: "Europe/Berlin", label: "柏林" },
  { value: "America/New_York", label: "纽约" },
  { value: "America/Los_Angeles", label: "洛杉矶" },
];

function detectBrowserTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (typeof tz === "string" && tz.length > 0) {
      return tz;
    }
  } catch {
    // resolvedOptions unavailable
  }
  return "UTC";
}

function parseLocal(value: string): {
  year: string;
  month: string;
  day: string;
  time: string;
} {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}:\d{2}))?$/.exec(
    value || "",
  );
  return match
    ? {
        year: match[1] ?? "",
        month: match[2] ?? "",
        day: match[3] ?? "",
        time: match[4] ?? "",
      }
    : { year: "", month: "", day: "", time: "" };
}

function OncePart({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: number;
  max: number;
}) {
  return (
    <div className="flex flex-1 flex-col gap-1">
      <span className="text-muted-foreground text-xs">{label}</span>
      <Input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

export function ScheduledTaskScheduleInput({
  initial,
  onChange,
  scheduleTypeLocked = false,
}: {
  initial: ScheduleValue;
  onChange: (value: ScheduleValue) => void;
  scheduleTypeLocked?: boolean;
}) {
  const { t, locale } = useI18n();
  const labels = t.scheduledTasks;
  const isZh = locale.startsWith("zh");

  const [scheduleType, setScheduleType] = useState<"once" | "cron">(
    initial.schedule_type,
  );
  const [preset, setPreset] = useState<CronPreset>(
    () => parseCron(initial.schedule_spec.cron ?? "0 9 * * *").preset,
  );
  const [parts, setParts] = useState<CronParts>(
    () => parseCron(initial.schedule_spec.cron ?? "0 9 * * *").parts,
  );
  const initOnce =
    initial.schedule_type === "once" && initial.schedule_spec.run_at
      ? parseLocal(
          utcToZonedLocalInput(
            initial.schedule_spec.run_at,
            initial.timezone || "UTC",
          ),
        )
      : { year: "", month: "", day: "", time: "" };
  const [onceYear, setOnceYear] = useState(initOnce.year);
  const [onceMonth, setOnceMonth] = useState(initOnce.month);
  const [onceDay, setOnceDay] = useState(initOnce.day);
  const [onceTime, setOnceTime] = useState(initOnce.time);
  const [timezone, setTimezone] = useState<string>(
    initial.timezone || detectBrowserTimezone(),
  );

  // Hold the latest onChange in a ref so the effect below does not depend on
  // it. This avoids a re-render loop: if the parent passes an inline
  // onChange (new reference each render), depending on it directly would
  // re-fire the effect every render and call onChange again, looping.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  // Emit on every change including mount. On mount this syncs the parent with
  // the browser-detected timezone and the canonicalized cron, so the submitted
  // value always matches what the user sees in the form.
  useEffect(() => {
    if (scheduleType === "once") {
      const year = Number(onceYear);
      const month = Number(onceMonth);
      const day = Number(onceDay);
      const validDate =
        onceYear &&
        onceMonth &&
        onceDay &&
        Number.isInteger(year) &&
        Number.isInteger(month) &&
        Number.isInteger(day) &&
        year >= 1970 &&
        month >= 1 &&
        month <= 12 &&
        day >= 1 &&
        day <= 31 &&
        new Date(Date.UTC(year, month - 1, day)).getUTCDate() === day;
      const runAtLocal = validDate
        ? `${onceYear}-${pad2(month)}-${pad2(day)}${onceTime ? `T${onceTime}` : ""}`
        : "";
      const runAt = runAtLocal ? zonedLocalToUtcIso(runAtLocal, timezone) : "";
      onChangeRef.current({
        schedule_type: "once",
        schedule_spec: runAt ? { run_at: runAt } : {},
        timezone,
      });
      return;
    }
    const cron =
      preset === "custom" ? (parts.raw ?? "") : serializeCron(preset, parts);
    onChangeRef.current({
      schedule_type: "cron",
      schedule_spec: cron ? { cron } : {},
      timezone,
    });
  }, [
    scheduleType,
    preset,
    parts,
    onceYear,
    onceMonth,
    onceDay,
    onceTime,
    timezone,
  ]);

  const timezoneOptions = useMemo(() => {
    const options = COMMON_TIMEZONES.map((tz) => ({
      value: tz.value,
      label: isZh ? tz.label : tz.value,
    }));
    if (!options.some((tz) => tz.value === timezone)) {
      options.unshift({ value: timezone, label: timezone });
    }
    return options;
  }, [isZh, timezone]);

  function updateParts(patch: Partial<CronParts>) {
    setParts((prev) => ({ ...prev, ...patch }));
  }

  function changePreset(next: CronPreset) {
    setParts((prev) => {
      const merged = { ...prev };
      if (next === "weekly" && (merged.weekdays ?? []).length === 0) {
        merged.weekdays = ["mon"];
      }
      if (next === "monthly" && merged.dayOfMonth == null) {
        merged.dayOfMonth = 1;
      }
      if (next === "custom" && !merged.raw) {
        merged.raw = serializeCron("daily", prev);
      }
      return merged;
    });
    setPreset(next);
  }

  function toggleWeekday(w: Weekday) {
    setParts((prev) => {
      const set = new Set(prev.weekdays ?? []);
      if (set.has(w)) {
        if (set.size <= 1) {
          return prev;
        }
        set.delete(w);
      } else {
        set.add(w);
      }
      return { ...prev, weekdays: WEEKDAYS.filter((d) => set.has(d)) };
    });
  }

  return (
    <div className="flex flex-col gap-2" data-testid="schedule-input">
      {!scheduleTypeLocked && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant={scheduleType === "cron" ? "default" : "outline"}
            size="sm"
            onClick={() => setScheduleType("cron")}
          >
            {labels.scheduleType.cron}
          </Button>
          <Button
            variant={scheduleType === "once" ? "default" : "outline"}
            size="sm"
            onClick={() => setScheduleType("once")}
          >
            {labels.scheduleType.once}
          </Button>
        </div>
      )}

      {scheduleType === "cron" ? (
        <>
          <Select
            value={preset}
            onValueChange={(v) => changePreset(v as CronPreset)}
          >
            <SelectTrigger className="w-full" data-testid="schedule-preset">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRESETS.map((p) => (
                <SelectItem key={p} value={p}>
                  {labels.preset[p]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {preset === "hourly" && (
            <Input
              type="number"
              min={0}
              max={59}
              value={parts.minute ?? 0}
              onChange={(e) => updateParts({ minute: Number(e.target.value) })}
              aria-label={labels.fields.minute}
            />
          )}

          {(preset === "daily" ||
            preset === "weekly" ||
            preset === "monthly") && (
            <Input
              type="time"
              value={`${pad2(parts.hour ?? 9)}:${pad2(parts.minute ?? 0)}`}
              onChange={(e) => {
                const [h, m] = e.target.value.split(":").map(Number);
                updateParts({ hour: h, minute: m });
              }}
              aria-label={labels.fields.time}
            />
          )}

          {preset === "weekly" && (
            <div className="flex flex-wrap gap-1">
              <span className="text-muted-foreground w-full text-sm">
                {labels.fields.weekday}
              </span>
              {WEEKDAYS.map((w) => {
                const active = (parts.weekdays ?? []).includes(w);
                return (
                  <Button
                    key={w}
                    variant={active ? "default" : "outline"}
                    size="sm"
                    onClick={() => toggleWeekday(w)}
                    aria-pressed={active}
                  >
                    {labels.weekdays[w]}
                  </Button>
                );
              })}
            </div>
          )}

          {preset === "monthly" && (
            <Input
              type="number"
              min={1}
              max={31}
              value={parts.dayOfMonth ?? 1}
              onChange={(e) =>
                updateParts({ dayOfMonth: Number(e.target.value) })
              }
              aria-label={labels.fields.dayOfMonth}
            />
          )}

          {preset === "custom" && (
            <div className="flex flex-col gap-1">
              <Input
                value={parts.raw ?? ""}
                onChange={(e) => updateParts({ raw: e.target.value })}
                placeholder={labels.fields.cronPlaceholder}
                aria-label={labels.fields.cron}
              />
              <a
                href="https://crontab.guru/"
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground text-xs hover:underline"
              >
                {labels.cronHelp} ↗
              </a>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex items-end gap-2">
            <OncePart
              label={labels.fields.year}
              value={onceYear}
              onChange={setOnceYear}
              min={2000}
              max={2100}
            />
            <OncePart
              label={labels.fields.month}
              value={onceMonth}
              onChange={setOnceMonth}
              min={1}
              max={12}
            />
            <OncePart
              label={labels.fields.day}
              value={onceDay}
              onChange={setOnceDay}
              min={1}
              max={31}
            />
          </div>
          <Input
            type="time"
            value={onceTime}
            onChange={(e) => setOnceTime(e.target.value)}
            aria-label={labels.fields.time}
          />
        </>
      )}

      <Select value={timezone} onValueChange={setTimezone}>
        <SelectTrigger className="w-full" data-testid="schedule-timezone">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {timezoneOptions.map((tz) => (
            <SelectItem key={tz.value} value={tz.value}>
              {tz.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
