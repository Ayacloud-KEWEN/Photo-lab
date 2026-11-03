import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { StorageRoot } from "@/api/types";
import { formatDateTime } from "@/lib/format";

export function Inspector({ root }: { root: StorageRoot | undefined }) {
  const { t } = useTranslation();
  return (
    <aside
      aria-label={t("inspector.title")}
      className="flex w-72 shrink-0 flex-col border-l bg-panel"
    >
      <div className="flex h-9 items-center border-b px-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {t("inspector.title")}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {root ? (
          <RootDetails root={root} />
        ) : (
          <p className="pt-8 text-center text-xs text-subtle-foreground">{t("inspector.empty")}</p>
        )}
      </div>
    </aside>
  );
}

function RootDetails({ root }: { root: StorageRoot }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="space-y-4">
      <h2 className="break-words text-sm font-medium">{root.display_name}</h2>
      <dl className="space-y-3">
        <Field label={t("inspector.path")}>
          <span className="select-text break-all font-mono text-[11.5px]">{root.path}</span>
        </Field>
        <Field label={t("inspector.status")}>{t(`library.rootStatus.${root.status}`)}</Field>
        <Field label={t("inspector.availability")}>
          {root.is_available ? t("inspector.available") : t("inspector.unavailable")}
        </Field>
        <Field label={t("inspector.volumeLabel")}>{root.volume_label ?? "—"}</Field>
        <Field label={t("inspector.volumeSerial")}>
          <span className="select-text font-mono text-[11.5px]">{root.volume_serial ?? "—"}</span>
        </Field>
        <Field label={t("inspector.addedAt")}>{formatDateTime(root.created_at, i18n.language)}</Field>
        <Field label={t("inspector.lastScanned")}>
          {root.last_scanned_at
            ? formatDateTime(root.last_scanned_at, i18n.language)
            : t("inspector.never")}
        </Field>
      </dl>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="mb-0.5 text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="text-[12.5px] text-foreground">{children}</dd>
    </div>
  );
}
