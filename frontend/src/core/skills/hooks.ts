import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { enableSkill, getSkillsConfig, updateSkillsConfig } from "./api";

import { loadSkills } from ".";

export function useSkills() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["skills"],
    queryFn: () => loadSkills(),
  });
  return { skills: data ?? [], isLoading, error };
}

export function useEnableSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      skillName,
      enabled,
    }: {
      skillName: string;
      enabled: boolean;
    }) => {
      await enableSkill(skillName, enabled);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useSkillsConfig() {
  return useQuery({
    queryKey: ["skills-config"],
    queryFn: () => getSkillsConfig(),
  });
}

export function useUpdateSkillsConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (allowExternalSkills: boolean) =>
      updateSkillsConfig(allowExternalSkills),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["skills-config"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}
