import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SystemRole } from "@/core/auth/types";

import {
  AdminUsersRequestError,
  changeAdminUserRole,
  listAdminUsers,
} from "./api";
import type { AdminUsersResponse } from "./types";

export const adminUsersQueryKey = ["auth", "admin-users"] as const;

export function useAdminUsers(enabled: boolean) {
  return useQuery({
    queryKey: adminUsersQueryKey,
    queryFn: listAdminUsers,
    enabled,
    retry: (failureCount, error) =>
      !(error instanceof AdminUsersRequestError) && failureCount < 3,
  });
}

export function useChangeAdminUserRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      systemRole,
    }: {
      userId: string;
      systemRole: SystemRole;
    }) => changeAdminUserRole(userId, systemRole),
    onSuccess: (result) => {
      queryClient.setQueryData<AdminUsersResponse>(
        adminUsersQueryKey,
        (current) =>
          current
            ? {
                ...current,
                users: current.users.map((user) =>
                  user.id === result.user.id ? result.user : user,
                ),
              }
            : current,
      );
      void queryClient.invalidateQueries({ queryKey: adminUsersQueryKey });
    },
  });
}
