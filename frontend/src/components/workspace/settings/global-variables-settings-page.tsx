"use client";

import {
  LockIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useId, useState } from "react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useGlobalVariables } from "@/core/global-variables/hooks";
import type {
  GlobalVariable,
  VariableFormData,
  VariableScope,
} from "@/core/global-variables/types";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

type VariableFormState = {
  key: string;
  value: string;
  description: string;
  llm_editable: boolean;
};

const DEFAULT_FORM_STATE: VariableFormState = {
  key: "",
  value: "",
  description: "",
  llm_editable: true,
};

function VariableFormDialog({
  open,
  onOpenChange,
  existingVar,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existingVar: GlobalVariable | null;
  onSave: (data: VariableFormData) => void;
}) {
  const { t } = useI18n();
  const keyId = useId();
  const valueId = useId();
  const descId = useId();

  const [form, setForm] = useState<VariableFormState>(
    existingVar
      ? {
          key: existingVar.key,
          value: existingVar.value,
          description: existingVar.description ?? "",
          llm_editable: existingVar.llm_editable ?? true,
        }
      : DEFAULT_FORM_STATE,
  );

  const isSystem = existingVar?.is_system ?? false;
  const title = isSystem
    ? t.globalVariables.systemLabel
    : existingVar
      ? t.globalVariables.editVariableTitle
      : t.globalVariables.addVariableTitle;

  function handleSave() {
    if (!form.key.trim()) {
      toast.error(t.globalVariables.validationKey);
      return;
    }
    if (!form.value.trim()) {
      toast.error(t.globalVariables.validationValue);
      return;
    }
    onSave({
      key: form.key.trim(),
      value: form.value.trim(),
      description: form.description.trim(),
      llm_editable: form.llm_editable,
      is_system: false,
    });
    setForm(DEFAULT_FORM_STATE);
    onOpenChange(false);
  }

  function handleClose() {
    setForm(DEFAULT_FORM_STATE);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {isSystem && (
            <DialogDescription>
              {t.globalVariables.systemHint}
            </DialogDescription>
          )}
        </DialogHeader>
        {isSystem ? (
          <div className="bg-muted rounded-lg border p-4 text-sm">
            <div className="mb-2 font-medium">{existingVar?.key}</div>
            <div className="text-muted-foreground">
              {existingVar?.description}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor={keyId} className="block text-sm font-medium">
                {t.globalVariables.keyLabel}
              </label>
              <Input
                id={keyId}
                value={form.key}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    key: event.target.value,
                  }))
                }
                placeholder={t.globalVariables.keyPlaceholder}
                disabled={!!existingVar}
              />
            </div>

            <div className="space-y-2">
              <label htmlFor={valueId} className="block text-sm font-medium">
                {t.globalVariables.valueLabel}
              </label>
              <Input
                id={valueId}
                value={form.value}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    value: event.target.value,
                  }))
                }
                placeholder={t.globalVariables.valuePlaceholder}
              />
            </div>

            <div className="space-y-2">
              <label htmlFor={descId} className="block text-sm font-medium">
                {t.globalVariables.descriptionLabel}
              </label>
              <Input
                id={descId}
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
                placeholder={t.globalVariables.descriptionPlaceholder}
              />
            </div>

            <div className="flex items-center justify-between space-x-2 rounded-lg border p-3">
              <div className="space-y-0.5">
                <span className="text-sm font-medium">
                  {t.globalVariables.llmEditableLabel}
                </span>
                <p className="text-muted-foreground text-xs">
                  {t.globalVariables.llmEditableHint}
                </p>
              </div>
              <Switch
                checked={form.llm_editable}
                onCheckedChange={(checked) =>
                  setForm((current) => ({
                    ...current,
                    llm_editable: checked,
                  }))
                }
              />
            </div>
          </div>
        )}
        {!isSystem && (
          <DialogFooter>
            <Button variant="outline" onClick={handleClose}>
              {t.common.cancel}
            </Button>
            <Button onClick={() => void handleSave()}>
              {t.globalVariables.save}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DeleteConfirmDialog({
  variable,
  onConfirm,
  onCancel,
}: {
  variable: GlobalVariable | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  if (!variable) return null;
  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.globalVariables.deleteConfirmTitle}</DialogTitle>
          <DialogDescription>
            {t.globalVariables.deleteConfirmDescription}
          </DialogDescription>
        </DialogHeader>
        <div className="bg-muted rounded-md border p-3 text-sm">
          <span className="font-mono font-medium">{variable.key}</span>
          <span className="text-muted-foreground ml-2">= {variable.value}</span>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t.common.cancel}
          </Button>
          <Button variant="destructive" onClick={() => void onConfirm()}>
            {t.common.delete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function VariablesTable({
  variables,
  onEdit,
  onDelete,
}: {
  variables: GlobalVariable[];
  onEdit: (variable: GlobalVariable) => void;
  onDelete: (variable: GlobalVariable) => void;
}) {
  const { t } = useI18n();
  if (variables.length === 0) {
    return (
      <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
        {t.globalVariables.noVariables}
      </div>
    );
  }
  return (
    <div className="rounded-lg border">
      <div className="bg-muted/50 grid grid-cols-12 items-center gap-2 border-b px-4 py-2 text-sm font-medium">
        <div className="col-span-3">{t.globalVariables.table.key}</div>
        <div className="col-span-3">{t.globalVariables.table.value}</div>
        <div className="col-span-3">{t.globalVariables.table.description}</div>
        <div className="col-span-2">{t.globalVariables.table.llmEditable}</div>
        <div className="col-span-1 text-right">
          {t.globalVariables.table.operations}
        </div>
      </div>
      {variables.map((variable) => {
        const isSystem = variable.is_system ?? false;
        return (
          <div
            key={variable.key}
            className={`grid grid-cols-12 items-center gap-2 border-b px-4 py-3 text-sm last:border-b-0 ${
              isSystem ? "bg-muted/30" : ""
            }`}
          >
            <div className="col-span-3">
              <div className="flex items-center gap-2">
                <code className="text-xs">{variable.key}</code>
                {isSystem && (
                  <Badge
                    variant="secondary"
                    className="flex-shrink-0 gap-1 px-1.5 py-0 text-[10px]"
                  >
                    <LockIcon className="h-3 w-3" />
                    {t.globalVariables.systemLabel}
                  </Badge>
                )}
              </div>
            </div>
            <div className="col-span-3 truncate font-mono text-xs">
              {variable.value}
            </div>
            <div className="text-muted-foreground col-span-3 truncate text-xs">
              {variable.description || "-"}
            </div>
            <div className="col-span-2">
              <Badge
                variant={variable.llm_editable ? "default" : "outline"}
                className="gap-1 px-1.5 py-0 text-[10px]"
              >
                {variable.llm_editable ? (
                  <>{t.globalVariables.llmAllowed}</>
                ) : (
                  <>
                    <XIcon className="h-3 w-3" />
                    {t.globalVariables.llmForbidden}
                  </>
                )}
              </Badge>
            </div>
            <div className="col-span-1 flex justify-end gap-1">
              {isSystem ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 cursor-not-allowed opacity-50"
                  disabled
                  aria-label={t.globalVariables.systemHint}
                >
                  <LockIcon className="h-3.5 w-3.5" />
                </Button>
              ) : (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={() => onEdit(variable)}
                    aria-label={t.common.edit}
                  >
                    <PencilIcon className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive h-7 w-7 shrink-0"
                    onClick={() => onDelete(variable)}
                    aria-label={t.common.delete}
                  >
                    <Trash2Icon className="h-3.5 w-3.5" />
                  </Button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function GlobalVariablesSettingsPage() {
  const { t } = useI18n();
  const [scope, setScope] = useState<VariableScope>("project");
  const [threadId, setThreadId] = useState("");
  const [editingVar, setEditingVar] = useState<GlobalVariable | null>(null);
  const [deletingVar, setDeletingVar] = useState<GlobalVariable | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const {
    variables,
    isLoading,
    error,
    addVariable,
    updateVariable,
    deleteVariable,
    reload,
  } = useGlobalVariables(scope, scope === "thread" ? threadId : undefined);

  function handleAdd() {
    setEditingVar(null);
    setFormOpen(true);
  }

  function handleEdit(variable: GlobalVariable) {
    if (variable.is_system) return;
    setEditingVar(variable);
    setFormOpen(true);
  }

  function handleDelete(variable: GlobalVariable) {
    if (variable.is_system) return;
    setDeletingVar(variable);
  }

  async function handleSave(data: VariableFormData) {
    try {
      if (editingVar) {
        await updateVariable(editingVar.key, data);
      } else {
        await addVariable(data);
      }
    } catch {
      // Error already shown by hook
    }
  }

  async function handleConfirmDelete() {
    if (deletingVar) {
      try {
        await deleteVariable(deletingVar.key);
      } catch {
        // Error already shown by hook
      } finally {
        setDeletingVar(null);
      }
    }
  }

  return (
    <SettingsSection
      title={t.globalVariables.title}
      description={t.globalVariables.description}
    >
      <div className="space-y-4">
        {/* Scope Selector */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <span className="block flex-shrink-0 pt-2 text-sm font-medium sm:w-20 sm:pt-0">
            {t.globalVariables.scopeLabel}
          </span>
          <Select
            value={scope}
            onValueChange={(value) => setScope(value as VariableScope)}
          >
            <SelectTrigger className="w-full sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="project">
                {t.globalVariables.scopeProject}
              </SelectItem>
              <SelectItem value="thread">
                {t.globalVariables.scopeThread}
              </SelectItem>
            </SelectContent>
          </Select>

          {scope === "thread" && (
            <Input
              value={threadId}
              onChange={(event) => setThreadId(event.target.value)}
              placeholder={t.globalVariables.searchThreadPlaceholder}
              className="flex-1"
            />
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={() => void reload()}
            className="flex-shrink-0"
          >
            {t.common.loading}
          </Button>
        </div>

        {/* Loading / Error / Content */}
        {isLoading ? (
          <div className="text-muted-foreground text-center text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div className="text-destructive text-center text-sm">
            {error.message}
          </div>
        ) : (
          <>
            {/* Table */}
            <VariablesTable
              variables={variables}
              onEdit={handleEdit}
              onDelete={handleDelete}
            />

            {/* Add Button */}
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={handleAdd}>
                <PlusIcon className="mr-2 h-4 w-4" />
                {t.globalVariables.addVariable}
              </Button>
            </div>
          </>
        )}
      </div>

      {/* Variable Form Dialog */}
      <VariableFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        existingVar={editingVar}
        onSave={(data) => void handleSave(data)}
      />

      {/* Delete Confirmation Dialog */}
      <DeleteConfirmDialog
        variable={deletingVar}
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setDeletingVar(null)}
      />
    </SettingsSection>
  );
}
