"use client";

import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  useCreateManagedSubagent,
  useDeleteManagedSubagent,
  useSubagents,
  useUpdateManagedSubagent,
} from "@/core/subagents";
import type { Subagent } from "@/core/subagents";

import { SettingsSection } from "./settings-section";
import {
  isValidManagedSubagentName,
  optionalNameListFromDraft,
  optionalNameListToDraft,
  positiveInteger,
  type OptionalNameListMode,
} from "./subagent-settings-helpers";

type Draft = {
  name: string;
  displayName: string;
  description: string;
  systemPrompt: string;
  model: string;
  toolsMode: OptionalNameListMode;
  tools: string;
  skillsMode: OptionalNameListMode;
  skills: string;
  maxTurns: string;
  timeoutSeconds: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  displayName: "",
  description: "",
  systemPrompt: "",
  model: "inherit",
  toolsMode: "all",
  tools: "",
  skillsMode: "all",
  skills: "",
  maxTurns: "50",
  timeoutSeconds: "900",
};

function formatOverrideValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function draftFrom(subagent: Subagent): Draft {
  const tools = optionalNameListToDraft(subagent.tools);
  const skills = optionalNameListToDraft(subagent.skills);
  return {
    name: subagent.name,
    displayName: subagent.display_name ?? "",
    description: subagent.description,
    systemPrompt: subagent.system_prompt ?? "",
    model: subagent.model,
    toolsMode: tools.mode,
    tools: tools.text,
    skillsMode: skills.mode,
    skills: skills.text,
    maxTurns: String(subagent.max_turns),
    timeoutSeconds: String(subagent.timeout_seconds),
  };
}

export function SubagentSettingsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const { subagents, isLoading, error } = useSubagents();
  const update = useUpdateManagedSubagent();
  const remove = useDeleteManagedSubagent();
  const [editing, setEditing] = useState<Subagent | "new" | null>(null);

  async function setEnabled(subagent: Subagent, enabled: boolean) {
    try {
      await update.mutateAsync({ name: subagent.name, request: { enabled } });
      toast.success(t.settings.subagents.saved);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteSubagent(subagent: Subagent) {
    if (!window.confirm(t.settings.subagents.deleteConfirm)) return;
    try {
      await remove.mutateAsync(subagent.name);
      toast.success(t.settings.subagents.deleted);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <SettingsSection
      title={t.settings.subagents.title}
      description={t.settings.subagents.description}
    >
      <div className="space-y-4">
        <p className="text-muted-foreground text-sm">
          {t.settings.subagents.executionNote}
        </p>
        <div className="flex items-center justify-between gap-4">
          {!isAdmin && (
            <p className="text-muted-foreground text-sm">
              {t.settings.subagents.adminNote}
            </p>
          )}
          {isAdmin && (
            <Button
              size="sm"
              className="ml-auto"
              onClick={() => setEditing("new")}
            >
              <PlusIcon className="size-4" />
              {t.settings.subagents.create}
            </Button>
          )}
        </div>

        {isLoading ? (
          <p className="text-muted-foreground text-sm">{t.common.loading}</p>
        ) : error ? (
          <p className="text-destructive text-sm">{error.message}</p>
        ) : subagents.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.settings.subagents.empty}
          </p>
        ) : (
          <div className="space-y-3">
            {subagents.map((subagent) => (
              <Item
                variant="outline"
                key={`${subagent.source}-${subagent.name}`}
              >
                <ItemContent>
                  <ItemTitle className="flex flex-wrap items-center gap-2">
                    <span>{subagent.display_name ?? subagent.name}</span>
                    <Badge variant="outline">
                      {subagent.source === "builtin"
                        ? t.settings.subagents.sourceBuiltin
                        : subagent.source === "config"
                          ? t.settings.subagents.sourceConfig
                          : t.settings.subagents.sourceManaged}
                    </Badge>
                    {subagent.conflict && (
                      <Badge variant="destructive">
                        {t.settings.subagents.conflict}
                      </Badge>
                    )}
                  </ItemTitle>
                  <ItemDescription>{subagent.description}</ItemDescription>
                  {Object.keys(subagent.config_overrides).length > 0 && (
                    <p className="text-muted-foreground text-xs">
                      {t.settings.subagents.overridden}:{" "}
                      {Object.entries(subagent.config_overrides)
                        .map(
                          ([field, value]) =>
                            `${field}=${formatOverrideValue(value)}`,
                        )
                        .join("; ")}
                    </p>
                  )}
                </ItemContent>
                <ItemActions className="gap-1">
                  {isAdmin && subagent.editable && (
                    <>
                      <Switch
                        checked={subagent.enabled}
                        disabled={update.isPending || subagent.conflict}
                        onCheckedChange={(enabled) =>
                          void setEnabled(subagent, enabled)
                        }
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditing(subagent)}
                      >
                        <PencilIcon className="size-4" />
                        <span className="sr-only">{t.common.edit}</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => void deleteSubagent(subagent)}
                      >
                        <Trash2Icon className="size-4" />
                        <span className="sr-only">{t.common.delete}</span>
                      </Button>
                    </>
                  )}
                </ItemActions>
              </Item>
            ))}
          </div>
        )}
      </div>

      <SubagentEditor
        value={editing}
        onOpenChange={(open) => !open && setEditing(null)}
      />
    </SettingsSection>
  );
}

