"use client";

/**
 * StatusBlock — operating-state badge for a single equipment / unit.
 *
 * Six canonical states match the `--status-*` palette injected in
 * `globals.css` (P0). When `comm-loss` is rendered, the dot is left blinking
 * via CSS `animate-pulse` so the operator notices stale data; everything
 * else is static — industrial HMIs avoid ambient motion (ISA-101 §6.6).
 *
 * `prefers-reduced-motion` already disables the pulse globally (P0).
 */

type StatusKind =
  | "running"
  | "stopped"
  | "maint"
  | "standby"
  | "fault"
  | "comm-loss";

interface StatusBlockProps {
  block: {
    props: {
      status: StatusKind;
      tag?: string;
      label?: string;
    };
  };
}

const STATUS_LABEL_ZH: Record<StatusKind, string> = {
  running: "运行",
  stopped: "停机",
  maint: "维修",
  standby: "备用",
  fault: "故障",
  "comm-loss": "失联",
};

const STATUS_BG: Record<StatusKind, string> = {
  running: "bg-status-running text-status-foreground",
  stopped: "bg-status-stopped text-status-foreground",
  maint: "bg-status-maint text-status-foreground",
  standby: "bg-status-standby text-status-foreground",
  fault: "bg-status-fault text-status-foreground",
  "comm-loss": "bg-status-comm-loss text-status-foreground",
};

export default function StatusBlock({ block }: StatusBlockProps) {
  const { props } = block;
  const safeStatus: StatusKind =
    props.status in STATUS_LABEL_ZH ? props.status : "stopped";
  const labelText = STATUS_LABEL_ZH[safeStatus];

  return (
    <div
      className="bg-card text-card-foreground inline-flex items-center gap-2 rounded-md border px-3 py-1.5"
      role="status"
      aria-label={`${props.tag ?? props.label ?? labelText} ${labelText}`}
    >
      <span
        className={`inline-flex h-2 w-2 rounded-full ${STATUS_BG[safeStatus]} ${
          safeStatus === "comm-loss" ? "animate-pulse" : ""
        }`}
        aria-hidden="true"
      />
      {props.tag && (
        <span
          className="text-muted-foreground font-mono text-xs"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {props.tag}
        </span>
      )}
      {props.label && (
        <span className="text-foreground text-sm">{props.label}</span>
      )}
      <span
        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${STATUS_BG[safeStatus]}`}
      >
        {labelText}
      </span>
    </div>
  );
}
