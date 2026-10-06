import {
  Bookmark,
  Briefcase,
  Clock,
  Flag,
  Folder,
  Heart,
  Layers,
  LayoutGrid,
  type LucideIcon,
  MessageSquare,
  Star,
  Target,
  Zap,
} from "lucide-react";

import {
  DRAWER_COLORS,
  type DrawerColorKey,
  type DrawerIconKey,
} from "@/core/knowledge/card-drawers";
import { cn } from "@/lib/utils";

/** Maps a stored drawer icon key to its lucide component. */
export const DRAWER_ICON_COMPONENTS: Record<DrawerIconKey, LucideIcon> = {
  folder: Folder,
  star: Star,
  layers: Layers,
  briefcase: Briefcase,
  target: Target,
  zap: Zap,
  flag: Flag,
  heart: Heart,
  bookmark: Bookmark,
  clock: Clock,
  message: MessageSquare,
  grid: LayoutGrid,
};

/**
 * A drawer's icon tinted with its color's accent. When `color` is omitted the
 * glyph inherits the surrounding text color (used for the neutral picker grid
 * in the create dialog, where selection is shown by the cell, not the glyph).
 */
export function DrawerGlyph({
  icon,
  color,
  className,
}: {
  icon: DrawerIconKey;
  color?: DrawerColorKey;
  className?: string;
}) {
  const Glyph = DRAWER_ICON_COMPONENTS[icon] ?? Folder;
  const accent = color ? DRAWER_COLORS[color]?.accent : undefined;
  return (
    <Glyph
      aria-hidden="true"
      className={cn("size-4 shrink-0", className)}
      style={accent ? { color: accent } : undefined}
    />
  );
}