function SubagentEditor({
  value,
  onOpenChange,
}: {
  value: Subagent | "new" | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { models } = useModels();
  const create = useCreateManagedSubagent();
  const update = useUpdateManagedSubagent();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);

  useEffect(() => {
    setDraft(value && value !== "new" ? draftFrom(value) : EMPTY_DRAFT);
  }, [value]);

  const isNew = value === "new";
  const pending = create.isPending || update.isPending;

  function set<K extends keyof Draft>(key: K, next: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: next }));
  }

  async function save() {
    const maxTurns = positiveInteger(draft.maxTurns);
    const timeoutSeconds = positiveInteger(draft.timeoutSeconds);
    if (
      maxTurns === null ||
      timeoutSeconds === null ||
      !isValidManagedSubagentName(draft.name)
    )
      return;

    const payload = {
      display_name: draft.displayName.trim() || null,
      description: draft.description.trim(),
      system_prompt: draft.systemPrompt.trim(),
      model: draft.model,
      tools: optionalNameListFromDraft(draft.toolsMode, draft.tools),
      skills: optionalNameListFromDraft(draft.skillsMode, draft.skills),
      max_turns: maxTurns,
      timeout_seconds: timeoutSeconds,
    };
    try {
      if (isNew) {
        await create.mutateAsync({ name: draft.name.trim(), ...payload });
        toast.success(t.settings.subagents.created);
      } else if (value) {
        await update.mutateAsync({ name: value.name, request: payload });
        toast.success(t.settings.subagents.saved);
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Dialog open={value !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isNew
              ? t.settings.subagents.createTitle
              : t.settings.subagents.editTitle}
          </DialogTitle>
          <DialogDescription>
            {t.settings.subagents.description}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-1 sm:grid-cols-2">
          <Field label={t.settings.subagents.name}>
            <Input
              value={draft.name}
              disabled={!isNew}
              onChange={(event) => set("name", event.target.value)}
            />
            {isNew && (
              <p className="text-muted-foreground text-xs">
                {t.settings.subagents.nameHint}
              </p>
            )}
          </Field>
          <Field label={t.settings.subagents.displayName}>
            <Input
              value={draft.displayName}
              onChange={(event) => set("displayName", event.target.value)}
            />
          </Field>
          <Field
            className="sm:col-span-2"
            label={t.settings.subagents.descriptionLabel}
          >
            <Textarea
              value={draft.description}
              onChange={(event) => set("description", event.target.value)}
            />
          </Field>
          <Field
            className="sm:col-span-2"
            label={t.settings.subagents.systemPrompt}
          >
            <Textarea
              className="min-h-32"
              value={draft.systemPrompt}
              onChange={(event) => set("systemPrompt", event.target.value)}
            />
          </Field>
          <Field label={t.settings.subagents.model}>
            <Select
              value={draft.model}
              onValueChange={(next) => set("model", next)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inherit">
                  {t.settings.subagents.inheritModel}
                </SelectItem>
                {models.map((model) => (
                  <SelectItem key={model.name} value={model.name}>
                    {model.display_name || model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t.settings.subagents.tools}>
            <OptionalNameListField
              mode={draft.toolsMode}
              text={draft.tools}
              onModeChange={(mode) => set("toolsMode", mode)}
              onTextChange={(text) => set("tools", text)}
            />
          </Field>
          <Field label={t.settings.subagents.skills}>
            <OptionalNameListField
              mode={draft.skillsMode}
              text={draft.skills}
              onModeChange={(mode) => set("skillsMode", mode)}
              onTextChange={(text) => set("skills", text)}
            />
          </Field>
          <Field label={t.settings.subagents.maxTurns}>
            <Input
              type="number"
              min={1}
              step={1}
              value={draft.maxTurns}
              onChange={(event) => set("maxTurns", event.target.value)}
            />
          </Field>
          <Field label={t.settings.subagents.timeout}>
            <Input
              type="number"
              min={1}
              step={1}
              value={draft.timeoutSeconds}
              onChange={(event) => set("timeoutSeconds", event.target.value)}
            />
          </Field>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            {t.common.cancel}
          </Button>
          <Button
            onClick={() => void save()}
            disabled={
              pending ||
              !isValidManagedSubagentName(draft.name) ||
              !draft.description.trim() ||
              !draft.systemPrompt.trim() ||
              positiveInteger(draft.maxTurns) === null ||
              positiveInteger(draft.timeoutSeconds) === null
            }
          >
            {pending ? t.common.loading : t.common.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OptionalNameListField({
  mode,
  text,
  onModeChange,
  onTextChange,
}: {
  mode: OptionalNameListMode;
  text: string;
  onModeChange: (mode: OptionalNameListMode) => void;
  onTextChange: (text: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <Select
        value={mode}
        onValueChange={(value) => onModeChange(value as OptionalNameListMode)}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">
            {t.settings.subagents.listModeAll}
          </SelectItem>
          <SelectItem value="none">
            {t.settings.subagents.listModeNone}
          </SelectItem>
          <SelectItem value="selected">
            {t.settings.subagents.listModeSelected}
          </SelectItem>
        </SelectContent>
      </Select>
      {mode === "selected" && (
        <Input
          value={text}
          placeholder={t.settings.subagents.listNamesPlaceholder}
          onChange={(event) => onTextChange(event.target.value)}
        />
      )}
    </div>
  );
}

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`space-y-1.5 ${className ?? ""}`}>
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}
