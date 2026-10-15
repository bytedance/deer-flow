"use client";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useChannelConnections } from "@/core/channels/hooks";
import { useScheduledTasksFeature } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import {
  notificationGroupName,
  notificationGroups,
} from "@/core/scheduled-tasks/notification-groups";

import { BindFeishuGroup } from "./bind-feishu-group";

const NO_GROUP = "__no_additional_group__";

type NotificationGroupSelectProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
};

/** Older Gateways ignore unknown fields: do not offer a destination they cannot save. */
export function NotificationGroupSelect(props: NotificationGroupSelectProps) {
  const { groupNotifications, isLoading } = useScheduledTasksFeature();
  const { t } = useI18n();
  if (isLoading) {
    return (
      <p role="status" className="text-muted-foreground text-sm">
        {t.scheduledTasks.notificationGroup.loading}
      </p>
    );
  }
  if (!groupNotifications && props.value) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-muted-foreground text-sm">
          {t.scheduledTasks.notificationGroup.savedUnavailable}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => props.onChange("")}
        >
          {t.scheduledTasks.notificationGroup.clearSaved}
        </Button>
      </div>
    );
  }
  return groupNotifications ? (
    <EnabledNotificationGroupSelect {...props} />
  ) : null;
}

/** Loading or losing the list must never reset the form's saved selection. */
function EnabledNotificationGroupSelect({
  id,
  value,
  onChange,
}: NotificationGroupSelectProps) {
  const { t } = useI18n();
  const labels = t.scheduledTasks.notificationGroup;
  const { connections, isLoading, error } = useChannelConnections();
  const groups = notificationGroups(connections);
  const selected = groups.find((group) => group.id === value);
  const selectedMissing = Boolean(value) && !selected;
  const unnamed = groups.some((group) => !notificationGroupName(group));
  const hint = error
    ? labels.loadFailed
    : isLoading
      ? labels.loading
      : selectedMissing
        ? labels.unavailableHint
        : unnamed
          ? labels.unnamedHint
          : groups.length === 0
            ? labels.emptyHint
            : null;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {labels.label}
      </label>
      <Select
        value={value || NO_GROUP}
        onValueChange={(next) => onChange(next === NO_GROUP ? "" : next)}
      >
        <SelectTrigger
          id={id}
          className="w-full"
          aria-label={labels.label}
          aria-describedby={`${id}-hint`}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_GROUP}>{labels.none}</SelectItem>
          {selectedMissing && (
            <SelectItem value={value} disabled>
              {isLoading ? labels.loading : labels.unavailable}
            </SelectItem>
          )}
          {groups.map((group) => (
            <SelectItem
              key={group.id}
              value={group.id}
              disabled={!notificationGroupName(group) || Boolean(error)}
            >
              {notificationGroupName(group) ?? labels.unnamed}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div id={`${id}-hint`} className="text-muted-foreground text-xs">
        <p>{labels.personalHint}</p>
        {hint && <p role="status">{hint}</p>}
      </div>
      <BindFeishuGroup />
    </div>
  );
}

/** Shares the existing connections query cache, without adding a polling loop. */
export function NotificationGroupSummary({
  connectionId,
}: {
  connectionId: string;
}) {
  const { t } = useI18n();
  const labels = t.scheduledTasks.notificationGroup;
  const { connections, isLoading, error } = useChannelConnections();
  const group = notificationGroups(connections).find(
    (connection) => connection.id === connectionId,
  );
  const name = notificationGroupName(group);
  return (
    <div data-testid="scheduled-task-notification-group">
      <p>
        {name ??
          (isLoading
            ? labels.loading
            : group
              ? labels.unnamed
              : labels.unavailable)}
      </p>
      <p className="text-muted-foreground text-xs">{labels.personalHint}</p>
      {error && (
        <p className="text-muted-foreground text-xs">{labels.loadFailed}</p>
      )}
    </div>
  );
}
