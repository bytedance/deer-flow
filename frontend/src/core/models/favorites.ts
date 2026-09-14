import { defaultFilter } from "cmdk";

import { type Model } from "./types";

const FAVORITES_KEY_PREFIX = "deerflow.model-favorites.v1:";

interface FavoriteNamesPayload {
  version: 1;
  names: readonly string[];
}

export interface ModelChoiceProjection {
  matches: readonly Model[];
  favorites: readonly Model[];
  others: readonly Model[];
}

export function favoritesKey(userId: string): string {
  return `${FAVORITES_KEY_PREFIX}${encodeURIComponent(userId)}`;
}

export function parseFavoriteNames(value: string | null): readonly string[] {
  if (value === null) {
    return [];
  }

  let payload: unknown;
  try {
    payload = JSON.parse(value);
  } catch {
    return [];
  }

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("version" in payload) ||
    payload.version !== 1 ||
    !("names" in payload) ||
    !Array.isArray(payload.names)
  ) {
    return [];
  }

  const names: string[] = [];
  const seen = new Set<string>();
  for (const name of payload.names) {
    if (typeof name !== "string" || name.trim() === "" || seen.has(name)) {
      continue;
    }
    seen.add(name);
    names.push(name);
  }
  return names;
}

export function serializeFavoriteNames(names: readonly string[]): string {
  const payload: FavoriteNamesPayload = { version: 1, names };
  return JSON.stringify(payload);
}

export function updateFavoriteNames(
  names: readonly string[],
  name: string,
  favorite: boolean,
): readonly string[] {
  if (name.trim() === "") {
    return names;
  }

  const includesName = names.includes(name);
  if (favorite) {
    return includesName ? names : [...names, name];
  }
  return includesName ? names.filter((candidate) => candidate !== name) : names;
}

export function projectModelChoices(
  models: readonly Model[],
  favoriteNames: readonly string[],
  query: string,
): ModelChoiceProjection {
  const matches = query
    ? models.filter(
        (model) =>
          defaultFilter(model.name, query, [model.display_name, model.model]) >
          0,
      )
    : [...models];
  const favoriteNameSet = new Set(favoriteNames);

  return {
    matches,
    favorites: matches.filter((model) => favoriteNameSet.has(model.name)),
    others: matches.filter((model) => !favoriteNameSet.has(model.name)),
  };
}
