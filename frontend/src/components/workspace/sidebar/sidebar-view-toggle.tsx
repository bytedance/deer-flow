import { Calendar, FolderTree, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";

interface SidebarViewToggleProps {
  viewMode: "date" | "project";
  onViewModeChange: (mode: "date" | "project") => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function SidebarViewToggle({
  viewMode,
  onViewModeChange,
  searchQuery,
  onSearchChange,
}: SidebarViewToggleProps) {
  const { t } = useI18n();

  return (
    <div className="flex items-center gap-1.5 px-2 pt-3 pb-1">
      <div className="relative flex-1">
        <Search className="text-muted-foreground/50 absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
        <Input
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={t.sidebar.searchChats}
          className="h-7 pl-7 text-xs"
        />
      </div>
      <ToggleGroup
        type="single"
        value={viewMode}
        onValueChange={(value) => {
          if (value) onViewModeChange(value as "date" | "project");
        }}
        variant="outline"
        size="sm"
      >
        <ToggleGroupItem
          value="date"
          aria-label={t.sidebar.dateView}
          className="h-7 w-7 px-0"
        >
          <Calendar className="size-3.5" />
        </ToggleGroupItem>
        <ToggleGroupItem
          value="project"
          aria-label={t.sidebar.projectView}
          className="h-7 w-7 px-0"
        >
          <FolderTree className="size-3.5" />
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
  );
}
