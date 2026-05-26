import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createTemplateFromBlueprint,
  getBlueprint,
  listBlueprints,
} from "./api";

const BLUEPRINTS_KEY = "blueprints" as const;

export function useBlueprints() {
  const { data, isLoading, error } = useQuery({
    queryKey: [BLUEPRINTS_KEY, "list"],
    queryFn: listBlueprints,
  });
  return { blueprints: data ?? [], isLoading, error };
}

export function useBlueprint(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [BLUEPRINTS_KEY, "one", id],
    queryFn: () => getBlueprint(id ?? ""),
    enabled: !!id,
  });
  return { blueprint: data, isLoading, error };
}

export function useCreateTemplateFromBlueprint(blueprintId: string) {
  return useMutation({
    mutationFn: (body: { name: string; visibility: "private" | "tenant" }) =>
      createTemplateFromBlueprint(blueprintId, body),
  });
}
