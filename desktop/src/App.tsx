import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { useLibraryRefresh } from "@/api/hooks";
import { Inspector } from "@/components/layout/Inspector";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusBar";
import { TopBar } from "@/components/layout/TopBar";
import { CloudDialog } from "@/components/ai/CloudDialog";
import { AddToCollectionDialog } from "@/components/collections/AddToCollectionDialog";
import { ExportDialog } from "@/components/library/ExportDialog";
import { Viewer } from "@/components/viewer/Viewer";
import { cleanQuery, useLibraryState } from "@/library/state";
import { ALL_NAV, type PageId } from "@/navigation";
import { AISearchPage } from "@/pages/AISearchPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { CollectionsPage } from "@/pages/CollectionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TimelinePage } from "@/pages/TimelinePage";
import type { Selection } from "@/selection";

// MapLibre is large: load the map page only when it is opened.
const MapPage = lazy(() => import("@/pages/MapPage").then((module) => ({ default: module.MapPage })));

const INSPECTOR_KEY = "lumen.inspectorOpen";
const SEARCH_DELAY_MS = 250;
/** Pages that show the shared (filtered) library. */
const LIBRARY_VIEWS: PageId[] = ["library", "timeline", "map", "aiSearch"];
/** Pages whose inspector shows the selected photo. */
const INSPECTED_VIEWS: PageId[] = ["library", "timeline", "aiSearch"];

function initialInspectorOpen(): boolean {
  try {
    return localStorage.getItem(INSPECTOR_KEY) !== "false";
  } catch {
    return true;
  }
}

export default function App() {
  const [page, setPage] = useState<PageId>("library");
  const [inspectorOpen, setInspectorOpen] = useState(initialInspectorOpen);
  const [selection, setSelection] = useState<Selection>(null);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const { setQuery, viewer, similarTo, cloudRequest } = useLibraryState();
  useLibraryRefresh();

  // "Find similar" (inspector, viewer) opens the AI search page.
  useEffect(() => {
    if (similarTo) setPage("aiSearch");
  }, [similarTo]);

  useEffect(() => {
    try {
      localStorage.setItem(INSPECTOR_KEY, String(inspectorOpen));
    } catch {
      // Preference simply won't persist.
    }
  }, [inspectorOpen]);

  // Live search: applies to the library, timeline and map.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery((current) => cleanQuery({ ...current, q: search.trim() || undefined }));
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search, setQuery]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (viewer || cloudRequest || !event.ctrlKey || event.altKey || event.metaKey) return;
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
  }, [viewer, cloudRequest]);

  const onSearchSubmit = () => {
    if (!LIBRARY_VIEWS.includes(page)) setPage("library");
  };

  return (
    <div className="flex h-full flex-col">
      <TopBar
        searchRef={searchRef}
        search={search}
        onSearchChange={setSearch}
        onSearchSubmit={onSearchSubmit}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((open) => !open)}
      />
      <div className="flex min-h-0 flex-1">
        <Sidebar current={page} onNavigate={setPage} />
        <main className="min-w-0 flex-1 overflow-hidden">
          {page === "library" && <LibraryPage selection={selection} onSelect={setSelection} />}
          {page === "timeline" && <TimelinePage onSelect={setSelection} />}
          {page === "map" && (
            <Suspense fallback={null}>
              <MapPage />
            </Suspense>
          )}
          {page === "aiSearch" && <AISearchPage onSelect={setSelection} />}
          {page === "collections" && <CollectionsPage />}
          {page === "settings" && <SettingsPage />}
        </main>
        {inspectorOpen && page !== "map" && page !== "collections" && (
          <Inspector selection={INSPECTED_VIEWS.includes(page) ? selection : null} />
        )}
      </div>
      <StatusBar />
      <Viewer />
      <CloudDialog onOpenSettings={() => setPage("settings")} />
      <ExportDialog />
      <AddToCollectionDialog />
    </div>
  );
}
