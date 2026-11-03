import { useEffect, useRef, useState } from "react";

import { useLibraryRefresh } from "@/api/hooks";
import { Inspector } from "@/components/layout/Inspector";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusBar";
import { TopBar } from "@/components/layout/TopBar";
import { ALL_NAV, MAIN_NAV, type PageId } from "@/navigation";
import { LibraryPage } from "@/pages/LibraryPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";
import { SettingsPage } from "@/pages/SettingsPage";
import type { Selection } from "@/selection";

const INSPECTOR_KEY = "lumen.inspectorOpen";

function initialInspectorOpen(): boolean {
  try {
    return localStorage.getItem(INSPECTOR_KEY) !== "false";
  } catch {
    return true;
  }
}

const iconFor = (id: PageId) => MAIN_NAV.find((item) => item.id === id)!.icon;

export default function App() {
  const [page, setPage] = useState<PageId>("library");
  const [inspectorOpen, setInspectorOpen] = useState(initialInspectorOpen);
  const [selection, setSelection] = useState<Selection>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  useLibraryRefresh();

  useEffect(() => {
    try {
      localStorage.setItem(INSPECTOR_KEY, String(inspectorOpen));
    } catch {
      // Preference simply won't persist.
    }
  }, [inspectorOpen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.altKey || event.metaKey) return;
      const key = event.key.toLowerCase();
      const target = ALL_NAV.find((item) => item.shortcut === key);
      if (target) {
        event.preventDefault();
        setPage(target.id);
      } else if (key === "k" || key === "f") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (key === "i") {
        event.preventDefault();
        setInspectorOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <TopBar
        searchRef={searchRef}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((open) => !open)}
      />
      <div className="flex min-h-0 flex-1">
        <Sidebar current={page} onNavigate={setPage} />
        <main className="min-w-0 flex-1 overflow-y-auto">
          {page === "library" && (
            <LibraryPage selection={selection} onSelect={setSelection} />
          )}
          {page === "timeline" && (
            <PlaceholderPage page="timeline" icon={iconFor("timeline")} phase="Phase 3" />
          )}
          {page === "map" && <PlaceholderPage page="map" icon={iconFor("map")} phase="Phase 3" />}
          {page === "aiSearch" && (
            <PlaceholderPage page="aiSearch" icon={iconFor("aiSearch")} phase="Phase 4" />
          )}
          {page === "collections" && (
            <PlaceholderPage page="collections" icon={iconFor("collections")} phase="Phase 3" />
          )}
          {page === "settings" && <SettingsPage />}
        </main>
        {inspectorOpen && <Inspector selection={page === "library" ? selection : null} />}
      </div>
      <StatusBar />
    </div>
  );
}
