"use client";

import { CheckCircle2, Circle, Clock } from "@/components/ui/icons";

interface TimelineEvent {
  title: string;
  description?: string;
  timestamp?: string;
  status?: "completed" | "active" | "pending";
  icon?: string;
}

interface TimelineBlockProps {
  block: {
    props: {
      title?: string;
      events: TimelineEvent[];
      orientation?: "vertical" | "horizontal";
    };
  };
}

export default function TimelineBlock({ block }: TimelineBlockProps) {
  const { props } = block;
  const { title, events } = props;

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="h-4 w-4 text-green-600" />;
      case "active":
        return <Clock className="h-4 w-4 text-blue-600" />;
      default:
        return <Circle className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <div className="rounded-lg border bg-card p-4" role="list" aria-label={title ?? "Timeline"}>
      {title && <h3 className="mb-3 text-sm font-medium">{title}</h3>}
      <div className="space-y-0">
        {events.map((event, i) => (
          <div key={i} className="flex gap-3" role="listitem" aria-label={`${event.title}${event.status ? ` (${event.status})` : ""}`}>
            <div className="flex flex-col items-center" aria-hidden="true">
              {getStatusIcon(event.status)}
              {i < events.length - 1 && (
                <div className="my-1 h-full w-px bg-border" />
              )}
            </div>
            <div className="pb-4">
              <p className="text-sm font-medium">{event.title}</p>
              {event.description && (
                <p className="mt-0.5 text-xs text-muted-foreground">{event.description}</p>
              )}
              {event.timestamp && (
                <p className="mt-0.5 text-xs text-muted-foreground"><time>{event.timestamp}</time></p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
