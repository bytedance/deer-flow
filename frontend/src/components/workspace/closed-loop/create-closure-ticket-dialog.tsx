"use client";

import { PlusIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { Textarea } from "@/components/ui/textarea";
import { useCreateClosureTicket } from "@/core/closed-loop";
import type {
  ClosurePriority,
  CreateClosureTicketRequest,
} from "@/core/closed-loop";

const PRIORITY_OPTIONS: { value: ClosurePriority; label: string }[] = [
  { value: "urgent", label: "紧急（4h）" },
  { value: "important", label: "重要（72h）" },
  { value: "normal", label: "一般（7d）" },
  { value: "observe", label: "观察（30d）" },
];

interface CreateClosureTicketDialogProps {
  onCreated?: (ticketId: string) => void;
}

export function CreateClosureTicketDialog({
  onCreated,
}: CreateClosureTicketDialogProps) {
  const [open, setOpen] = useState(false);
  const create = useCreateClosureTicket();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [priority, setPriority] = useState<ClosurePriority>("normal");
  const [severity, setSeverity] = useState("");

  function reset() {
    setTitle("");
    setDescription("");
    setDeviceId("");
    setDeviceName("");
    setPriority("normal");
    setSeverity("");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) {
      toast.error("请填写标题");
      return;
    }
    const request: CreateClosureTicketRequest = {
      title: trimmed,
      source_type: "manual",
      priority,
    };
    if (description.trim()) request.description = description.trim();
    if (deviceId.trim()) request.device_id = deviceId.trim();
    if (deviceName.trim()) request.device_name = deviceName.trim();
    if (severity.trim()) request.severity = severity.trim();

    try {
      const ticket = await create.mutateAsync(request);
      toast.success("整改单已创建");
      reset();
      setOpen(false);
      onCreated?.(ticket.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <Button
        type="button"
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-1.5"
      >
        <PlusIcon className="size-4" />
        新建整改单
      </Button>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建整改单</DialogTitle>
          <DialogDescription>
            手工登记一条闭环单，来源标记为 manual。受理人可在派单时指定。
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="grid gap-4"
          aria-label="新建整改单表单"
        >
          <Field label="标题" required>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：1#磨煤机出口温度持续偏低"
              maxLength={255}
              required
              autoFocus
            />
          </Field>
          <Field label="描述">
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="问题现象、影响范围、初步判断…"
              rows={4}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="设备编号">
              <Input
                value={deviceId}
                onChange={(e) => setDeviceId(e.target.value)}
                placeholder="MILL-1"
              />
            </Field>
            <Field label="设备名称">
              <Input
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                placeholder="1#磨煤机"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="优先级">
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as ClosurePriority)}
                className="bg-background border-input focus-visible:border-ring focus-visible:ring-ring/50 h-9 rounded-md border px-3 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
              >
                {PRIORITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="严重等级">
              <Input
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                placeholder="critical / high / medium / low"
              />
            </Field>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={create.isPending}
            >
              取消
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-muted-foreground text-xs">
        {label}
        {required && <span className="text-destructive ml-0.5">*</span>}
      </span>
      {children}
    </label>
  );
}
