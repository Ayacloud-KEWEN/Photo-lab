import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useMapWebActions, useSettings, useUpdateSettings } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** The address of the user's MapWeb, where photos can be sent (only when asked). */
export function MapWebSettings() {
  const { t } = useTranslation();
  const settings = useSettings();
  const update = useUpdateSettings();
  const { test } = useMapWebActions();
  const saved = settings.data?.mapweb_url ?? "";
  const [draft, setDraft] = useState<string | null>(null);
  const url = (draft ?? saved).trim();
  const changed = draft !== null && url !== saved;
  const failure = test.error ?? update.error;

  const save = () =>
    update.mutate({ mapweb_url: url }, { onSuccess: () => setDraft(null) });

  return (
    <div className="space-y-3">
      <p className="max-w-lg text-xs leading-relaxed text-subtle-foreground">
        {t("mapweb.hint")}
      </p>
      <div className="flex max-w-xl flex-wrap items-center gap-2">
        <Input
          aria-label={t("mapweb.address")}
          placeholder="http://kevin:8788"
          value={draft ?? saved}
          onChange={(event) => {
            setDraft(event.target.value);
            test.reset();
            update.reset();
          }}
          className="h-8 min-w-64 flex-1 font-mono text-[12px]"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!url || test.isPending}
          onClick={() => test.mutate(url)}
        >
          {test.isPending && <Loader2 className="animate-spin" />}
          {t("mapweb.test")}
        </Button>
        <Button size="sm" disabled={!changed || !url || update.isPending} onClick={save}>
          {t("mapweb.save")}
        </Button>
        {saved && !changed && (
          <Button
            size="sm"
            variant="ghost"
            disabled={update.isPending}
            onClick={() => update.mutate({ mapweb_url: "" }, { onSuccess: () => setDraft(null) })}
          >
            {t("mapweb.remove")}
          </Button>
        )}
      </div>
      {test.data && (
        <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Check className="size-3.5 text-success" />
          {t("mapweb.connected", { count: test.data.point_count })}
        </p>
      )}
      {failure && (
        <p role="alert" className="max-w-xl select-text text-xs leading-relaxed text-destructive">
          {mapWebError(failure, t)}
        </p>
      )}
    </div>
  );
}

/** A MapWeb error in words: unreachable, not MapWeb, or the server's answer. */
export function mapWebError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError && error.code === "mapweb_failed") {
    const reason = error.details.reason ?? error.details.detail ?? error.message;
    return error.details.status === undefined
      ? t("mapweb.unreachable", { reason: String(reason) })
      : t("mapweb.failed", { reason: `${String(error.details.status)} ${String(reason)}` });
  }
  return error instanceof ApiError ? error.message : String(error);
}
