"use client";

import { LoaderCircleIcon, ShieldCheckIcon, UserRoundIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import {
  AdminUsersRequestError,
  canManageAdminUsers,
  useAdminUsers,
  useChangeAdminUserRole,
  type AdminUser,
} from "@/core/admin-users";
import { useAuth } from "@/core/auth/AuthProvider";
import type { SystemRole } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

type PendingRoleChange = {
  user: AdminUser;
  nextRole: SystemRole;
};

const EMPTY_USERS: AdminUser[] = [];

function roleChangeErrorMessage(
  error: unknown,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (!(error instanceof AdminUsersRequestError)) {
    return error instanceof TypeError
      ? t.settings.users.errors.network
      : t.settings.users.errors.unknown;
  }
  if (
    error.code === "last_admin" ||
    error.code === "last_admin_required" ||
    error.code === "cannot_demote_last_admin"
  ) {
    return t.settings.users.errors.lastAdmin;
  }
  if (error.status === 403) {
    return t.settings.users.errors.forbidden;
  }
  if (error.status === 404 || error.code === "user_not_found") {
    return t.settings.users.errors.notFound;
  }
  if (error.status === 409) {
    return t.settings.users.errors.conflict;
  }
  return t.settings.users.errors.unknown;
}

export function UsersSettingsPage() {
  const { user: currentUser, refreshUser } = useAuth();
  const { t } = useI18n();
  const canManage = canManageAdminUsers(currentUser);
  const usersQuery = useAdminUsers(canManage);
  const roleMutation = useChangeAdminUserRole();
  const [search, setSearch] = useState("");
  const [pendingChange, setPendingChange] = useState<PendingRoleChange | null>(
    null,
  );
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const users = usersQuery.data?.users ?? EMPTY_USERS;
  const adminCount = users.filter(
    (managedUser) => managedUser.system_role === "admin",
  ).length;
  const filteredUsers = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return users;
    return users.filter((managedUser) =>
      managedUser.email.toLowerCase().includes(query),
    );
  }, [search, users]);

  const closeConfirm = () => {
    if (roleMutation.isPending) return;
    setPendingChange(null);
    setConfirmError(null);
  };

  const confirmRoleChange = async () => {
    if (!pendingChange) return;
    setConfirmError(null);
    try {
      const result = await roleMutation.mutateAsync({
        userId: pendingChange.user.id,
        systemRole: pendingChange.nextRole,
      });
      setPendingChange(null);
      toast.success(
        result.user.system_role === "admin"
          ? t.settings.users.success.promoted(result.user.email)
          : t.settings.users.success.demoted(result.user.email),
      );
      if (
        currentUser?.id === result.user.id &&
        result.previous_role !== result.user.system_role
      ) {
        await refreshUser();
      }
    } catch (error) {
      setConfirmError(roleChangeErrorMessage(error, t));
      if (error instanceof AdminUsersRequestError) {
        if (error.status === 403) {
          await refreshUser();
        } else if (error.status === 404 || error.status === 409) {
          void usersQuery.refetch();
        }
      }
    }
  };

  return (
    <>
      <SettingsSection
        title={t.settings.users.title}
        description={t.settings.users.description}
      >
        {!canManage ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.users.adminRequired}
          </div>
        ) : usersQuery.isLoading ? (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t.common.loading}
          </div>
        ) : usersQuery.error ? (
          <div className="space-y-3">
            <p className="text-destructive text-sm">
              {usersQuery.error instanceof AdminUsersRequestError &&
              usersQuery.error.isAdminRequired
                ? t.settings.users.adminRequired
                : t.settings.users.loadFailed}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void usersQuery.refetch()}
            >
              {t.settings.users.retry}
            </Button>
          </div>
        ) : users.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.users.empty}
          </div>
        ) : (
          <div className="space-y-4">
            <Input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t.settings.users.searchPlaceholder}
              aria-label={t.settings.users.searchPlaceholder}
            />
            {filteredUsers.length === 0 ? (
              <div className="text-muted-foreground text-sm">
                {t.settings.users.noResults}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {filteredUsers.map((managedUser) => {
                  const isCurrentUser = managedUser.id === currentUser?.id;
                  const nextRole: SystemRole =
                    managedUser.system_role === "admin" ? "user" : "admin";
                  const lastAdmin =
                    managedUser.system_role === "admin" && adminCount <= 1;
                  const actionLabel =
                    nextRole === "admin"
                      ? t.settings.users.actions.promoteUser(managedUser.email)
                      : t.settings.users.actions.demoteUser(managedUser.email);
                  return (
                    <Item
                      key={managedUser.id}
                      variant="outline"
                      className="w-full flex-wrap sm:flex-nowrap"
                      data-testid={`admin-user-row-${managedUser.id}`}
                    >
                      <ItemMedia variant="icon" className="bg-background">
                        {managedUser.system_role === "admin" ? (
                          <ShieldCheckIcon className="size-5" />
                        ) : (
                          <UserRoundIcon className="size-5" />
                        )}
                      </ItemMedia>
                      <ItemContent className="min-w-0">
                        <ItemTitle className="flex flex-wrap items-center gap-2">
                          <span className="break-all">{managedUser.email}</span>
                          {isCurrentUser ? (
                            <Badge variant="outline">
                              {t.settings.users.currentUser}
                            </Badge>
                          ) : null}
                        </ItemTitle>
                        <ItemDescription>
                          {managedUser.oauth_provider
                            ? t.settings.users.ssoAccount(
                                managedUser.oauth_provider,
                              )
                            : t.settings.users.localAccount}
                        </ItemDescription>
                      </ItemContent>
                      <ItemActions className="ml-auto flex-wrap">
                        <Badge
                          variant={
                            managedUser.system_role === "admin"
                              ? "default"
                              : "outline"
                          }
                        >
                          {t.settings.users.roles[managedUser.system_role]}
                        </Badge>
                        <Button
                          type="button"
                          size="sm"
                          variant={
                            nextRole === "user" ? "destructive" : "outline"
                          }
                          aria-label={actionLabel}
                          title={
                            lastAdmin
                              ? t.settings.users.blocked.lastAdmin
                              : undefined
                          }
                          disabled={lastAdmin || roleMutation.isPending}
                          onClick={() => {
                            setConfirmError(null);
                            setPendingChange({ user: managedUser, nextRole });
                          }}
                        >
                          {nextRole === "admin"
                            ? t.settings.users.actions.promote
                            : t.settings.users.actions.demote}
                        </Button>
                      </ItemActions>
                    </Item>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </SettingsSection>

      <Dialog
        open={pendingChange !== null}
        onOpenChange={(open) => {
          if (!open) closeConfirm();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.users.confirm.title}</DialogTitle>
            <DialogDescription>
              {pendingChange?.nextRole === "admin"
                ? t.settings.users.confirm.promote(pendingChange.user.email)
                : pendingChange
                  ? t.settings.users.confirm.demote(pendingChange.user.email)
                  : ""}
            </DialogDescription>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            {t.settings.users.confirm.sessionWarning}
          </p>
          {confirmError ? (
            <p className="text-destructive text-sm" role="alert">
              {confirmError}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={closeConfirm}
              disabled={roleMutation.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              variant={
                pendingChange?.nextRole === "user" ? "destructive" : "default"
              }
              onClick={() => void confirmRoleChange()}
              disabled={roleMutation.isPending}
            >
              {roleMutation.isPending
                ? t.settings.users.actions.changing
                : pendingChange?.nextRole === "admin"
                  ? t.settings.users.actions.promote
                  : t.settings.users.actions.demote}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
