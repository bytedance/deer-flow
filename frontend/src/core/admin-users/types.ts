import { z } from "zod";

import { systemRoleSchema, userSchema } from "@/core/auth/types";

export const adminUserSchema = userSchema.extend({
  created_at: z.string(),
});

export type AdminUser = z.infer<typeof adminUserSchema>;

export const adminUsersResponseSchema = z.object({
  users: z.array(adminUserSchema),
  total: z.number().int().nonnegative(),
});

export type AdminUsersResponse = z.infer<typeof adminUsersResponseSchema>;

export const adminUserRoleChangeResponseSchema = z.object({
  user: adminUserSchema,
  previous_role: systemRoleSchema,
  sessions_invalidated: z.boolean(),
});

export type AdminUserRoleChangeResponse = z.infer<
  typeof adminUserRoleChangeResponseSchema
>;
