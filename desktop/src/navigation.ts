import {
  Album,
  Images,
  ListChecks,
  MapPinned,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type PageId =
  | "library"
  | "map"
  | "aiSearch"
  | "collections"
  | "cull"
  | "settings";

export interface NavItem {
  id: PageId;
  icon: LucideIcon;
  /** Ctrl+<shortcut> switches to the page. */
  shortcut: string;
}

export const MAIN_NAV: NavItem[] = [
  { id: "library", icon: Images, shortcut: "1" },
  { id: "map", icon: MapPinned, shortcut: "2" },
  { id: "aiSearch", icon: Sparkles, shortcut: "3" },
  { id: "collections", icon: Album, shortcut: "4" },
  { id: "cull", icon: ListChecks, shortcut: "5" },
];

export const SETTINGS_NAV: NavItem = { id: "settings", icon: Settings, shortcut: "," };

export const ALL_NAV: NavItem[] = [...MAIN_NAV, SETTINGS_NAV];
