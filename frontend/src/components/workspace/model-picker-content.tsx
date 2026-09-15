"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { CheckIcon, StarIcon } from "lucide-react";
import {
  type KeyboardEvent,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";

import { Button } from "@/components/ui/button";
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

type FocusedControl = {
  modelName: string;
  kind: "model" | "favorite";
};

function orderedModels(projection: ModelChoiceProjection): readonly Model[] {
  return [...projection.favorites, ...projection.others];
}

function ModelDetails({ model }: { model: Model }) {
  return (
    <span className="flex min-w-0 flex-1 flex-col text-left">
      <span className="truncate text-xs">{model.display_name}</span>
      <span className="text-muted-foreground truncate text-[10px] leading-4">
        {model.model}
      </span>
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
  const modelButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const favoriteButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const pendingFavoriteFocusRef = useRef<string | null>(null);
  const lastFocusedControlRef = useRef<FocusedControl | null>(null);
  const wasOpenRef = useRef(false);

  const projection = useMemo(
    () => projectModelChoices(models, favorites.names),
    [favorites.names, models],
  );
  const visibleModels = useMemo(() => orderedModels(projection), [projection]);

  const focusInitialModel = useCallback(() => {
    const preferredModel =
      visibleModels.find((model) => model.name === selectedModelName) ??
      visibleModels[0];
    if (preferredModel) {
      modelButtonRefs.current.get(preferredModel.name)?.focus();
    }
  }, [selectedModelName, visibleModels]);

  useLayoutEffect(() => {
    const opening = open && !wasOpenRef.current;
    wasOpenRef.current = open;
    if (opening) {
      focusInitialModel();
    }
  }, [focusInitialModel, open]);

  useLayoutEffect(() => {
    if (!open) {
      lastFocusedControlRef.current = null;
      return;
    }

    const pendingFavorite = pendingFavoriteFocusRef.current;
    if (pendingFavorite !== null) {
      const button = favoriteButtonRefs.current.get(pendingFavorite);
      if (button) {
        button.focus();
        pendingFavoriteFocusRef.current = null;
      }
      return;
    }

    const previousControl = lastFocusedControlRef.current;
    if (previousControl === null || document.activeElement !== document.body) {
      return;
    }
    const button =
      previousControl.kind === "model"
        ? modelButtonRefs.current.get(previousControl.modelName)
        : favoriteButtonRefs.current.get(previousControl.modelName);
    if (button) {
      button.focus();
    }
  }, [favorites.names, open]);

  const handleFavorite = useCallback(
    (modelName: string) => {
      if (user === null || isLoading || !favorites.canEdit) {
        return;
      }
      const stillVisible = models.some((model) => model.name === modelName);
      if (!stillVisible) {
        return;
      }
      pendingFavoriteFocusRef.current = modelName;
      favorites.setFavorite(modelName, !favorites.names.includes(modelName));
    },
    [favorites, isLoading, models, user],
  );

  const focusModel = useCallback(
    (currentName: string, direction: 1 | -1) => {
      if (visibleModels.length === 0) {
        return;
      }
      const currentIndex = visibleModels.findIndex(
        (model) => model.name === currentName,
      );
      const nextIndex =
        (Math.max(currentIndex, 0) + direction + visibleModels.length) %
        visibleModels.length;
      modelButtonRefs.current.get(visibleModels[nextIndex]!.name)?.focus();
    },
    [visibleModels],
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

  const renderGroup = (heading: string, groupModels: readonly Model[]) => {
    if (groupModels.length === 0) {
      return null;
    }
    return (
      <section role="group" aria-label={heading}>
        <h3 className="text-muted-foreground px-2 py-1.5 text-xs font-medium">
          {heading}
        </h3>
        <ul className="px-1 pb-0.5">
          {groupModels.map((model) => {
            const isFavorite = favorites.names.includes(model.name);
            const isCurrent = model.name === selectedModelName;
            return (
              <li
                key={model.name}
                className="hover:bg-accent focus-within:bg-accent flex min-h-9 min-w-0 items-stretch rounded-sm"
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
                  className="focus-visible:ring-ring flex min-w-0 flex-1 items-center gap-2 rounded-l-sm px-2 py-1.5 outline-none focus-visible:ring-2"
                  aria-label={`${model.display_name} (${model.name})`}
                  aria-current={isCurrent ? "true" : undefined}
                  data-model-picker-option="true"
                  data-current-model={isCurrent ? "true" : undefined}
                  onFocus={() => {
                    lastFocusedControlRef.current = {
                      modelName: model.name,
                      kind: "model",
                    };
                  }}
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
                      "size-8 shrink-0 rounded-l-none",
                      isFavorite && "text-amber-500",
                    )}
                    aria-label={t.modelPicker.favoriteModel(
                      model.display_name,
                      model.name,
                    )}
                    aria-pressed={isFavorite}
                    disabled={isLoading || !favorites.canEdit}
                    onFocus={() => {
                      lastFocusedControlRef.current = {
                        modelName: model.name,
                        kind: "favorite",
                      };
                    }}
                    onClick={() => handleFavorite(model.name)}
                  >
                    <StarIcon
                      aria-hidden="true"
                      className={cn("size-4", isFavorite && "fill-current")}
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
        className="bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 z-50 flex max-h-[min(20rem,var(--radix-popover-content-available-height))] w-72 max-w-[calc(100vw-1rem)] origin-(--radix-popover-content-transform-origin) flex-col overflow-hidden rounded-md border shadow-md outline-none"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          focusInitialModel();
        }}
      >
        <div className="min-h-0 overflow-x-hidden overflow-y-auto py-0.5">
          {visibleModels.length === 0 ? (
            <div className="text-muted-foreground py-6 text-center text-sm">
              {t.modelPicker.noModels}
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
