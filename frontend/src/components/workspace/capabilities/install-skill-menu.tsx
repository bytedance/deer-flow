"use client";

import {
  ChevronDownIcon,
  FolderGit2Icon,
  LoaderIcon,
  PackageIcon,
  UploadIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";

export function InstallSkillMenu({
  canManage,
  sourceInstallAvailable,
  isUploading,
  onSelectFile,
  onSelectSource,
}: {
  canManage: boolean;
  sourceInstallAvailable: boolean;
  isUploading: boolean;
  onSelectFile: () => void;
  onSelectSource: () => void;
}) {
  const { t } = useI18n();
  const text = t.settings.skills;
  if (!canManage) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline" disabled={isUploading}>
          {isUploading ? (
            <LoaderIcon className="size-4 animate-spin" />
          ) : (
            <PackageIcon className="size-4" />
          )}
          {isUploading ? text.installingArchive : text.installSkill}
          <ChevronDownIcon className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {sourceInstallAvailable && (
          <DropdownMenuItem onSelect={onSelectSource}>
            <FolderGit2Icon />
            {text.installFromSource}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={onSelectFile}>
          <UploadIcon />
          {text.installFromFile}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
