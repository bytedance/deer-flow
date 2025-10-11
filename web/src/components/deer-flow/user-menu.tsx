// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { UserOutlined, LogoutOutlined, SettingOutlined } from "@ant-design/icons";
import { useTranslations } from "next-intl";
import { useAuth } from "~/core/auth/context";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { Button } from "~/components/ui/button";

export function UserMenu() {
  const { user, logout } = useAuth();
  const t = useTranslations("chat.page.userMenu");

  if (!user) {
    return null;
  }

  const handleLogout = async () => {
    await logout();
    // Redirect to login page
    window.location.href = "/login";
  };

  const getUserInitials = () => {
    if (user.name) {
      return user.name.charAt(0).toUpperCase();
    }
    if (user.email) {
      return user.email.charAt(0).toUpperCase();
    }
    return "U";
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary">
            <UserOutlined />
          </div>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{user.name || user.email}</p>
            <p className="text-xs leading-none text-muted-foreground">
              {user.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {user.role === "admin" && (
          <DropdownMenuItem
            onClick={() => {
              window.location.href = "/admin";
            }}
            className="cursor-pointer"
          >
            <SettingOutlined className="mr-2 h-4 w-4" />
            <span>{t("adminConsole", { defaultMessage: "Admin Console" })}</span>
          </DropdownMenuItem>
        )}
        {user.role === "admin" && <DropdownMenuSeparator />}
        <DropdownMenuItem onClick={handleLogout} className="cursor-pointer">
          <LogoutOutlined className="mr-2 h-4 w-4" />
          <span>{t("logout")}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}