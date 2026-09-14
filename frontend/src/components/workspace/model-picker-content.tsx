"use client";

import { CheckIcon, StarIcon } from "lucide-react";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
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

export interface ModelPickerContentProps {
  open: boolean;
  models: readonly Model[];
  selectedModelName?: string;
  onModelSelect: (name: string) => void;
}

type PickerMode = "select" | "manage";

function commandValue(name: string): string {
  return JSON.stringify(name);
}

function orderedMatches(projection: ModelChoiceProjection): readonly Model[] {
  return [...projection.favorites, ...projection.others];
}

function preferredCommandValue(
  projection: ModelChoiceProjection,
  selectedModelName: string | undefined,
): string {
  const ordered = orderedMatches(projection);
  const current = ordered.find((model) => model.name === selectedModelName);
  const preferred = current ?? ordered[0];
  return preferred ? commandValue(preferred.name) : "";
}

function ModelDetails({ model }: { model: Model }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <span className="truncate font-medium">{model.display_name}</span>
      <span className="text-muted-foreground truncate text-xs">
        {model.model}
      </span>
      {model.description ? (
        <span className="text-muted-foreground truncate text-xs">
          {model.description}
        </span>
      ) : null}
    </div>
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
  const [mode, setMode] = useState<PickerMode>("select");
  const [query, setQuery] = useState("");
  const initialProjection = projectModelChoices(models, favorites.names, "");
  const [highlightedValue, setHighlightedValue] = useState(() =>
    preferredCommandValue(initialProjection, selectedModelName),
  );
  const selectInputRef = useRef<HTMLInputElement>(null);
  const manageInputRef = useRef<HTMLInputElement>(null);
  const wasOpenRef = useRef(false);

  const projection = useMemo(
    () => projectModelChoices(models, favorites.names, query),
    [favorites.names, models, query],
  );
  const selectModels = useMemo(() => orderedMatches(projection), [projection]);
  const selectValuesKey = JSON.stringify(
    selectModels.map((model) => commandValue(model.name)),
  );

  useLayoutEffect(() => {
    const opening = open && !wasOpenRef.current;
    wasOpenRef.current = open;
    if (!opening) {
      return;
    }

    const resetProjection = projectModelChoices(models, favorites.names, "");
    setMode("select");
    setQuery("");
    setHighlightedValue(
      preferredCommandValue(resetProjection, selectedModelName),
    );
  }, [favorites.names, models, open, selectedModelName]);

  useLayoutEffect(() => {
    if (!open || mode !== "select") {
      return;
    }

    const visibleValues = selectModels.map((model) => commandValue(model.name));
    setHighlightedValue((current) =>
      visibleValues.includes(current) ? current : (visibleValues[0] ?? ""),
    );
  }, [mode, open, selectModels, selectValuesKey]);

  useLayoutEffect(() => {
    if (!open) {
      return;
    }
    const input =
      mode === "select" ? selectInputRef.current : manageInputRef.current;
    input?.focus();
  }, [mode, open]);

  const handleQueryChange = useCallback(
    (nextQuery: string) => {
      const nextProjection = projectModelChoices(
        models,
        favorites.names,
        nextQuery,
      );
      setQuery(nextQuery);
      setHighlightedValue(preferredCommandValue(nextProjection, undefined));
    },
    [favorites.names, models],
  );

  const handleManage = useCallback(() => {
    if (user === null || isLoading) {
      return;
    }
    setMode("manage");
  }, [isLoading, user]);

  const handleDone = useCallback(() => {
    const currentProjection = projectModelChoices(
      models,
      favorites.names,
      query,
    );
    setHighlightedValue(
      preferredCommandValue(currentProjection, selectedModelName),
    );
    setMode("select");
  }, [favorites.names, models, query, selectedModelName]);

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
      favorites.setFavorite(modelName, !favorites.names.includes(modelName));
    },
    [favorites, isLoading, models, query, user],
  );

  const emptyMessage =
    models.length === 0 ? t.modelPicker.noModels : t.modelPicker.noResults;

  return (
    <DialogContent
      className="min-w-0 gap-0 overflow-hidden p-0 sm:max-w-xl"
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        const input =
          mode === "select" ? selectInputRef.current : manageInputRef.current;
        input?.focus();
      }}
    >
      <div className="flex min-h-14 items-center gap-3 border-b px-4 pr-12">
        <DialogTitle className="min-w-0 flex-1 truncate text-base">
          {t.modelPicker.title}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {t.modelPicker.description}
        </DialogDescription>
        {mode === "manage" ? (
          <Button type="button" size="sm" variant="ghost" onClick={handleDone}>
            {t.modelPicker.done}
          </Button>
        ) : user !== null ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={isLoading}
            onClick={handleManage}
          >
            {t.modelPicker.manageFavorites}
          </Button>
        ) : null}
      </div>

      {mode === "select" ? (
        <Command
          label={t.modelPicker.title}
          shouldFilter={false}
          value={highlightedValue}
          onValueChange={setHighlightedValue}
        >
          <CommandInput
            ref={selectInputRef}
            aria-label={t.modelPicker.search}
            placeholder={t.modelPicker.search}
            value={query}
            onValueChange={handleQueryChange}
          />
          <CommandList className="max-h-96">
            {selectModels.length === 0 ? (
              <div className="text-muted-foreground py-8 text-center text-sm">
                {emptyMessage}
              </div>
            ) : (
              <>
                {projection.favorites.length > 0 ? (
                  <CommandGroup heading={t.modelPicker.favorites}>
                    {projection.favorites.map((model) => (
                      <CommandItem
                        key={model.name}
                        value={commandValue(model.name)}
                        onSelect={() => onModelSelect(model.name)}
                      >
                        <ModelDetails model={model} />
                        <StarIcon
                          aria-hidden="true"
                          className="size-4 fill-current"
                        />
                        {model.name === selectedModelName ? (
                          <CheckIcon
                            aria-hidden="true"
                            className="size-4"
                            data-current-model="true"
                          />
                        ) : (
                          <span aria-hidden="true" className="size-4" />
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ) : null}
                {projection.others.length > 0 ? (
                  <CommandGroup heading={t.modelPicker.otherModels}>
                    {projection.others.map((model) => (
                      <CommandItem
                        key={model.name}
                        value={commandValue(model.name)}
                        onSelect={() => onModelSelect(model.name)}
                      >
                        <ModelDetails model={model} />
                        {model.name === selectedModelName ? (
                          <CheckIcon
                            aria-hidden="true"
                            className="size-4"
                            data-current-model="true"
                          />
                        ) : (
                          <span aria-hidden="true" className="size-4" />
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ) : null}
              </>
            )}
          </CommandList>
        </Command>
      ) : (
        <div className="flex min-h-0 min-w-0 flex-col overflow-x-hidden">
          <div className="border-b p-3">
            <Input
              ref={manageInputRef}
              type="search"
              aria-label={t.modelPicker.search}
              placeholder={t.modelPicker.search}
              value={query}
              onChange={(event) => handleQueryChange(event.target.value)}
            />
          </div>
          {projection.matches.length === 0 ? (
            <div className="text-muted-foreground py-8 text-center text-sm">
              {emptyMessage}
            </div>
          ) : (
            <ul className="max-h-96 max-w-full min-w-0 overflow-x-hidden overflow-y-auto p-1">
              {projection.matches.map((model) => {
                const isFavorite = favorites.names.includes(model.name);
                return (
                  <li
                    key={model.name}
                    className="flex min-h-12 max-w-full min-w-0 items-center gap-2 overflow-hidden rounded-sm px-2"
                  >
                    <ModelDetails model={model} />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className={cn("size-11", isFavorite && "text-amber-500")}
                      aria-label={t.modelPicker.favoriteModel(
                        model.display_name,
                        model.name,
                      )}
                      aria-pressed={isFavorite}
                      disabled={
                        user === null || isLoading || !favorites.canEdit
                      }
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => handleFavorite(model.name)}
                    >
                      <StarIcon
                        aria-hidden="true"
                        className={cn("size-5", isFavorite && "fill-current")}
                      />
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
          <p
            role="status"
            className="text-muted-foreground border-t px-4 py-3 text-xs"
          >
            {favorites.persistence === "memory"
              ? t.modelPicker.sessionOnly
              : t.modelPicker.localOnly}
          </p>
        </div>
      )}
    </DialogContent>
  );
}
