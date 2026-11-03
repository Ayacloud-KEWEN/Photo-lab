import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { useHealth, useStorageRoots } from "@/api/hooks";
import { LANGUAGES } from "@/i18n";
import { cn } from "@/lib/utils";

export function StatusBar() {
  const { t, i18n } = useTranslation();
  const backend = useBackendStatus();
  const health = useHealth();
  const roots = useStorageRoots();

  let tone: "pending" | "ok" | "error";
  let label: string;
  if (backend.state === "failed") {
    tone = "error";
    label = t("status.failed");
  } else if (backend.state === "starting" || (health.isPending && !health.isError)) {
    tone = "pending";
    label = t("status.starting");
  } else if (health.isError) {
    tone = "error";
    label = t("status.disconnected");
  } else {
    tone = "ok";
    label = t("status.connected");
  }

  const language = LANGUAGES.find((item) => item.code === i18n.language)?.label;

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t bg-surface px-3 text-[11px] text-muted-foreground">
      <span
        className="flex items-center gap-1.5"
        title={backend.state === "failed" ? backend.message : undefined}
      >
        <span
          className={cn(
            "size-1.5 rounded-full",
            tone === "ok" && "bg-success",
            tone === "pending" && "animate-pulse bg-warning",
            tone === "error" && "bg-destructive",
          )}
        />
        {label}
      </span>
      {health.data && (
        <span>{t("status.schema", { version: health.data.database.schema_version })}</span>
      )}
      {roots.data && <span>{t("status.roots", { count: roots.data.length })}</span>}
      <span className="ml-auto">{language}</span>
      <span>LUMEN Studio {health.data?.app_version ?? ""}</span>
    </footer>
  );
}
