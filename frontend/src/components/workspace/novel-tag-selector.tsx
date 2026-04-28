import { Check, ChevronsUpDown } from "lucide-react";
import { useState, useCallback, useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface NovelTagSelectorProps {
  value?: string;
  onChange: (tag: string | undefined) => void;
  tags: string[];
  disabled?: boolean;
}

export function NovelTagSelector({
  value,
  onChange,
  tags,
  disabled = false,
}: NovelTagSelectorProps) {
  const [open, setOpen] = useState(false);

  const handleSelect = useCallback(
    (tag: string) => {
      onChange(tag === value ? undefined : tag);
      setOpen(false);
    },
    [onChange, value],
  );

  const handleClear = useCallback(() => {
    onChange(undefined);
    setOpen(false);
  }, [onChange]);

  const selectedTag = useMemo(
    () => tags.find((tag) => tag === value),
    [tags, value],
  );

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between"
          disabled={disabled}
        >
          {selectedTag || "选择进行中的小说（可选）"}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-full p-0" align="start">
        <Command>
          <CommandInput placeholder="搜索小说..." />
          <CommandList>
            <CommandEmpty>没有找到小说</CommandEmpty>
            <CommandGroup>
              {value && (
                <CommandItem onSelect={handleClear}>
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      !selectedTag ? "opacity-100" : "opacity-0",
                    )}
                  />
                  清空选择
                </CommandItem>
              )}
              {tags.map((tag) => (
                <CommandItem
                  key={tag}
                  value={tag}
                  onSelect={() => handleSelect(tag)}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === tag ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {tag}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
