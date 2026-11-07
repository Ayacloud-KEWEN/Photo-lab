import type { TFunction } from "i18next";
import {
  AlertCircle,
  ArrowUpToLine,
  ChevronDown,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Info,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { ApiError } from "@/api/client";
import {
  tasksByRoot,
  useActiveTasks,
  useCancelTask,
  useCreateStorageRoot,
  useDeleteStorageRoot,
  useScanStorageRoot,
  useStorageRoots,
  useTimeline,
} from "@/api/hooks";
import type { StorageRoot, Task } from "@/api/types";
import { DateRail, fromMonth, groupByDay } from "@/components/library/DateRail";
import { FilterBar } from "@/components/library/FilterBar";
import { PhotoWall } from "@/components/library/PhotoWall";
import { SelectionBar } from "@/components/library/SelectionBar";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { WallMode } from "@/library/layout";
import { cleanQuery, useLibraryState } from "@/library/state";
import { useWall } from "@/library/useWall";
import { confirmAction, pickDirectory } from "@/lib/dialogs";
import { cn } from "@/lib/utils";
import type { Selection } from "@/selection";

interface LibraryPageProps {
  selection: Selection;
  onSelect: (selection: Selection) => void;
}

const MODE_KEY = "lumen.wallMode";
const GROUPED_KEY = "lumen.groupByDate";

function initialGrouped(): boolean {
  try {
    return localStorage.getItem(GROUPED_KEY) !== "false";
  } catch {
    return true;
  }
}

function initialMode(): WallMode {
  try {
    return localStorage.getItem(MODE_KEY) === "grid" ? "grid" : "justified";
  } catch {
    return "justified";
  }
}

export function describeError(t: TFunction, error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "conflict":
        return t("library.errors.conflict");
      case "invalid_path":
        return t("library.errors.invalid_path", { message: error.message });
      case "network_error":
        return t("library.errors.network_error");
    }
  }
  const message = error instanceof Error ? error.message : String(error);
  return t("library.errors.generic", { message });
}

