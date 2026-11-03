import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { MAIN_NAV, SETTINGS_NAV, type NavItem, type PageId } from "@/navigation";

interface SidebarProps {
  current: PageId;
  onNavigate: (page: PageId) => void;
}

export function Sidebar({ current, onNavigate }: SidebarProps) {
  return (
    <nav
      aria-label="Main"
      className="flex w-52 shrink-0 flex-col border-r bg-surface px-2 pb-2 pt-3"
    >
      <ul className="flex flex-col gap-0.5">
        {MAIN_NAV.map((item) => (
          <li key={item.id}>
            <SidebarLink item={item} active={current === item.id} onNavigate={onNavigate} />
          </li>
        ))}
      </ul>
      <div className="mt-auto border-t pt-2">
        <SidebarLink
          item={SETTINGS_NAV}
          active={current === SETTINGS_NAV.id}
          onNavigate={onNavigate}
        />
      </div>
    </nav>
  );
}

function SidebarLink({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate: (page: PageId) => void;
}) {
  const { t } = useTranslation();
  const Icon = item.icon;
  return (
    <button
      type="button"
      onClick={() => onNavigate(item.id)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-[13px] transition-colors",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      {active && (
        <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-highlight" />
      )}
      <Icon className="size-4" strokeWidth={1.75} />
      <span className="flex-1 truncate">{t(`nav.${item.id}`)}</span>
      <kbd className="font-sans text-[11px] text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100">
        Ctrl {item.shortcut}
      </kbd>
    </button>
  );
}
