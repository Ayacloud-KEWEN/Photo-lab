import { AlertCircle, FolderOpen, FolderPlus, HardDrive, Info, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { useBackendStatus } from "@/api/backend-context";
import { ApiError } from "@/api/client";
import { useCreateStorageRoot, useDeleteStorageRoot, useStorageRoots } from "@/api/hooks";
import type { StorageRoot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { confirmAction, pickDirectory } from "@/lib/dialogs";
import { cn } from "@/lib/utils";

interface LibraryPageProps {
  selectedRootId: number | null;
  onSelectRoot: (id: number | null) => void;
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

export function LibraryPage({ selectedRootId, onSelectRoot }: LibraryPageProps) {
  const { t } = useTranslation();
  const backend = useBackendStatus();
  const roots = useStorageRoots();
  const createRoot = useCreateStorageRoot();
  const deleteRoot = useDeleteStorageRoot();
  const [actionError, setActionError] = useState<string | null>(null);

  const addFolder = async () => {
    setActionError(null);
    try {
      const path = await pickDirectory(t("library.pickerTitle"));
      if (!path) return;
      const root = await createRoot.mutateAsync({ path });
      onSelectRoot(root.id);
    } catch (error) {
      setActionError(describeError(t, error));
    }
  };

  const removeFolder = async (root: StorageRoot) => {
    setActionError(null);
    const ok = await confirmAction(
      t("library.removeConfirmMessage", { name: root.display_name }),
      {
        title: t("library.removeConfirmTitle"),
        okLabel: t("library.removeConfirmOk"),
        cancelLabel: t("library.cancel"),
      },
    );
    if (!ok) return;
    try {
      await deleteRoot.mutateAsync(root.id);
      if (selectedRootId === root.id) onSelectRoot(null);
    } catch (error) {
      setActionError(describeError(t, error));
    }
  };

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

  return (
    <div className="mx-auto flex max-w-4xl flex-col px-8 py-7">
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

      {actionError && <ErrorBanner message={actionError} className="mt-5" />}

      <h2 className="mb-2 mt-7 text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
        {t("library.sources")}
      </h2>
      <ul className="divide-y overflow-hidden rounded-lg border bg-card">
        {roots.data.map((root) => (
          <RootRow
            key={root.id}
            root={root}
            selected={root.id === selectedRootId}
            onSelect={() => onSelectRoot(root.id)}
            onRemove={() => void removeFolder(root)}
          />
        ))}
      </ul>

      <p className="mt-5 flex items-start gap-2 text-xs leading-relaxed text-subtle-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        {t("library.scanNotice")}
      </p>
    </div>
  );
}

function RootRow({
  root,
  selected,
  onSelect,
  onRemove,
}: {
  root: StorageRoot;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li
      className={cn(
        "group flex items-center gap-3 px-4 py-3 transition-colors",
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
          className={cn("size-5 shrink-0", root.is_available ? "text-muted-foreground" : "text-destructive")}
          strokeWidth={1.5}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{root.display_name}</span>
          <span className="block truncate font-mono text-[11.5px] text-muted-foreground">
            {root.path}
          </span>
        </span>
        <StatusBadge root={root} />
      </button>
      <Tooltip label={t("library.remove")}>
        <Button
          variant="destructive"
          size="icon-sm"
          onClick={onRemove}
          aria-label={`${t("library.remove")} ${root.display_name}`}
          className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
        >
          <Trash2 />
        </Button>
      </Tooltip>
    </li>
  );
}

function StatusBadge({ root }: { root: StorageRoot }) {
  const { t } = useTranslation();
  const offline = !root.is_available;
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-[11px]",
        offline ? "border-destructive/40 text-destructive" : "text-muted-foreground",
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

function CenteredMessage({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: "error";
}) {
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
