import type { Model } from "./types";

export function filterModels(
  models: readonly Model[],
  query: string,
  provider = "",
) {
  const term = query.trim().toLocaleLowerCase();
  return models.filter(
    (model) =>
      (!provider || (model.provider ?? "") === provider) &&
      [model.name, model.model, model.display_name, model.provider].some(
        (value) => value?.toLocaleLowerCase().includes(term),
      ),
  );
}

export function projectRecentModels(
  models: readonly Model[],
  recent: readonly string[],
  favorites: readonly string[],
) {
  const available = new Map(models.map((model) => [model.name, model]));
  return [...new Set(recent)]
    .filter((name) => !favorites.includes(name))
    .flatMap((name) => {
      const model = available.get(name);
      return model ? [model] : [];
    });
}
