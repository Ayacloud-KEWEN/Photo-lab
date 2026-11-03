import {
  Album,
  CalendarDays,
  Images,
  MapPinned,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type PageId = "library" | "timeline" | "map" | "aiSearch" | "collections" | "settings";

export interface NavItem {
  id: PageId;
  icon: LucideIcon;
  /** Ctrl+<shortcut> switches to the page. */
  shortcut: string;
}

export const MAIN_NAV: NavItem[] = [
  { id: "library", icon: Images, shortcut: "1" },
  { id: "timeline", icon: CalendarDays, shortcut: "2" },
  { id: "map", icon: MapPinned, shortcut: "3" },
  { id: "aiSearch", icon: Sparkles, shortcut: "4" },
  { id: "collections", icon: Album, shortcut: "5" },
];

export const SETTINGS_NAV: NavItem = { id: "settings", icon: Settings, shortcut: "," };

export const ALL_NAV: NavItem[] = [...MAIN_NAV, SETTINGS_NAV];
