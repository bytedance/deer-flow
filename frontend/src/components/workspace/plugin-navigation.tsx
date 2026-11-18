"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { pluginPages, pluginPageTitle } from "@/core/extensions/pages";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";

export function PluginNavigation() {
  const query = useFrontendExtensions();
  const pathname = usePathname();
  const { locale, t } = useI18n();
  const pages = pluginPages(query.data ?? []).filter(
    ({ surface }) => surface.navigation,
  );
  if (!pages.length) return null;
  return (
    <SidebarGroup>
      <SidebarGroupLabel>{t.extensions.navigation}</SidebarGroupLabel>
      <SidebarMenu>
        {pages.map(({ surface, href, icon }) => {
          const Icon = extensionIcon(icon);
          const title = pluginPageTitle(surface, locale);
          return (
            <SidebarMenuItem key={href}>
              <SidebarMenuButton
                asChild
                isActive={pathname === href}
                tooltip={title}
              >
                <Link href={href}>
                  <Icon />
                  <span>{title}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
