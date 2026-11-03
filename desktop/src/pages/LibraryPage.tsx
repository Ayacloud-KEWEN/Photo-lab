import type { TFunction } from "i18next";
import {
  AlertCircle,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Info,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { ApiError } from "@/api/client";
import {
  tasksByRoot,
  useActiveTasks,
  useAssets,
  useCancelTask,
  useCreateStorageRoot,
  useDeleteStorageRoot,
  useScanStorageRoot,
  useStorageRoots,
} from "@/api/hooks";
import type { StorageRoot, Task } from "@/api/types";
import { MediaGrid } from "@/components/library/MediaGrid";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { confirmAction, pickDirectory } from "@/lib/dialogs";
import { cn } from "@/lib/utils";
import type { Selection } from "@/selection";

interface LibraryPageProps {
  selection: Selection;
  onSelect: (selection: Selection) => void;
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
  const { t } = useTranslation();
  const backend = useBackendStatus();
  const roots = useStorageRoots();
  const tasks = useActiveTasks();
  const assets = useAssets();
  const createRoot = useCreateStorageRoot();
  const deleteRoot = useDeleteStorageRoot();
  const scanRoot = useScanStorageRoot();
  const cancelTask = useCancelTask();
  const [actionError, setActionError] = useState<string | null>(null);

  const rootTasks = useMemo(() => tasksByRoot(tasks.data), [tasks.data]);
  const items = useMemo(() => assets.data?.pages.flatMap((page) => page.items) ?? [], [assets.data]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = assets;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

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
  const selectedAssetId = selection?.kind === "asset" ? selection.id : null;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-6 pt-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-lg font-medium">{t("library.title")}</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("library.subtitle", { count: roots.data.length })}
            </p>
          </div>
          <Button variant="secondary" onClick={() => void addFolder()} disabled={busy}>
            <FolderPlus />
            {t("library.addFolder")}
          </Button>
        </div>

        {actionError && <ErrorBanner message={actionError} className="mt-4" />}

        <ul className="mt-4 max-h-52 divide-y overflow-y-auto rounded-lg border bg-card">
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

        <div className="mb-2 mt-5 flex items-baseline justify-between">
          <h2 className="text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
            {t("library.allMedia")}
          </h2>
          {items.length > 0 && (
            <span className="text-[11px] text-subtle-foreground">
              {t("library.itemCount", { count: items.length })}
              {hasNextPage ? "+" : ""}
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {items.length > 0 ? (
          <MediaGrid
            assets={items}
            selectedId={selectedAssetId}
            onSelect={(id) => onSelect({ kind: "asset", id })}
            onReachEnd={loadMore}
          />
        ) : (
          <p className="flex items-start justify-center gap-2 px-6 pt-10 text-center text-xs text-subtle-foreground">
            <Info className="mt-px size-3.5 shrink-0" />
            {assets.isPending || indexing ? t("library.gridIndexing") : t("library.gridEmpty")}
          </p>
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
