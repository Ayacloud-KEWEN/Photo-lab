import { AlertTriangle, DatabaseBackup, FolderOpen, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useBackupActions, useBackups, useSettings, useUpdateSettings } from "@/api/hooks";
import type { BackupInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { confirmAction, pickDatabaseFile, pickDirectory } from "@/lib/dialogs";
import { formatBytes, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const INTERVALS = [1, 3, 7, 30] as const;
const KEEP = [5, 10, 20, 50] as const;
const SHOWN = 6;

type Message = { tone: "ok" | "error"; text: string } | null;

export function BackupSettings() {
  const { t, i18n } = useTranslation();
  const settings = useSettings();
  const update = useUpdateSettings();
  const backups = useBackups();
  const actions = useBackupActions();
  const [message, setMessage] = useState<Message>(null);
  const [showAll, setShowAll] = useState(false);
  const busy = actions.create.isPending || actions.restore.isPending;
  if (!settings.data) return null;
  const app = settings.data;
  const list = backups.data;
  const date = (item: BackupInfo) => formatDateTime(item.created_at, i18n.language);

  const fail = (error: unknown) =>
    setMessage({
      tone: "error",
      text: error instanceof ApiError ? error.message : t("settings.backupFailed"),
    });

  const backupNow = () => {
    setMessage(null);
    actions.create.mutate(undefined, {
      onSuccess: (made) =>
        setMessage({ tone: "ok", text: t("settings.backupDone", { name: made.name }) }),
      onError: fail,
    });
  };

  const restore = async (body: { name: string } | { path: string }, label: string) => {
    const ok = await confirmAction(t("settings.restoreConfirm", { backup: label }), {
      title: t("settings.restore"),
      okLabel: t("settings.restore"),
      cancelLabel: t("settings.cancel"),
    });
    if (!ok) return;
    setMessage(null);
    actions.restore.mutate(body, {
      onSuccess: (result) =>
        setMessage({
          tone: "ok",
          text: t("settings.restoreDone", {
            backup: date(result.restored),
            count: result.restored.asset_count,
            safety: result.safety_backup.name,
          }),
        }),
      onError: fail,
    });
  };

  const restoreFromFile = async () => {
    const path = await pickDatabaseFile(t("settings.restoreFromFile"), t("settings.backupFiles"));
    if (path) void restore({ path }, path);
  };

  const chooseFolder = async () => {
    const folder = await pickDirectory(t("settings.backupFolder"));
    if (folder) update.mutate({ backup_folder: folder }, { onSuccess: () => void backups.refetch() });
  };

  const items = list?.items ?? [];
  const shown = showAll ? items : items.slice(0, SHOWN);

  return (
    <div className="space-y-3">
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          checked={app.backup_auto}
          disabled={update.isPending}
          onChange={(event) => update.mutate({ backup_auto: event.target.checked })}
          className="mt-0.5 size-4 accent-[var(--highlight)]"
        />
        <span>
          <span className="block text-[13px]">{t("settings.backupAuto")}</span>
          <span className="mt-1 block max-w-lg text-xs leading-relaxed text-subtle-foreground">
            {t("settings.backupHint")}
          </span>
        </span>
      </label>

      <dl className="divide-y rounded-lg border bg-card text-[13px]">
        <Row label={t("settings.backupInterval")}>
          <select
            aria-label={t("settings.backupInterval")}
            value={app.backup_interval_days}
            disabled={!app.backup_auto || update.isPending}
            onChange={(event) => update.mutate({ backup_interval_days: Number(event.target.value) })}
            className="h-7 rounded-md border bg-background/60 px-2 text-xs disabled:opacity-50"
          >
            {INTERVALS.map((days) => (
              <option key={days} value={days} className="bg-popover">
                {t(`settings.backupEvery_${days}`)}
              </option>
            ))}
          </select>
        </Row>
        <Row label={t("settings.backupKeep")}>
          <select
            aria-label={t("settings.backupKeep")}
            value={app.backup_keep}
            disabled={!app.backup_auto || update.isPending}
            onChange={(event) => update.mutate({ backup_keep: Number(event.target.value) })}
            className="h-7 rounded-md border bg-background/60 px-2 text-xs disabled:opacity-50"
          >
            {[...new Set([...KEEP, app.backup_keep])].sort((a, b) => a - b).map((count) => (
              <option key={count} value={count} className="bg-popover">
                {t("settings.backupKeepCount", { count })}
              </option>
            ))}
          </select>
        </Row>
        <Row label={t("settings.backupFolder")}>
          <span className="flex min-w-0 items-center gap-2">
            {list && !list.folder_available && (
              <span className="flex items-center gap-1 text-xs text-destructive">
                <AlertTriangle className="size-3.5" />
                {t("settings.backupFolderMissing")}
              </span>
            )}
            <span className="truncate font-mono text-[11.5px] text-muted-foreground" title={list?.folder}>
              {list?.folder}
            </span>
            <Button size="sm" variant="secondary" onClick={() => void chooseFolder()}>
              {t("settings.change")}
            </Button>
            {app.backup_folder && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  update.mutate({ backup_folder: "" }, { onSuccess: () => void backups.refetch() })
                }
              >
                {t("settings.backupFolderDefault")}
              </Button>
            )}
          </span>
        </Row>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy} onClick={backupNow}>
          {actions.create.isPending ? <Loader2 className="animate-spin" /> : <DatabaseBackup />}
          {t("settings.backupNow")}
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void restoreFromFile()}>
          <RotateCcw /> {t("settings.restoreFromFile")}
        </Button>
        {actions.restore.isPending && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> {t("settings.restoring")}
          </span>
        )}
      </div>
      {message && (
        <p
          role="status"
          className={cn(
            "max-w-xl select-text text-xs leading-relaxed",
            message.tone === "ok" ? "text-emerald-400" : "text-destructive",
          )}
        >
          {message.text}
        </p>
      )}

      {items.length > 0 && (
        <ul aria-label={t("settings.backups")} className="divide-y rounded-lg border bg-card">
          {shown.map((item) => (
            <li key={item.path} className="flex items-center gap-3 px-4 py-2 text-[12.5px]">
              <span className="min-w-0 flex-1">
                <span className="block">{date(item)}</span>
                <span className="block truncate text-[11px] text-subtle-foreground" title={item.path}>
                  {t(`settings.backupKind_${item.kind}`)} ·{" "}
                  {t("settings.backupAssets", { count: item.asset_count })} ·{" "}
                  {formatBytes(item.size_bytes, i18n.language)} · v{item.schema_version}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t("settings.reveal")}
                title={t("settings.reveal")}
                onClick={() => actions.reveal.mutate(item.name, { onError: fail })}
              >
                <FolderOpen className="size-3.5" />
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void restore({ name: item.name }, date(item))}
              >
                {t("settings.restore")}
              </Button>
            </li>
          ))}
          {items.length > SHOWN && (
            <li className="px-4 py-1.5">
              <Button size="sm" variant="ghost" onClick={() => setShowAll(!showAll)}>
                {showAll
                  ? t("settings.backupsFewer")
                  : t("settings.backupsAll", { count: items.length })}
              </Button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-4 px-4 py-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 justify-end">{children}</dd>
    </div>
  );
}
