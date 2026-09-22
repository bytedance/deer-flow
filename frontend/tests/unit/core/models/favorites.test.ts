import { describe, expect, test } from "@rstest/core";

import {
  favoritesKey,
  parseFavoriteNames,
  projectModelChoices,
  serializeFavoriteNames,
  updateFavoriteNames,
} from "@/core/models/favorites";
import { type Model } from "@/core/models/types";

const models: Model[] = [
  {
    id: "model-1",
    name: "openai/gpt-5",
    model: "gpt-5-2025-08-07",
    display_name: "GPT 5",
  },
  {
    id: "model-2",
    name: "azure/gpt-5",
    model: "azure-gpt-5",
    display_name: "GPT 5",
  },
  {
    id: "model-3",
    name: "anthropic/claude-sonnet",
    model: "claude-sonnet-4-5-20250929",
    display_name: "Claude Sonnet",
  },
];

describe("favorite model persistence", () => {
  test("encodes the user id in the versioned storage key", () => {
    expect(favoritesKey("person+a/b@example.com")).toBe(
      "deerflow.model-favorites.v1:person%2Ba%2Fb%40example.com",
    );
  });

  test("round-trips favorite names without rewriting valid values", () => {
    const names = ["openai/gpt-5", " spaced model "];

    expect(parseFavoriteNames(serializeFavoriteNames(names))).toEqual(names);
  });

  test("parses only version 1 payloads and filters invalid or duplicate names", () => {
    expect(
      parseFavoriteNames(
        JSON.stringify({
          version: 1,
          names: [
            "openai/gpt-5",
            42,
            "",
            "   ",
            "openai/gpt-5",
            " openai/gpt-5 ",
          ],
        }),
      ),
    ).toEqual(["openai/gpt-5", " openai/gpt-5 "]);
    expect(
      parseFavoriteNames(
        JSON.stringify({ version: 2, names: ["openai/gpt-5"] }),
      ),
    ).toEqual([]);
  });

  test("returns an empty list for malformed JSON and invalid structures", () => {
    expect(parseFavoriteNames(null)).toEqual([]);
    expect(parseFavoriteNames("not json")).toEqual([]);
    expect(parseFavoriteNames(JSON.stringify(null))).toEqual([]);
    expect(parseFavoriteNames(JSON.stringify(["openai/gpt-5"]))).toEqual([]);
    expect(
      parseFavoriteNames(JSON.stringify({ version: 1, names: "gpt-5" })),
    ).toEqual([]);
    expect(
      parseFavoriteNames(JSON.stringify({ version: "1", names: [] })),
    ).toEqual([]);
  });
});

describe("updating favorite model names", () => {
  test("adds a new favorite at the end without changing the input", () => {
    const names = ["openai/gpt-5"];

    expect(updateFavoriteNames(names, "azure/gpt-5", true)).toEqual([
      "openai/gpt-5",
      "azure/gpt-5",
    ]);
    expect(names).toEqual(["openai/gpt-5"]);
  });

  test("removes a favorite while preserving the remaining order", () => {
    const names = ["openai/gpt-5", "azure/gpt-5", "anthropic/claude-sonnet"];

    expect(updateFavoriteNames(names, "azure/gpt-5", false)).toEqual([
      "openai/gpt-5",
      "anthropic/claude-sonnet",
    ]);
  });

  test("returns the original array for blank names and idempotent updates", () => {
    const names = ["openai/gpt-5"];

    expect(updateFavoriteNames(names, "   ", true)).toBe(names);
    expect(updateFavoriteNames(names, "openai/gpt-5", true)).toBe(names);
    expect(updateFavoriteNames(names, "azure/gpt-5", false)).toBe(names);
  });

  test("accepts readonly favorite names", () => {
    const names = ["openai/gpt-5"] as const;

    expect(serializeFavoriteNames(names)).toBe(
      '{"version":1,"names":["openai/gpt-5"]}',
    );
    expect(updateFavoriteNames(names, "azure/gpt-5", true)).toEqual([
      "openai/gpt-5",
      "azure/gpt-5",
    ]);
  });
});

describe("projecting model choices", () => {
  test("keeps API order for empty, partial, and complete favorite sets", () => {
    expect(projectModelChoices(models, [])).toEqual({
      favorites: [],
      others: models,
    });
    expect(
      projectModelChoices(models, ["anthropic/claude-sonnet", "openai/gpt-5"]),
    ).toEqual({
      favorites: [models[0], models[2]],
      others: [models[1]],
    });
    expect(
      projectModelChoices(
        models,
        models.map((model) => model.name),
      ),
    ).toEqual({
      favorites: models,
      others: [],
    });
  });

  test("uses model name rather than a shared display name as favorite identity", () => {
    const result = projectModelChoices(models, ["azure/gpt-5"]);

    expect(result.favorites).toEqual([models[1]]);
    expect(result.others).toEqual([models[0], models[2]]);
  });

  test("restores temporarily unavailable favorites without modifying inputs", () => {
    const modelSnapshot = structuredClone(models);
    const favoriteNames = ["missing/model", "anthropic/claude-sonnet"];
    const favoriteSnapshot = [...favoriteNames];

    const hidden = projectModelChoices(models.slice(0, 2), favoriteNames);
    const visibleAgain = projectModelChoices(models, favoriteNames);

    expect(hidden.favorites).toEqual([]);
    expect(hidden.others).toEqual(models.slice(0, 2));
    expect(visibleAgain.favorites).toEqual([models[2]]);
    expect(models).toEqual(modelSnapshot);
    expect(favoriteNames).toEqual(favoriteSnapshot);
  });

  test("accepts readonly model and favorite inputs", () => {
    const readonlyModels = [models[0]!, models[1]!] as const;
    const readonlyFavorites = ["azure/gpt-5"] as const;

    expect(
      projectModelChoices(readonlyModels, readonlyFavorites).favorites,
    ).toEqual([models[1]]);
  });
});