export function LibraryPage({ selection, onSelect }: LibraryPageProps) {
  const { t, i18n } = useTranslation();
  const backend = useBackendStatus();
  const roots = useStorageRoots();
  const tasks = useActiveTasks();
  const createRoot = useCreateStorageRoot();
  const deleteRoot = useDeleteStorageRoot();
  const scanRoot = useScanStorageRoot();
  const cancelTask = useCancelTask();
  const { query, setQuery } = useLibraryState();
  const [actionError, setActionError] = useState<string | null>(null);
  const [mode, setMode] = useState<WallMode>(initialMode);
  const [showSources, setShowSources] = useState<boolean | null>(null);
  const [grouped, setGrouped] = useState(initialGrouped);
  // The month jumped to in the date bar (null: from the newest, or oldest, photo).
  const [anchor, setAnchor] = useState<string | null>(null);
  const sort = query.sort ?? "capture_desc";
  const byDate = grouped && sort !== "added_desc";
  const oldestFirst = sort === "capture_asc";
  const railQuery = useMemo(() => cleanQuery({ ...query, sort: undefined }), [query]);
  const wallQuery = useMemo(
    () => (byDate && anchor ? fromMonth(query, anchor, oldestFirst) : query),
    [byDate, anchor, query, oldestFirst],
  );
  // A new sort order or no grouping: the jump no longer applies.
  useEffect(() => setAnchor(null), [sort, grouped]);

  const focusAsset = useCallback(
    (id: number | null) => {
      if (id !== null) onSelect({ kind: "asset", id });
    },
    [onSelect],
  );
  const wall = useWall(wallQuery, focusAsset);
  const counts = useTimeline(query, "year");
  const total = counts.data?.buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  const rootTasks = useMemo(() => tasksByRoot(tasks.data), [tasks.data]);
  const groups = useMemo(
    () => (byDate ? groupByDay(wall.items, i18n.language) : [{ key: "all", items: wall.items }]),
    [byDate, wall.items, i18n.language],
  );

  const changeGrouped = (next: boolean) => {
    setGrouped(next);
    try {
      localStorage.setItem(GROUPED_KEY, String(next));
    } catch {
      // Preference simply won't persist.
    }
  };

  const changeMode = (next: WallMode) => {
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      // Preference simply won't persist.
    }
  };

  const run = async (action: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await action();
    } catch (error) {
      setActionError(describeError(t, error));
    }
  };

  const addFolder = () =>
    run(async () => {
      const path = await pickDirectory(t("library.pickerTitle"));
      if (!path) return;
      const root = await createRoot.mutateAsync({ path });
      setShowSources(true);
      onSelect({ kind: "root", id: root.id });
    });

  const removeFolder = (root: StorageRoot) =>
    run(async () => {
      const ok = await confirmAction(
        t("library.removeConfirmMessage", { name: root.display_name }),
        {
          title: t("library.removeConfirmTitle"),
          okLabel: t("library.removeConfirmOk"),
          cancelLabel: t("library.cancel"),
        },
      );
      if (!ok) return;
      await deleteRoot.mutateAsync(root.id);
      if (selection?.kind === "root" && selection.id === root.id) onSelect(null);
    });

  if (backend.state === "failed") {
    return (
      <CenteredMessage tone="error">
        {t("library.backendUnavailable", { message: backend.message })}
      </CenteredMessage>
    );
  }
  if (roots.isError) {
    return (
      <CenteredMessage tone="error">
        <span>{describeError(t, roots.error)}</span>
        <Button variant="outline" size="sm" onClick={() => void roots.refetch()}>
          {t("library.retry")}
        </Button>
      </CenteredMessage>
    );
  }
  if (!roots.data) {
    return <CenteredMessage>{t("library.connecting")}</CenteredMessage>;
  }

  const busy = createRoot.isPending;

  if (roots.data.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-8 text-center">
        <div className="mb-6 flex size-16 items-center justify-center rounded-full border bg-card">
          <FolderOpen className="size-7 text-muted-foreground" strokeWidth={1.5} />
        </div>
        <h1 className="text-lg font-medium">{t("library.emptyTitle")}</h1>
        <p className="mt-2 max-w-md leading-relaxed text-muted-foreground">
          {t("library.emptyDescription")}
        </p>
        <Button size="lg" className="mt-7" onClick={() => void addFolder()} disabled={busy}>
          <FolderPlus />
          {t("library.selectFolder")}
        </Button>
        <p className="mt-4 text-xs text-subtle-foreground">{t("library.emptyFormats")}</p>
        {actionError && <ErrorBanner message={actionError} className="mt-6 max-w-md" />}
      </div>
    );
  }

  const indexing = (tasks.data?.length ?? 0) > 0;
  const sourcesOpen = showSources ?? (wall.items.length === 0 && !wall.assets.isPending);
  const filtered = Object.keys(query).some((key) => key !== "sort");
  const error = actionError ?? (wall.error ? describeError(t, wall.error) : null);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-3 px-6 pb-3 pt-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-medium">{t("library.title")}</h1>
            {total !== undefined && (
              <span className="text-xs text-muted-foreground">
                {query.q ? `${t("filters.searching", { q: query.q })} · ` : ""}
                {t("filters.results", { count: total })}
              </span>
            )}
            {byDate && anchor && (
              <Button variant="ghost" size="sm" onClick={() => setAnchor(null)}>
                <ArrowUpToLine className="size-3.5" />
                {oldestFirst ? t("library.backToOldest") : t("library.backToNewest")}
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={sourcesOpen}
              onClick={() => setShowSources(!sourcesOpen)}
            >
              <HardDrive className="size-3.5" />
              {t("library.subtitle", { count: roots.data.length })}
              <ChevronDown
                className={cn("size-3.5 transition-transform", sourcesOpen && "rotate-180")}
              />
            </Button>
            <Button variant="secondary" size="sm" onClick={() => void addFolder()} disabled={busy}>
              <FolderPlus className="size-3.5" />
              {t("library.addFolder")}
            </Button>
          </div>
        </div>

        {error && <ErrorBanner message={error} />}

        {sourcesOpen && (
          <ul className="max-h-52 divide-y overflow-y-auto rounded-lg border bg-card">
            {roots.data.map((root) => (
              <RootRow
                key={root.id}
                root={root}
                task={rootTasks.get(root.id)}
                selected={selection?.kind === "root" && selection.id === root.id}
                onSelect={() => onSelect({ kind: "root", id: root.id })}
                onRescan={() => void run(() => scanRoot.mutateAsync(root.id))}
                onStop={(task) => void run(() => cancelTask.mutateAsync(task.id))}
                onRemove={() => void removeFolder(root)}
              />
            ))}
          </ul>
        )}

        <FilterBar
          query={query}
          onChange={setQuery}
          mode={mode}
          onModeChange={changeMode}
          grouped={grouped}
          onGroupedChange={changeGrouped}
        />
        {wall.selection.selected.size > 1 && (
          <SelectionBar
            ids={wall.selectedIds}
            onClear={wall.clearSelection}
            onError={(cause) => setActionError(describeError(t, cause))}
          />
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1">
          {wall.items.length > 0 ? (
            <PhotoWall
              key={byDate ? (anchor ?? "start") : "all"}
              groups={groups}
              mode={mode}
              selection={wall.selection}
              onSelect={wall.select}
              onOpen={wall.open}
              onReachEnd={wall.loadMore}
              onKeyDown={wall.onKeyDown}
            />
          ) : (
            <p className="flex items-start justify-center gap-2 px-6 pt-10 text-center text-xs text-subtle-foreground">
              <Info className="mt-px size-3.5 shrink-0" />
              {wall.assets.isPending
                ? t("wall.loading")
                : filtered
                  ? t("wall.empty")
                  : indexing
                    ? t("library.gridIndexing")
                    : t("library.gridEmpty")}
            </p>
          )}
        </div>
        {byDate && (
          <DateRail
            query={railQuery}
            oldestFirst={oldestFirst}
            current={anchor}
            onJump={setAnchor}
          />
        )}
      </div>
    </div>
  );
}

function RootRow({
  root,
  task,
  selected,
  onSelect,
  onRescan,
  onStop,
  onRemove,
}: {
  root: StorageRoot;
  task: Task | undefined;
  selected: boolean;
  onSelect: () => void;
  onRescan: () => void;
  onStop: (task: Task) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const { stats } = root;
  const details = [
    t("library.stats.files", { count: stats.file_count }),
    stats.pending_count > 0 && !task
      ? t("library.stats.pending", { count: stats.pending_count })
      : null,
    stats.error_count > 0 ? t("library.stats.errors", { count: stats.error_count }) : null,
    stats.missing_count > 0 ? t("library.stats.missing", { count: stats.missing_count }) : null,
  ].filter(Boolean);

  return (
    <li
      className={cn(
        "group relative flex items-center gap-3 px-4 py-2.5 transition-colors",
        selected ? "bg-accent" : "hover:bg-accent/50",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <HardDrive
          className={cn(
            "size-5 shrink-0",
            root.is_available ? "text-muted-foreground" : "text-destructive",
          )}
          strokeWidth={1.5}
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="truncate font-medium">{root.display_name}</span>
            <span className="truncate text-[11px] text-subtle-foreground">
              {task ? <TaskLabel task={task} /> : details.join(" · ")}
            </span>
          </span>
          <span className="block truncate font-mono text-[11.5px] text-muted-foreground">
            {root.path}
          </span>
        </span>
        {!task && <StatusBadge root={root} />}
      </button>

      <div className="flex shrink-0 items-center gap-0.5">
        {task ? (
          <Tooltip label={t("library.stopTask")}>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onStop(task)}
              aria-label={`${t("library.stopTask")} ${root.display_name}`}
            >
              <Square className="size-3.5" />
            </Button>
          </Tooltip>
        ) : (
          <Tooltip label={t("library.rescan")}>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onRescan}
              disabled={!root.is_available}
              aria-label={`${t("library.rescan")} ${root.display_name}`}
              className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
            >
              <RefreshCw className="size-3.5" />
            </Button>
          </Tooltip>
        )}
        <Tooltip label={t("library.remove")}>
          <Button
            variant="destructive"
            size="icon-sm"
            onClick={onRemove}
            aria-label={`${t("library.remove")} ${root.display_name}`}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </Tooltip>
      </div>

      {task && <ProgressBar task={task} />}
    </li>
  );
}

function TaskLabel({ task }: { task: Task }) {
  const { t } = useTranslation();
  if (task.status === "pending") return <>{t("library.task.queued")}</>;
  if (task.kind === "scan_storage_root") {
    return <>{t("library.task.scanning", { count: task.progress_current })}</>;
  }
  return (
    <>
      {t("library.task.ingesting", {
        current: task.progress_current,
        total: task.progress_total ?? 0,
      })}
    </>
  );
}

function ProgressBar({ task }: { task: Task }) {
  const total = task.progress_total ?? 0;
  const determinate = task.status === "running" && task.kind !== "scan_storage_root" && total > 0;
  const percent = determinate ? Math.min(100, (task.progress_current / total) * 100) : 0;
  return (
    <span className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-transparent">
      <span
        className={cn(
          "block h-full bg-highlight transition-[width] duration-500",
          !determinate && "w-1/4 animate-pulse",
        )}
        style={determinate ? { width: `${percent}%` } : undefined}
      />
    </span>
  );
}

function StatusBadge({ root }: { root: StorageRoot }) {
  const { t } = useTranslation();
  const offline = !root.is_available;
  if (!offline && root.status === "ready") return null;
  return (
    <span
      title={offline ? t("library.offlineHint") : undefined}
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-[11px]",
        offline || root.status === "error"
          ? "border-destructive/40 text-destructive"
          : "text-muted-foreground",
      )}
    >
      {offline ? t("library.rootStatus.offline") : t(`library.rootStatus.${root.status}`)}
    </span>
  );
}

function ErrorBanner({ message, className }: { message: string; className?: string }) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-left text-xs text-destructive",
        className,
      )}
    >
      <AlertCircle className="mt-px size-3.5 shrink-0" />
      <span className="select-text">{message}</span>
    </div>
  );
}

function CenteredMessage({ children, tone }: { children: ReactNode; tone?: "error" }) {
  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-center gap-3 px-8 text-center",
        tone === "error" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {children}
    </div>
  );
}
