"use client";

import {
  DatabaseIcon,
  FileSearchIcon,
  FolderIcon,
  GlobeIcon,
  SearchIcon,
} from "lucide-react";
import { useState } from "react";

import { safePluginIcon } from "@/core/mcp/icon";
import { cn } from "@/lib/utils";

import { CapabilityIcon } from "./capability-card";

const nativeIcons = {
  "web-search": SearchIcon,
  "web-fetch": FileSearchIcon,
  database: DatabaseIcon,
  browser: GlobeIcon,
  filesystem: FolderIcon,
};

/** Use the same resolver in the catalog, installed rows, and edit previews. */
export function PluginIcon({
  name,
  icon,
  className,
  asset,
  capabilityId,
}: {
  name: string;
  icon?: string | null;
  className?: string;
  asset?: string | null;
  capabilityId?: string;
}) {
  const custom = safePluginIcon(icon);
  const builtin =
    asset?.startsWith("/images/plugins/") && !asset.includes("..")
      ? asset
      : undefined;
  const [failed, setFailed] = useState<string[]>([]);
  const src =
    custom && !failed.includes(custom)
      ? custom
      : builtin && !failed.includes(builtin)
        ? builtin
        : undefined;
  if (src)
    return (
      <span
        className={cn(
          "flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-white p-2",
          className,
        )}
      >
        {/* Inline PNGs and local brand assets need no image optimization request. */}
        <img
          key={src}
          src={src}
          alt=""
          data-plugin-icon={name}
          width={32}
          height={32}
          className="size-full object-contain"
          onError={() => setFailed((previous) => [...previous, src])}
        />
      </span>
    );
  return (
    <span className={className}>
      <CapabilityIcon
        name={name}
        icon={nativeIcons[capabilityId as keyof typeof nativeIcons]}
      />
    </span>
  );
}
