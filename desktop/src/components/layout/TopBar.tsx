import { PanelRightClose, PanelRightOpen, Search } from "lucide-react";
import type { Ref } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";

interface TopBarProps {
  searchRef: Ref<HTMLInputElement>;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
}

export function TopBar({ searchRef, inspectorOpen, onToggleInspector }: TopBarProps) {
  const { t } = useTranslation();
  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b bg-surface pr-2">
      <div className="flex w-52 shrink-0 items-center gap-2 px-4">
        <LogoMark />
        <span className="text-[13px] font-semibold tracking-[0.18em]">LUMEN</span>
        <span className="text-[13px] font-light tracking-wide text-muted-foreground">Studio</span>
      </div>

      <div className="relative w-full max-w-xl">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
        <Input
          ref={searchRef}
          type="search"
          aria-label={t("topbar.searchPlaceholder")}
          placeholder={t("topbar.searchPlaceholder")}
          className="h-7 bg-background/70 pl-8 pr-16"
        />
        <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border px-1.5 font-sans text-[10px] text-subtle-foreground">
          Ctrl K
        </kbd>
      </div>

      <div className="ml-auto flex items-center">
        <Tooltip label={`${inspectorOpen ? t("topbar.hideInspector") : t("topbar.showInspector")}  (Ctrl I)`}>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleInspector}
            aria-pressed={inspectorOpen}
            aria-label={inspectorOpen ? t("topbar.hideInspector") : t("topbar.showInspector")}
          >
            {inspectorOpen ? <PanelRightClose /> : <PanelRightOpen />}
          </Button>
        </Tooltip>
      </div>
    </header>
  );
}

function LogoMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-[18px]" aria-hidden="true">
      <circle cx="12" cy="12" r="9.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="12" cy="12" r="3.25" fill="var(--highlight)" />
    </svg>
  );
}
