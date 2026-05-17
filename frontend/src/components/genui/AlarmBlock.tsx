"use client";

/**
 * AlarmBlock — list of process alarms following the IEC 62682 / ISA-18.2
 * five-priority palette (critical / high / medium / low / journal).
 *
 * Backend skills (e.g. `vibration-fault-diagnosis`) emit alarm items with a
 * `level`, optional `tag`, message, time, and ack state. The frontend only
 * renders — there is no client-side ack/suppress logic; if a skill needs
 * follow-up actions it should emit a separate `form` or `confirm` block.
 */

import { AlertTriangleIcon, CheckIcon, InfoIcon } from "lucide-react";

type AlarmLevel = "critical" | "high" | "medium" | "low" | "journal";

interface AlarmItem {
  level: AlarmLevel;
  message: string;
  tag?: string;
  time?: string;
  source?: string;
  acked?: boolean;
}

interface AlarmBlockProps {
  block: {
    props: {
      title?: string;
      items: AlarmItem[];
    };
  };
}

const LEVEL_BG: Record<AlarmLevel, string> = {
  critical: "bg-alarm-critical text-alarm-foreground",
  high: "bg-alarm-high text-alarm-foreground",
  medium: "bg-alarm-medium text-alarm-foreground",
  low: "bg-alarm-low text-alarm-foreground",
  journal: "bg-alarm-journal text-alarm-foreground",
};

const LEVEL_LABEL_ZH: Record<AlarmLevel, string> = {
  critical: "紧急",
  high: "高",
  medium: "中",
  low: "低",
  journal: "记录",
};

function AlarmIcon({ level }: { level: AlarmLevel }) {
  if (level === "critical" || level === "high") {
    return <AlertTriangleIcon className="size-3.5" aria-hidden="true" />;
  }
  if (level === "journal") {
    return <InfoIcon className="size-3.5" aria-hidden="true" />;
  }
  return <AlertTriangleIcon className="size-3.5" aria-hidden="true" />;
}

export default function AlarmBlock({ block }: AlarmBlockProps) {
  const items = Array.isArray(block.props.items) ? block.props.items : [];

  if (items.length === 0) {
    return (
      <div
        className="bg-card text-muted-foreground rounded-lg border p-4 text-sm"
        role="region"
        aria-label={block.props.title ?? "alarms"}
      >
        无报警
      </div>
    );
  }

  return (
    <div
      className="bg-card text-card-foreground flex flex-col gap-2 rounded-lg border p-4"
      role="region"
      aria-label={block.props.title ?? "alarms"}
    >
      {block.props.title && (
        <h3 className="text-sm font-semibold">{block.props.title}</h3>
      )}
      <ul className="flex flex-col gap-1.5">
        {items.map((item, index) => (
          <li
            key={`${item.tag ?? "alarm"}-${index}`}
            className="border-border/60 flex items-start gap-3 rounded-md border-l-4 px-3 py-2 text-sm"
            style={{
              borderLeftColor: `var(--color-alarm-${item.level})`,
            }}
          >
            <span
              className={`inline-flex h-5 shrink-0 items-center gap-1 rounded px-1.5 text-[10px] font-semibold uppercase ${LEVEL_BG[item.level] ?? LEVEL_BG.journal}`}
              aria-label={`${LEVEL_LABEL_ZH[item.level] ?? item.level} 级`}
            >
              <AlarmIcon level={item.level} />
              {LEVEL_LABEL_ZH[item.level] ?? item.level}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <p className="text-foreground leading-snug break-words">
                {item.tag && (
                  <span
                    className="text-muted-foreground mr-1 font-mono text-xs"
                    style={{ fontVariantNumeric: "tabular-nums" }}
                  >
                    {item.tag}
                  </span>
                )}
                {item.message}
              </p>
              {(item.time ?? item.source) && (
                <p
                  className="text-muted-foreground text-xs"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {item.time}
                  {item.time && item.source && " · "}
                  {item.source}
                </p>
              )}
            </div>
            {item.acked && (
              <span
                className="text-muted-foreground inline-flex items-center gap-0.5 text-[10px]"
                aria-label="已确认"
              >
                <CheckIcon className="size-3" />
                已确认
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
