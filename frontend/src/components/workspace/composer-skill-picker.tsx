"use client";

import { BlocksIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import type { Skill } from "@/core/skills";

import { getSelectableSkills } from "./input-box-helpers";
import { Tooltip } from "./tooltip";

type ComposerSkillPickerProps = {
  skills: Skill[];
  disabled?: boolean;
  onPick: (skill: Skill) => void;
};

/**
 * Composer-owned skill picker (#4062 MVP): a toolbar button opening a
 * searchable list of enabled skills. Selection is handed to the composer's
 * existing `applySkillSuggestion` path, so insertion, the active-skill chip,
 * and focus handling have exactly one implementation.
 */
export function ComposerSkillPicker({
  skills,
  disabled,
  onPick,
}: ComposerSkillPickerProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const selectableSkills = useMemo(() => getSelectableSkills(skills), [skills]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip content={t.inputBox.skillPickerLabel}>
        <DialogTrigger asChild>
          <PromptInputButton
            aria-label={t.inputBox.skillPickerLabel}
            disabled={(disabled ?? false) || selectableSkills.length === 0}
          >
            <BlocksIcon className="size-3" />
          </PromptInputButton>
        </DialogTrigger>
      </Tooltip>
      <DialogContent className="overflow-hidden p-0 sm:max-w-[400px]">
        <DialogTitle className="sr-only">
          {t.inputBox.skillPickerLabel}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {t.inputBox.skillPickerDescription}
        </DialogDescription>
        <Command>
          <CommandInput placeholder={t.inputBox.skillPickerSearch} />
          <CommandList>
            <CommandEmpty>{t.inputBox.skillPickerEmpty}</CommandEmpty>
            <CommandGroup heading={t.inputBox.skillPickerGroup}>
              {selectableSkills.map((skill) => (
                <CommandItem
                  key={skill.name}
                  value={`${skill.name} ${skill.description}`}
                  onSelect={() => {
                    setOpen(false);
                    onPick(skill);
                  }}
                >
                  <div className="min-w-0">
                    <div className="font-mono text-sm">/{skill.name}</div>
                    <div className="text-muted-foreground truncate text-xs">
                      {skill.description}
                    </div>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
