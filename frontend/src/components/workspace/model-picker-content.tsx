"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { CheckIcon, SearchIcon, StarIcon } from "lucide-react";
import {
  type KeyboardEvent,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  projectModelChoices,
  type ModelChoiceProjection,
} from "@/core/models/favorites";
import { type Model } from "@/core/models/types";
import { useModelFavorites } from "@/core/models/use-model-favorites";
import { cn } from "@/lib/utils";

export const ModelPicker = PopoverPrimitive.Root;
export const ModelPickerTrigger = PopoverPrimitive.Trigger;

export interface ModelPickerContentProps {
  open: boolean;
  models: readonly Model[];
  selectedModelName?: string;
  onModelSelect: (name: string) => void;
}

function orderedMatches(projection: ModelChoiceProjection): readonly Model[] {
  return [...projection.favorites, ...projection.others];
}

function ModelDetails({ model }: { model: Model }) {
  return (
    <span className="flex min-w-0 flex-1 flex-col text-left">
      <span className="truncate font-medium">{model.display_name}</span>
      <span className="text-muted-foreground truncate text-xs">
        {model.model}
      </span>
      {model.description ? (
        <span className="text-muted-foreground truncate text-xs">
          {model.description}
        </span>
      ) : null}
    </span>
  );
}

export function ModelPickerContent({
  open,
  models,
  selectedModelName,
  onModelSelect,
}: ModelPickerContentProps) {
  const { t } = useI18n();
  const { user, isLoading } = useAuth();
  const favorites = useModelFavorites(user?.id ?? null);
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const modelButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const favoriteButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const pendingFavoriteFocusRef = useRef<string | null>(null);
  const wasOpenRef = useRef(false);

  const projection = useMemo(
    () => projectModelChoices(models, favorites.names, query),
    [favorites.names, models, query],
  );
  const visibleModels = useMemo(() => orderedMatches(projection), [projection]);

  useLayoutEffect(() => {
    const opening = open && !wasOpenRef.current;
    wasOpenRef.current = open;
    if (opening) {
      setQuery("");
    }
  }, [open]);

  useLayoutEffect(() => {
    if (open) {
      searchInputRef.current?.focus();
    }
  }, [open]);

  useLayoutEffect(() => {
    const modelName = pendingFavoriteFocusRef.current;
    if (!open || modelName === null) {
      return;
    }
    const button = favoriteButtonRefs.current.get(modelName);
    if (button) {
      button.focus();
      pendingFavoriteFocusRef.current = null;
    }
  }, [favorites.names, open]);

  const handleFavorite = useCallback(
    (modelName: string) => {
      if (user === null || isLoading || !favorites.canEdit) {
        return;
      }
      const stillVisible = projectModelChoices(
        models,
        favorites.names,
        query,
      ).matches.some((model) => model.name === modelName);
      if (!stillVisible) {
        return;
      }
      pendingFavoriteFocusRef.current = modelName;
      favorites.setFavorite(modelName, !favorites.names.includes(modelName));
    },
    [favorites, isLoading, models, query, user],
  );

  const focusModel = useCallback(
    (currentName: string | null, direction: 1 | -1) => {
      if (visibleModels.length === 0) {
        return;
      }
      const currentIndex = currentName
        ? visibleModels.findIndex((model) => model.name === currentName)
        : direction === 1
          ? -1
          : 0;
      const nextIndex =
        (currentIndex + direction + visibleModels.length) %
        visibleModels.length;
      modelButtonRefs.current.get(visibleModels[nextIndex]!.name)?.focus();
    },
    [visibleModels],
  );

  const handleSearchKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
        return;
      }
      event.preventDefault();
      focusModel(null, event.key === "ArrowDown" ? 1 : -1);
    },
    [focusModel],
  );

  const handleModelKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, modelName: string) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
        return;
      }
      event.preventDefault();
      focusModel(modelName, event.key === "ArrowDown" ? 1 : -1);
    },
    [focusModel],
  );

  const emptyMessage =
    models.length === 0 ? t.modelPicker.noModels : t.modelPicker.noResults;

  const renderGroup = (heading: string, groupModels: readonly Model[]) => {
    if (groupModels.length === 0) {
      return null;
    }
    return (
      <section role="group" aria-label={heading}>
        <h3 className="text-muted-foreground px-3 pt-2 pb-1 text-xs font-medium">
          {heading}
        </h3>
        <ul className="px-1 pb-1">
          {groupModels.map((model) => {
            const isFavorite = favorites.names.includes(model.name);
            const isCurrent = model.name === selectedModelName;
            return (
              <li
                key={model.name}
                className="hover:bg-accent focus-within:bg-accent flex min-h-11 min-w-0 items-stretch rounded-md"
              >
                <button
                  ref={(node) => {
                    if (node) {
                      modelButtonRefs.current.set(model.name, node);
                    } else {
                      modelButtonRefs.current.delete(model.name);
                    }
                  }}
                  type="button"
                  className="focus-visible:ring-ring flex min-w-0 flex-1 items-center gap-2 rounded-l-md px-3 py-2 outline-none focus-visible:ring-2"
                  aria-label={`${model.display_name} (${model.name})`}
                  aria-current={isCurrent ? "true" : undefined}
                  data-model-picker-option="true"
                  data-current-model={isCurrent ? "true" : undefined}
                  onClick={() => onModelSelect(model.name)}
                  onKeyDown={(event) => handleModelKeyDown(event, model.name)}
                >
                  <ModelDetails model={model} />
                  {isCurrent ? (
                    <CheckIcon aria-hidden="true" className="size-4 shrink-0" />
                  ) : null}
                </button>
                {user !== null ? (
                  <Button
                    ref={(node) => {
                      if (node) {
                        favoriteButtonRefs.current.set(model.name, node);
                      } else {
                        favoriteButtonRefs.current.delete(model.name);
                      }
                    }}
                    type="button"
                    variant="ghost"
                    size="icon"
                    className={cn(
                      "size-11 shrink-0 rounded-l-none",
                      isFavorite && "text-amber-500",
                    )}
                    aria-label={t.modelPicker.favoriteModel(
                      model.display_name,
                      model.name,
                    )}
                    aria-pressed={isFavorite}
                    disabled={isLoading || !favorites.canEdit}
                    onClick={() => handleFavorite(model.name)}
                  >
                    <StarIcon
                      aria-hidden="true"
                      className={cn("size-5", isFavorite && "fill-current")}
                    />
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>
    );
  };

  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        role="dialog"
        aria-label={t.modelPicker.title}
        side="top"
        align="end"
        sideOffset={8}
        collisionPadding={8}
        className="bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 z-50 flex max-h-[min(28rem,var(--radix-popover-content-available-height))] w-[22rem] max-w-[calc(100vw-1rem)] origin-(--radix-popover-content-transform-origin) flex-col overflow-hidden rounded-xl border shadow-lg outline-none"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchInputRef.current?.focus();
        }}
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-3">
          <SearchIcon
            aria-hidden="true"
            className="text-muted-foreground size-4 shrink-0"
          />
          <Input
            ref={searchInputRef}
            type="search"
            aria-label={t.modelPicker.search}
            placeholder={t.modelPicker.search}
            value={query}
            className="h-11 border-0 px-0 shadow-none focus-visible:ring-0"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleSearchKeyDown}
          />
        </div>
        <div className="min-h-0 overflow-x-hidden overflow-y-auto py-1">
          {visibleModels.length === 0 ? (
            <div className="text-muted-foreground py-8 text-center text-sm">
              {emptyMessage}
            </div>
          ) : (
            <>
              {renderGroup(t.modelPicker.favorites, projection.favorites)}
              {renderGroup(t.modelPicker.otherModels, projection.others)}
            </>
          )}
        </div>
        {favorites.persistence === "memory" && user !== null ? (
          <p
            role="status"
            className="text-muted-foreground shrink-0 border-t px-3 py-2 text-xs"
          >
            {t.modelPicker.sessionOnly}
          </p>
        ) : null}
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  );
}
