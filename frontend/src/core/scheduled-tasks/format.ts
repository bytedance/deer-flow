/**
 * Human time formatting for scheduled tasks: "Tomorrow 09:00", "Fri 09:00",
 * "Oct 9 09:00". Pure functions; the relative-day words come from
 * `t.scheduledTasks.time` so this module never bundles a locale itself.
 */

import type { ScheduledTask } from "./types";

/** `t.scheduledTasks.time`: "{time}" templates for relative days and the viewer's own time. */
export type TaskTimeLabels = {
  today: string;
  tomorrow: string;
  yesterday: string;
  yourTime: string;
};

export type FormatTaskTimeOptions = {
  /** IANA zone the time is shown in. */
  timeZone: string;
  /** App locale ("en-US", "zh-CN"); anything starting with "zh" formats as Chinese. */
  locale: string;
  labels: TaskTimeLabels;
  now?: Date;
};

const DAY_MS = 24 * 60 * 60 * 1000;

type ZonedParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  weekday: number;
};

const WEEKDAY_INDEX: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

function zonedParts(date: Date, timeZone: string): ZonedParts {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    weekday: "short",
  }).formatToParts(date);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")) % 24,
    minute: Number(get("minute")),
    weekday: WEEKDAY_INDEX[get("weekday")] ?? 0,
  };
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

const EN_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const ZH_WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const EN_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function isZh(locale: string): boolean {
  return locale.toLowerCase().startsWith("zh");
}

/**
 * Calendar-day label of `date` relative to `now`, both read in `timeZone`;
 * null for a plain date. Without `labels` there are no relative words, so
 * today/tomorrow/yesterday read as a plain date.
 */
function dayPart(
  date: ZonedParts,
  now: ZonedParts,
  {
    locale,
    labels,
  }: { locale: string; labels?: FormatTaskTimeOptions["labels"] },
): { relative: string | null; absolute: string } {
  const diff = Math.round(
    (Date.UTC(date.year, date.month - 1, date.day) -
      Date.UTC(now.year, now.month - 1, now.day)) /
      DAY_MS,
  );
  const zh = isZh(locale);
  if (labels) {
    if (diff === 0) return { relative: labels.today, absolute: "" };
    if (diff === 1) return { relative: labels.tomorrow, absolute: "" };
    if (diff === -1) return { relative: labels.yesterday, absolute: "" };
  }
  if (labels && diff > 1 && diff < 7) {
    const weekday = (zh ? ZH_WEEKDAYS : EN_WEEKDAYS)[date.weekday] ?? "";
    return { relative: null, absolute: weekday };
  }
  const sameYear = date.year === now.year;
  if (zh) {
    return {
      relative: null,
      absolute: `${sameYear ? "" : `${date.year}年`}${date.month}月${date.day}日`,
    };
  }
  const month = EN_MONTHS[date.month - 1] ?? "";
  return {
    relative: null,
    absolute: sameYear
      ? `${month} ${date.day}`
      : `${month} ${date.day}, ${date.year}`,
  };
}

function render(
  iso: string,
  options: Omit<FormatTaskTimeOptions, "labels"> & {
    labels?: FormatTaskTimeOptions["labels"];
  },
): { day: string; time: string; text: string } | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  let parts: ZonedParts;
  let nowParts: ZonedParts;
  try {
    parts = zonedParts(date, options.timeZone);
    nowParts = zonedParts(options.now ?? new Date(), options.timeZone);
  } catch {
    // Unknown zone name.
    return null;
  }
  const time = `${pad2(parts.hour)}:${pad2(parts.minute)}`;
  const { relative, absolute } = dayPart(parts, nowParts, options);
  if (relative !== null) {
    return {
      day: relative,
      time,
      text: relative.replace("{time}", time),
    };
  }
  return { day: absolute, time, text: `${absolute} ${time}` };
}

/**
 * "Today 09:00", "Tomorrow 09:00", "Yesterday 09:00", "Fri 09:00" (within the
 * week ahead), else "Oct 9 09:00" / "10月9日 09:00" (the year only when it
 * differs). 24-hour time, read in `timeZone`. Returns "" for an invalid value.
 */
export function formatTaskTime(
  iso: string,
  options: FormatTaskTimeOptions,
): string {
  return render(iso, options)?.text ?? "";
}

/**
 * An absolute "Oct 7 09:00" / "10月7日 09:00" (the year only when it differs
 * from `now`'s), for places that have no relative-day labels at hand. Returns
 * "" for an invalid value.
 */
export function formatTaskDateTime(
  iso: string,
  options: Omit<FormatTaskTimeOptions, "labels">,
): string {
  return render(iso, options)?.text ?? "";
}

/**
 * The time in the task's zone, plus "· {time} your time" when the viewer's
 * browser zone differs (the day is repeated only when it differs too).
 */
export function formatWithViewerTime(
  iso: string,
  taskTimeZone: string,
  options: Omit<FormatTaskTimeOptions, "timeZone"> & {
    viewerTimeZone?: string;
  },
): string {
  const task = render(iso, { ...options, timeZone: taskTimeZone });
  if (!task) {
    return "";
  }
  const viewerTimeZone = options.viewerTimeZone ?? browserTimeZone();
  if (sameZone(viewerTimeZone, taskTimeZone, iso)) {
    return task.text;
  }
  const viewer = render(iso, { ...options, timeZone: viewerTimeZone });
  if (!viewer) {
    return task.text;
  }
  const viewerText = viewer.day === task.day ? viewer.time : viewer.text;
  return `${task.text} · ${options.labels.yourTime.replace("{time}", viewerText)}`;
}

/** Same zone name, or two names that show the same wall time for this instant. */
function sameZone(a: string, b: string, iso: string): boolean {
  if (a === b) {
    return true;
  }
  try {
    const date = new Date(iso);
    const left = zonedParts(date, a);
    const right = zonedParts(date, b);
    return (
      left.year === right.year &&
      left.month === right.month &&
      left.day === right.day &&
      left.hour === right.hour &&
      left.minute === right.minute
    );
  } catch {
    return false;
  }
}

/** The viewer's IANA zone, or "UTC" when the browser cannot tell. */
export function browserTimeZone(): string {
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (typeof timeZone === "string" && timeZone.length > 0) {
      return timeZone;
    }
  } catch {
    // resolvedOptions unavailable
  }
  return "UTC";
}

/**
 * The zone a task's times are shown in. Interval tasks run on elapsed time,
 * so they use the viewer's zone and never the stored placeholder `UTC` of a
 * task created without a zone; every other task uses its own zone.
 */
export function displayTimeZone(
  task: Pick<ScheduledTask, "schedule_type" | "timezone">,
): string {
  if (task.schedule_type === "interval") {
    return browserTimeZone();
  }
  return task.timezone || browserTimeZone();
}
