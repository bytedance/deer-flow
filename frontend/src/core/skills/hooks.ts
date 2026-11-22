import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";
import { fetchFeatures } from "@/core/features/api";

import {
  enableSkill,
  loadSkills,
  SkillRequestError,
  uploadSkillArchive,
} from "./api";
import { canInstallSkillFromSource, canManageSkills } from "./permissions";

export function useSkillManagement() {
  const { user } = useAuth();
  const { data } = useQuery({
    queryKey: ["features", "skill_management"],
    queryFn: ({ signal }) => fetchFeatures(signal),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  const feature = data?.skill_management;
  return {
    canManage: canManageSkills(user, feature),
    sourceInstallAvailable: canInstallSkillFromSource(feature),
  };
}

export function useSkills() {
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ["skills"],
    queryFn: () => loadSkills(),
    retry: (count, err) => !(err instanceof SkillRequestError) && count < 3,
  });
  return { skills: data ?? [], isLoading, isFetching, error, refetch };
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

export function useUploadSkillArchive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadSkillArchive,
    onSuccess: (result) => {
      if (result.success) {
        void queryClient.invalidateQueries({ queryKey: ["skills"] });
      }
    },
  });
}
