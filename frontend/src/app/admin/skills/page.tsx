"use client";

import {
  AlertCircleIcon,
  CheckIcon,
  FactoryIcon,
  Loader2Icon,
  WrenchIcon,
} from "@/components/ui/icons";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { updateSkillTier, batchUpdateSkillTier } from "@/core/skills/admin-api";
import { useSkills } from "@/core/skills/hooks";
import type { Skill, SkillTier } from "@/core/skills/type";

const TIER_OPTIONS: { value: SkillTier; label: string; icon: React.ReactNode }[] = [
  {
    value: "core-industrial",
    label: "Core Industrial",
    icon: <FactoryIcon className="size-4 text-blue-600" />,
  },
  {
    value: "foundation",
    label: "Foundation",
    icon: <WrenchIcon className="size-4 text-gray-500" />,
  },
];

function TierBadge({ tier }: { tier: SkillTier }) {
  const option = TIER_OPTIONS.find((opt) => opt.value === tier);
  return (
    <div className="flex items-center gap-1.5">
      {option?.icon}
      <span className="text-sm font-medium">
        {option?.label ?? tier}
      </span>
    </div>
  );
}

export default function AdminSkillsPage() {
  const { skills, isLoading, error, refetch } = useSkills();
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [filterTier, setFilterTier] = useState<SkillTier | "all">("all");
  const [updating, setUpdating] = useState<string | null>(null);
  const [batchUpdating, setBatchUpdating] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    skillName: string;
    targetTier: SkillTier;
  }>({ open: false, skillName: "", targetTier: "foundation" });

  const filteredSkills = skills.filter(
    (skill) => filterTier === "all" || skill.tier === filterTier,
  );

  const handleTierChangeRequest = (skillName: string, tier: SkillTier) => {
    const skill = skills.find((s) => s.name === skillName);
    if (skill?.tier === "core-industrial" && tier === "foundation") {
      setConfirmDialog({ open: true, skillName, targetTier: tier });
    } else {
      handleTierChange(skillName, tier);
    }
  };

  const handleTierChange = async (skillName: string, tier: SkillTier) => {
    setUpdating(skillName);
    try {
      const result = await updateSkillTier(skillName, tier);
      if (result.success) {
        toast.success(`Updated ${skillName} to ${tier}`);
        refetch();
      } else {
        toast.error(`Failed to update: ${result.message}`);
      }
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setUpdating(null);
      setConfirmDialog({ open: false, skillName: "", targetTier: "foundation" });
    }
  };

  const handleBatchUpdate = async (tier: SkillTier) => {
    if (selectedSkills.size === 0) {
      toast.error("No skills selected");
      return;
    }

    setBatchUpdating(true);
    try {
      const result = await batchUpdateSkillTier(Array.from(selectedSkills), tier);
      if (result.success) {
        toast.success(`Updated ${result.updated} skills to ${tier}`);
        setSelectedSkills(new Set());
        refetch();
      } else {
        toast.error(`Batch update failed: ${result.message}`);
      }
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setBatchUpdating(false);
    }
  };

  const toggleSkillSelection = (skillName: string) => {
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(skillName)) {
        next.delete(skillName);
      } else {
        next.add(skillName);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedSkills.size === filteredSkills.length) {
      setSelectedSkills(new Set());
    } else {
      setSelectedSkills(new Set(filteredSkills.map((s) => s.name)));
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2Icon className="text-muted-foreground size-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <AlertCircleIcon className="text-destructive size-8" />
        <p className="text-destructive">Failed to load skills: {error.message}</p>
      </div>
    );
  }

  const allSelected =
    filteredSkills.length > 0 && selectedSkills.size === filteredSkills.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Skill Management</h1>
        <div className="flex items-center gap-2">
          <Select
            value={filterTier}
            onValueChange={(value) => setFilterTier(value as SkillTier | "all")}
          >
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Filter by tier" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Tiers</SelectItem>
              {TIER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  <div className="flex items-center gap-2">
                    {option.icon}
                    {option.label}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {selectedSkills.size > 0 && (
        <div className="bg-muted/50 flex items-center gap-3 rounded-lg border p-3">
          <span className="text-sm font-medium">
            {selectedSkills.size} selected
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleBatchUpdate("core-industrial")}
              disabled={batchUpdating}
              className="flex items-center gap-1.5"
            >
              {batchUpdating ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                <FactoryIcon className="size-4" />
              )}
              Set Core Industrial
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleBatchUpdate("foundation")}
              disabled={batchUpdating}
              className="flex items-center gap-1.5"
            >
              {batchUpdating ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                <WrenchIcon className="size-4" />
              )}
              Set Foundation
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelectedSkills(new Set())}
              disabled={batchUpdating}
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[50px]">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={undefined}
                  onChange={toggleSelectAll}
                  className="size-4 cursor-pointer"
                  aria-label="Select all"
                />
              </TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-[200px]">Tier</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredSkills.map((skill) => (
              <SkillRow
                key={skill.name}
                skill={skill}
                selected={selectedSkills.has(skill.name)}
                updating={updating === skill.name}
                onToggleSelect={() => toggleSkillSelection(skill.name)}
                onTierChange={(tier) => handleTierChangeRequest(skill.name, tier)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="text-muted-foreground text-sm">
        Showing {filteredSkills.length} of {skills.length} skills
      </div>

      <AlertDialog
        open={confirmDialog.open}
        onOpenChange={(open) => setConfirmDialog({ ...confirmDialog, open })}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认降级工业智能技能</AlertDialogTitle>
            <AlertDialogDescription>
              您即将将技能 <strong>{confirmDialog.skillName}</strong> 从"工业智能"降级为"基础工具"。
              <br /><br />
              降级后，该技能将不再作为平台的核心工业能力展示，且可以被禁用。
              <br /><br />
              此操作会影响平台的工业智能优先策略。确定要继续吗？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => handleTierChange(confirmDialog.skillName, confirmDialog.targetTier)}
            >
              确认降级
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function SkillRow({
  skill,
  selected,
  updating,
  onToggleSelect,
  onTierChange,
}: {
  skill: Skill;
  selected: boolean;
  updating: boolean;
  onToggleSelect: () => void;
  onTierChange: (tier: SkillTier) => void;
}) {
  return (
    <TableRow
      className={selected ? "bg-muted/50" : ""}
      onClick={onToggleSelect}
    >
      <TableCell>
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => {
            e.stopPropagation();
            onToggleSelect();
          }}
          className="size-4 cursor-pointer"
          aria-label={`Select ${skill.name}`}
        />
      </TableCell>
      <TableCell>
        <div>
          <div className="font-medium">{skill.name}</div>
          <div className="text-muted-foreground line-clamp-1 text-xs">
            {skill.description}
          </div>
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground">{skill.category}</TableCell>
      <TableCell>
        {skill.enabled ? (
          <span className="text-success flex items-center gap-1 text-sm">
            <CheckIcon className="size-3" />
            Enabled
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">Disabled</span>
        )}
      </TableCell>
      <TableCell onClick={(e) => e.stopPropagation()}>
        <Select
          value={skill.tier}
          onValueChange={(value) => onTierChange(value as SkillTier)}
          disabled={updating}
        >
          <SelectTrigger className="w-full">
            <SelectValue>
              {updating ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                <TierBadge tier={skill.tier} />
              )}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {TIER_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                <div className="flex items-center gap-2">
                  {option.icon}
                  {option.label}
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
    </TableRow>
  );
}
