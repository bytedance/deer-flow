"use client";

import { ArrowLeftIcon, CheckIcon, Loader2Icon } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useToolGroups, useUpdateAgent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useSkills } from "@/core/skills/hooks";
import { cn } from "@/lib/utils";

export default function EditAgentPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { agent_name } = useParams<{ agent_name: string }>();

  const { agent, isLoading: isLoadingAgent } = useAgent(agent_name);
  const { models } = useModels();
  const { skills } = useSkills();
  const { toolGroups } = useToolGroups();
  const updateAgent = useUpdateAgent();

  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string>("");
  const [selectedToolGroups, setSelectedToolGroups] = useState<string[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [soul, setSoul] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [toolGroupsDialogOpen, setToolGroupsDialogOpen] = useState(false);
  const [skillsDialogOpen, setSkillsDialogOpen] = useState(false);

  // Initialize form with agent data
  useEffect(() => {
    if (agent) {
      setDescription(agent.description ?? "");
      setModel(agent.model ?? "");
      setSelectedToolGroups(agent.tool_groups ?? []);
      setSelectedSkills(agent.skills ?? []);
      setSoul(agent.soul ?? "");
    }
  }, [agent]);

  const handleSave = useCallback(async () => {
    if (!agent_name || isSaving) return;

    setIsSaving(true);
    try {
      await updateAgent.mutateAsync({
        name: agent_name,
        request: {
          description,
          model: model || null,
          tool_groups: selectedToolGroups.length > 0 ? selectedToolGroups : [],
          skills: selectedSkills.length > 0 ? selectedSkills : [],
          soul,
        },
      });
      toast.success(t.agents.updateSuccess);
      router.push("/workspace/agents");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.agents.updateError);
    } finally {
      setIsSaving(false);
    }
  }, [
    agent_name,
    description,
    model,
    selectedToolGroups,
    selectedSkills,
    soul,
    isSaving,
    updateAgent,
    t.agents.updateSuccess,
    t.agents.updateError,
    router,
  ]);

  const toggleToolGroup = (group: string) => {
    setSelectedToolGroups((prev) =>
      prev.includes(group) ? prev.filter((g) => g !== group) : [...prev, group],
    );
  };

  const toggleSkill = (skill: string) => {
    setSelectedSkills((prev) =>
      prev.includes(skill) ? prev.filter((s) => s !== skill) : [...prev, skill],
    );
  };

  const enabledSkills = skills.filter((s) => s.enabled);

  if (isLoadingAgent) {
    return (
      <div className="flex size-full items-center justify-center">
        <Loader2Icon className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground text-sm">Agent not found</p>
        <Button
          variant="outline"
          onClick={() => router.push("/workspace/agents")}
        >
          {t.agents.backToGallery}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex size-full flex-col">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push("/workspace/agents")}
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </Button>
          <h1 className="text-sm font-semibold">{t.agents.editPageTitle}</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => router.push("/workspace/agents")}
          >
            {t.common.cancel}
          </Button>
          <Button onClick={() => void handleSave()} disabled={isSaving}>
            {isSaving ? (
              <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" />
            ) : null}
            {isSaving ? t.common.loading : t.common.save}
          </Button>
        </div>
      </header>

      {/* Form */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-6 p-6">
          {/* Name (read-only) */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t.agents.nameLabel}</label>
            <Input value={agent_name} disabled />
          </div>

          {/* Description */}
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t.agents.descriptionLabel}
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t.agents.descriptionPlaceholder}
            />
          </div>

          {/* Model */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t.agents.modelLabel}</label>
            <Select
              value={model}
              onValueChange={(value) =>
                setModel(value === "__default__" ? "" : value)
              }
            >
              <SelectTrigger>
                <SelectValue placeholder={t.agents.modelNone} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">
                  {t.agents.modelNone}
                </SelectItem>
                {models.map((m) => (
                  <SelectItem key={m.name} value={m.name}>
                    {m.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Tool Groups */}
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t.agents.toolGroupsLabel}
            </label>
            <div className="flex flex-wrap items-center gap-2">
              {selectedToolGroups.map((group) => (
                <Badge key={group} variant="secondary" className="gap-1">
                  {group}
                  <button
                    type="button"
                    onClick={() => toggleToolGroup(group)}
                    className="ring-offset-background focus:ring-ring ml-1 rounded-full outline-none focus:ring-2 focus:ring-offset-2"
                  >
                    <span className="sr-only">Remove</span>
                    <span className="text-xs">×</span>
                  </button>
                </Badge>
              ))}
              <Dialog
                open={toolGroupsDialogOpen}
                onOpenChange={setToolGroupsDialogOpen}
              >
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" className="h-7">
                    +
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t.agents.toolGroupsLabel}</DialogTitle>
                  </DialogHeader>
                  <div className="max-h-60 space-y-2 overflow-y-auto">
                    {toolGroups.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        No tool groups available
                      </p>
                    ) : (
                      toolGroups.map((group) => (
                        <label
                          key={group.name}
                          className={cn(
                            "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md border p-3 text-sm transition-colors",
                            selectedToolGroups.includes(group.name) &&
                              "border-primary bg-accent",
                          )}
                        >
                          <input
                            type="checkbox"
                            className="sr-only"
                            checked={selectedToolGroups.includes(group.name)}
                            onChange={() => toggleToolGroup(group.name)}
                          />
                          <div
                            className={cn(
                              "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border",
                              selectedToolGroups.includes(group.name)
                                ? "bg-primary text-primary-foreground"
                                : "border-input",
                            )}
                          >
                            {selectedToolGroups.includes(group.name) && (
                              <CheckIcon className="h-3 w-3" />
                            )}
                          </div>
                          <span>{group.name}</span>
                        </label>
                      ))
                    )}
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          </div>

          {/* Skills */}
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t.agents.skillsLabel}
            </label>
            <div className="flex flex-wrap items-center gap-2">
              {selectedSkills.map((skill) => (
                <Badge key={skill} variant="secondary" className="gap-1">
                  {skill}
                  <button
                    type="button"
                    onClick={() => toggleSkill(skill)}
                    className="ring-offset-background focus:ring-ring ml-1 rounded-full outline-none focus:ring-2 focus:ring-offset-2"
                  >
                    <span className="sr-only">Remove</span>
                    <span className="text-xs">×</span>
                  </button>
                </Badge>
              ))}
              <Dialog
                open={skillsDialogOpen}
                onOpenChange={setSkillsDialogOpen}
              >
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" className="h-7">
                    +
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t.agents.skillsLabel}</DialogTitle>
                  </DialogHeader>
                  <div className="max-h-60 space-y-2 overflow-y-auto">
                    {enabledSkills.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        No skills available
                      </p>
                    ) : (
                      enabledSkills.map((skill) => (
                        <label
                          key={skill.name}
                          className={cn(
                            "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md border p-3 text-sm transition-colors",
                            selectedSkills.includes(skill.name) &&
                              "border-primary bg-accent",
                          )}
                        >
                          <input
                            type="checkbox"
                            className="sr-only"
                            checked={selectedSkills.includes(skill.name)}
                            onChange={() => toggleSkill(skill.name)}
                          />
                          <div
                            className={cn(
                              "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border",
                              selectedSkills.includes(skill.name)
                                ? "bg-primary text-primary-foreground"
                                : "border-input",
                            )}
                          >
                            {selectedSkills.includes(skill.name) && (
                              <CheckIcon className="h-3 w-3" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="font-medium">{skill.name}</div>
                            {skill.description && (
                              <div className="text-muted-foreground truncate text-xs">
                                {skill.description}
                              </div>
                            )}
                          </div>
                        </label>
                      ))
                    )}
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          </div>

          {/* SOUL.md */}
          <div className="space-y-2">
            <label className="text-sm font-medium">{t.agents.soulLabel}</label>
            <Textarea
              value={soul}
              onChange={(e) => setSoul(e.target.value)}
              placeholder={t.agents.soulPlaceholder}
              className="min-h-[300px] font-mono text-sm"
            />
          </div>
        </div>
      </main>
    </div>
  );
}
